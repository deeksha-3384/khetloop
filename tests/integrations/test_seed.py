import importlib.util
import json
import math
import re
from pathlib import Path

from shared.constants import (AI_DECISIONS, CONFIDENCE_BANDS, CROPS, HIGH_RISK_ISSUES,
                              IMAGE_QUALITIES, ISSUES, LANGUAGES, RADAR_MIN_REPORTS,
                              RADAR_RADIUS_KM, RADAR_TIME_WINDOW_HOURS, REPORT_STATUSES,
                              RISK_LEVELS, WHY_CODES)

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "data" / "seed"
IMAGES = ROOT / "data" / "test_images"

FARMER_KEYS = {"id", "name", "language", "telegram_chat_id"}
FARM_KEYS = {"id", "farmer_id", "crop", "sowing_date", "area_label", "lat", "lng"}
REPORT_KEYS = {"id", "farm_id", "image_file", "hours_ago", "suspected_issue", "confidence_band",
               "image_quality", "decision", "status", "visible_symptoms", "voice_transcript",
               "escalation_reason", "why", "weather", "risk", "reply_language", "reply_text"}
ESCALATION_REASONS = {"AI_UNAVAILABLE", "UNCLEAR_AFTER_RETRY", "SEVERITY_KEYWORD",
                      "MEDIUM_CONFIDENCE_HIGH_RISK"}
SEVERITY_STEMS = ["spread", "dying", "whole field", "many plants", "all plants", "ಹರಡ", "ಸಾಯ", "फैल", "मर रहे"]
ALLOWED_STATUSES = {"ai_assessed", "expert_review_pending", "follow_up"}
IMAGE_ISSUE = {"clear_tomato_01.jpg": "early_blight", "clear_tomato_02.jpg": "late_blight",
               "clear_tomato_03.jpg": "healthy", "clear_tomato_04.jpg": "bacterial_spot",
               "clear_tomato_05.jpg": "leaf_curl"}
DEMO_FARM = {"lat": 13.14, "lng": 78.13}   # live demo farm, Kolar North (leader's brief)
MAX_HOURS_AGO = 60                          # leader's brief
DOSAGE = re.compile(r"\d+(\.\d+)?\s*(ml|mg|g|kg|l)\b|per\s+lit(re|er)|spray", re.I)
CHEMICALS = ["mancozeb", "chlorothalonil", "copper oxychloride", "imidacloprid", "carbendazim",
             "metalaxyl", "streptomycin", "pesticide", "fungicide"]


def load(name):
    with open(SEED / name, encoding="utf-8") as f:
        return json.load(f)


FARMERS, FARMS, REPORTS = load("farmers.json"), load("farms.json"), load("reports.json")
FARM_BY_ID = {f["id"]: f for f in FARMS}
FARMER_BY_ID = {f["id"]: f for f in FARMERS}


def haversine_km(a, b):
    lat1, lng1, lat2, lng2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def eligible(issue=None):
    """Reports the contract's check_cluster would consider (optionally for one issue)."""
    return [r for r in REPORTS
            if FARM_BY_ID[r["farm_id"]]["crop"] == "tomato"
            and r["suspected_issue"] not in ("unknown", "healthy")
            and (issue is None or r["suspected_issue"] == issue)
            and r["confidence_band"] in ("medium", "high")
            and r["hours_ago"] <= RADAR_TIME_WINDOW_HOURS]


def farm_groups(issue):
    """For each eligible report as centre: the distinct farms within the radius."""
    return [{r["farm_id"] for r in eligible(issue)
             if haversine_km(FARM_BY_ID[c["farm_id"]], FARM_BY_ID[r["farm_id"]]) <= RADAR_RADIUS_KM}
            for c in eligible(issue)]


# ---------- shape and ids ----------
def test_row_count_is_within_leader_brief():
    assert 20 <= len(FARMERS) + len(FARMS) + len(REPORTS) <= 30


def test_exact_keys_and_no_data_source():
    assert all(set(r) == FARMER_KEYS for r in FARMERS)
    assert all(set(r) == FARM_KEYS for r in FARMS)
    assert all(set(r) == REPORT_KEYS for r in REPORTS)  # loader sets data_source='simulated'


def test_ids_have_prefix_and_seed_marker():
    for rows, prefix in ((FARMERS, "fmr"), (FARMS, "farm"), (REPORTS, "rep")):
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids))
        assert all(re.fullmatch(prefix + r"_5eed[0-9a-f]{4}", i) for i in ids), prefix


def test_references_resolve_and_images_exist():
    assert all(f["farmer_id"] in FARMER_BY_ID for f in FARMS)
    assert all(r["farm_id"] in FARM_BY_ID for r in REPORTS)
    for r in REPORTS:
        assert (IMAGES / r["image_file"]).is_file(), r["image_file"]


def test_values_come_from_shared_constants():
    assert all(f["language"] in LANGUAGES for f in FARMERS)
    assert all(f["telegram_chat_id"] is None for f in FARMERS)   # never seed a chat id
    assert all(f["crop"] in CROPS for f in FARMS)
    for r in REPORTS:
        assert r["suspected_issue"] in ISSUES and r["confidence_band"] in CONFIDENCE_BANDS
        assert r["image_quality"] in IMAGE_QUALITIES and r["decision"] in AI_DECISIONS
        assert r["status"] in REPORT_STATUSES and r["status"] in ALLOWED_STATUSES
        assert isinstance(r["hours_ago"], (int, float)) and 0 <= r["hours_ago"] <= MAX_HOURS_AGO, r["id"]
        assert isinstance(r["visible_symptoms"], list)


def test_coordinates_are_rounded_to_two_decimals():
    for f in FARMS:
        assert round(f["lat"], 2) == f["lat"] and round(f["lng"], 2) == f["lng"], f["id"]


# ---------- consistency with the decision rules ----------
def test_decisions_follow_the_contract_rules():
    for r in REPORTS:
        text = (r["voice_transcript"] or "").lower()
        severe = any(s in text for s in SEVERITY_STEMS)
        unclear = (r["image_quality"] == "poor" or r["confidence_band"] == "low"
                   or r["suspected_issue"] == "unknown")
        if r["decision"] == "escalate_to_expert":
            assert r["escalation_reason"] in ESCALATION_REASONS, r["id"]
            assert r["status"] == "expert_review_pending", r["id"]
        else:
            assert r["escalation_reason"] is None, r["id"]
            assert r["status"] in ("ai_assessed", "follow_up"), r["id"]
        if r["escalation_reason"] == "SEVERITY_KEYWORD":
            assert severe and not unclear, r["id"]
        elif r["escalation_reason"] == "MEDIUM_CONFIDENCE_HIGH_RISK":
            assert r["confidence_band"] == "medium" and r["suspected_issue"] in HIGH_RISK_ISSUES
        elif r["escalation_reason"] == "UNCLEAR_AFTER_RETRY":
            assert unclear, r["id"]
        else:
            assert not severe, f"{r['id']} has a severity word but no SEVERITY_KEYWORD escalation"
            if unclear:
                assert r["decision"] == "abstain_request_better_image", r["id"]
            elif r["confidence_band"] == "medium" and r["suspected_issue"] in HIGH_RISK_ISSUES:
                raise AssertionError(f"{r['id']} should be escalated")
            else:
                assert r["decision"] == "preliminary_assessment", r["id"]


def test_unclear_after_retry_follows_an_abstain_30_minutes_earlier():
    for r in REPORTS:
        if r["escalation_reason"] == "UNCLEAR_AFTER_RETRY":
            prev = [o for o in REPORTS if o["farm_id"] == r["farm_id"]
                    and o["decision"] == "abstain_request_better_image"
                    and 0 < (o["hours_ago"] - r["hours_ago"]) * 60 <= 30]
            assert prev, r["id"]


def test_image_matches_the_claimed_issue():
    for r in REPORTS:
        if r["image_file"] in IMAGE_ISSUE:
            assert r["suspected_issue"] == IMAGE_ISSUE[r["image_file"]], r["id"]
        else:
            assert r["suspected_issue"] == "unknown", r["id"]


# ---------- the clustering story (leader's rules) ----------
def test_early_blight_forms_one_potential_cluster_of_three_chikkaballapur_farms():
    groups = farm_groups("early_blight")
    best = max(groups, key=len)
    assert len(best) >= RADAR_MIN_REPORTS
    assert best == {"farm_5eed0004", "farm_5eed0005", "farm_5eed0008"}
    members = [r for r in eligible("early_blight") if r["farm_id"] in best]
    assert {FARM_BY_ID[r["farm_id"]]["area_label"] for r in members} == {"Chikkaballapur"}
    assert len(members) == 3                       # 'watch' size


def test_nothing_near_the_demo_farm_can_form_a_cluster():
    near = [r for r in eligible() if haversine_km(DEMO_FARM, FARM_BY_ID[r["farm_id"]]) <= RADAR_RADIUS_KM]
    assert not [r for r in near if r["suspected_issue"] == "early_blight"]
    for issue in {r["suspected_issue"] for r in near}:
        assert len([r for r in near if r["suspected_issue"] == issue]) <= 1, issue   # demo farm adds one


def test_cluster_group_is_more_than_10_km_from_the_demo_farm():
    for r in eligible("early_blight"):
        f = FARM_BY_ID[r["farm_id"]]
        if f["area_label"] == "Chikkaballapur":
            assert haversine_km(DEMO_FARM, f) > RADAR_RADIUS_KM


def test_no_other_group_of_three_farms_exists():
    for issue in {r["suspected_issue"] for r in eligible()} - {"early_blight"}:
        assert max(len(g) for g in farm_groups(issue)) < RADAR_MIN_REPORTS, issue


def test_cluster_members_have_no_severity_words():
    for r in eligible("early_blight"):
        if FARM_BY_ID[r["farm_id"]]["area_label"] != "Chikkaballapur":
            continue
        assert not any(s in (r["voice_transcript"] or "").lower() for s in SEVERITY_STEMS), r["id"]


def test_late_blight_escalated_case_is_in_kolar_north():
    lb = [r for r in REPORTS if r["suspected_issue"] == "late_blight"]
    assert len(lb) == 1 and lb[0]["decision"] == "escalate_to_expert"
    assert FARM_BY_ID[lb[0]["farm_id"]]["area_label"] == "Kolar North"


# ---------- why, weather, risk, reply (leader's request) ----------
def nearby_count(r):
    f = FARM_BY_ID[r["farm_id"]]
    return len({o["farm_id"] for o in eligible(r["suspected_issue"])
                if r in eligible() and o is not r and o["farm_id"] != r["farm_id"]
                and o["hours_ago"] > r["hours_ago"] and o["hours_ago"] - r["hours_ago"] <= RADAR_TIME_WINDOW_HOURS
                and haversine_km(f, FARM_BY_ID[o["farm_id"]]) <= RADAR_RADIUS_KM})


def test_why_is_valid_and_ends_with_not_confirmed():
    for r in REPORTS:
        codes = [w["code"] for w in r["why"]]
        assert codes and codes[-1] == "NOT_CONFIRMED", r["id"]
        assert len(codes) == len(set(codes)) and all(c in WHY_CODES for c in codes), r["id"]
        assert all(isinstance(w["text"], str) and w["text"].strip() for w in r["why"])
        assert "WEATHER_CONTEXT" in codes, r["id"]
        assert ("IMAGE_QUALITY" in codes) == (r["image_quality"] == "poor"), r["id"]
        assert ("LOW_CONFIDENCE" in codes) == (r["confidence_band"] == "low"), r["id"]
        assert ("NEARBY_REPORTS" in codes) == (nearby_count(r) > 0), r["id"]   # never claim what is not true


def test_weather_is_simulated_and_consistent():
    for r in REPORTS:
        w = r["weather"]
        assert w["data_source"] == "simulated", r["id"]
        assert {"rain_expected", "rain_mm_next_48h", "humidity_pct_avg", "temp_c_avg"} <= set(w)
        assert w["rain_expected"] == (w["rain_mm_next_48h"] >= 2.0), r["id"]
        has_rain_line = "Rain is forecast" in next(x["text"] for x in r["why"] if x["code"] == "WEATHER_CONTEXT")
        assert has_rain_line == w["rain_expected"], r["id"]


def test_risk_shape():
    for r in REPORTS:
        assert r["risk"]["level"] in RISK_LEVELS and isinstance(r["risk"]["reasons"], list)
        assert (r["risk"]["level"] == "elevated") == bool(r["risk"]["reasons"]), r["id"]


def test_reply_matches_farmer_language_and_script():
    ranges = {"kn": ("ಀ", "೿"), "hi": ("ऀ", "ॿ")}
    for r in REPORTS:
        lang = FARMER_BY_ID[FARM_BY_ID[r["farm_id"]]["farmer_id"]]["language"]
        assert r["reply_language"] == lang, r["id"]
        assert isinstance(r["reply_text"], str) and r["reply_text"].strip()
        if lang in ranges:
            lo, hi = ranges[lang]
            assert any(lo <= c <= hi for c in r["reply_text"]), r["id"]
        else:
            assert "not a confirmed diagnosis" in r["reply_text"] or r["decision"] == "abstain_request_better_image"


def test_voice_transcripts_are_in_the_farmers_language():
    ranges = {"kn": ("ಀ", "೿"), "hi": ("ऀ", "ॿ")}
    for r in REPORTS:
        if r["voice_transcript"] and r["reply_language"] in ranges:
            lo, hi = ranges[r["reply_language"]]
            assert any(lo <= c <= hi for c in r["voice_transcript"]), r["id"]


def test_no_forbidden_words_dosages_or_chemicals():
    blob = " ".join(json.dumps(x, ensure_ascii=False).lower() for x in FARMERS + FARMS + REPORTS)
    assert "outbreak" not in blob
    assert not any(c in blob for c in CHEMICALS)
    for r in REPORTS:
        assert not DOSAGE.search(r["reply_text"]), r["id"]
        assert not DOSAGE.search(" ".join(w["text"] for w in r["why"])), r["id"]


# ---------- variety (leader brief) ----------
def test_data_is_varied():
    assert {f["crop"] for f in FARMS} >= {"tomato", "chilli", "potato"}
    assert len({f["area_label"] for f in FARMS}) >= 4
    assert {r["decision"] for r in REPORTS} == set(AI_DECISIONS)
    assert {r["confidence_band"] for r in REPORTS} == set(CONFIDENCE_BANDS)
    assert {r["status"] for r in REPORTS} == ALLOWED_STATUSES
    assert {r["suspected_issue"] for r in REPORTS} >= {
        "early_blight", "late_blight", "healthy", "bacterial_spot", "leaf_curl", "unknown"}
    assert {f["language"] for f in FARMERS} == set(LANGUAGES)
    assert {r["escalation_reason"] for r in REPORTS if r["escalation_reason"]} == {
        "MEDIUM_CONFIDENCE_HIGH_RISK", "SEVERITY_KEYWORD", "UNCLEAR_AFTER_RETRY"}


# ---------- files are exactly what the generator produces ----------
def test_seed_files_match_the_generator():
    spec = importlib.util.spec_from_file_location("make_seed", Path(__file__).with_name("make_seed.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    farmers, farms, reports = mod.build()
    assert (farmers, farms, reports) == (FARMERS, FARMS, REPORTS), "re-run: python tests/integrations/make_seed.py"