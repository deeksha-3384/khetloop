import json
import math
import re
from pathlib import Path

from shared.constants import (AI_DECISIONS, CONFIDENCE_BANDS, CROPS, HIGH_RISK_ISSUES,
                              IMAGE_QUALITIES, ISSUES, LANGUAGES, RADAR_MIN_REPORTS,
                              RADAR_RADIUS_KM, RADAR_TIME_WINDOW_HOURS, REPORT_STATUSES)

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "data" / "seed"
IMAGES = ROOT / "data" / "test_images"

FARMER_KEYS = {"id", "name", "language", "telegram_chat_id"}
FARM_KEYS = {"id", "farmer_id", "crop", "sowing_date", "area_label", "lat", "lng"}
REPORT_KEYS = {"id", "farm_id", "image_file", "hours_ago", "suspected_issue", "confidence_band",
               "image_quality", "decision", "status", "visible_symptoms", "voice_transcript",
               "escalation_reason"}
ESCALATION_REASONS = {"AI_UNAVAILABLE", "UNCLEAR_AFTER_RETRY", "SEVERITY_KEYWORD",
                      "MEDIUM_CONFIDENCE_HIGH_RISK"}
# short stems, as used by the backend keyword matching (see leader's note)
SEVERITY_STEMS = ["spread", "dying", "whole field", "many plants", "all plants", "ಹರಡ", "ಸಾಯ", "फैल", "मर रहे"]
# seeds never contain a finished expert review, so these statuses are not allowed
ALLOWED_STATUSES = {"ai_assessed", "expert_review_pending", "follow_up"}


def load(name):
    with open(SEED / name, encoding="utf-8") as f:
        return json.load(f)


FARMERS, FARMS, REPORTS = load("farmers.json"), load("farms.json"), load("reports.json")
FARM_BY_ID = {f["id"]: f for f in FARMS}


def haversine_km(a, b):
    lat1, lng1, lat2, lng2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def eligible(issue):
    """Reports the contract's check_cluster would consider for this issue."""
    return [r for r in REPORTS
            if FARM_BY_ID[r["farm_id"]]["crop"] == "tomato" and r["suspected_issue"] == issue
            and r["confidence_band"] in ("medium", "high")
            and r["hours_ago"] <= RADAR_TIME_WINDOW_HOURS]


def clusters_for(issue):
    """For each report as centre: distinct farms within the radius."""
    found = []
    for centre in eligible(issue):
        c = FARM_BY_ID[centre["farm_id"]]
        farms = {r["farm_id"] for r in eligible(issue)
                 if haversine_km(c, FARM_BY_ID[r["farm_id"]]) <= RADAR_RADIUS_KM}
        found.append(farms)
    return found


# ---------- shape and ids ----------
def test_row_counts_match_leader_brief():
    assert 20 <= len(FARMERS) + len(FARMS) + len(REPORTS) <= 30


def test_exact_keys_and_no_data_source():
    assert all(set(r) == FARMER_KEYS for r in FARMERS)
    assert all(set(r) == FARM_KEYS for r in FARMS)
    assert all(set(r) == REPORT_KEYS for r in REPORTS)  # loader always sets 'simulated'


def test_ids_have_prefix_and_seed_marker():
    for rows, prefix in ((FARMERS, "fmr"), (FARMS, "farm"), (REPORTS, "rep")):
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids))
        assert all(re.fullmatch(prefix + r"_5eed[0-9a-f]{4}", i) for i in ids), prefix


def test_references_resolve():
    farmer_ids = {f["id"] for f in FARMERS}
    assert all(f["farmer_id"] in farmer_ids for f in FARMS)
    assert all(r["farm_id"] in FARM_BY_ID for r in REPORTS)
    for r in REPORTS:
        assert (IMAGES / r["image_file"]).is_file(), r["image_file"]


def test_values_come_from_shared_constants():
    assert all(f["language"] in LANGUAGES and f["telegram_chat_id"] is None for f in FARMERS)
    assert all(f["crop"] in CROPS for f in FARMS)
    for r in REPORTS:
        assert r["suspected_issue"] in ISSUES and r["confidence_band"] in CONFIDENCE_BANDS
        assert r["image_quality"] in IMAGE_QUALITIES and r["decision"] in AI_DECISIONS
        assert r["status"] in REPORT_STATUSES and r["status"] in ALLOWED_STATUSES
        assert isinstance(r["hours_ago"], (int, float)) and r["hours_ago"] >= 0
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
            assert severe, r["id"]
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


def test_image_matches_the_claimed_issue():
    expected = {"clear_tomato_01.jpg": "early_blight", "clear_tomato_02.jpg": "late_blight",
                "clear_tomato_03.jpg": "healthy"}
    for r in REPORTS:
        if r["image_file"] in expected:
            assert r["suspected_issue"] == expected[r["image_file"]], r["id"]
        else:
            assert r["suspected_issue"] == "unknown", r["id"]


# ---------- the clustering story ----------
def test_early_blight_forms_exactly_one_potential_cluster_of_three_farms():
    groups = clusters_for("early_blight")
    assert max(len(g) for g in groups) >= RADAR_MIN_REPORTS
    best = max(groups, key=len)
    assert best == {"farm_5eed0001", "farm_5eed0002", "farm_5eed0004"}
    members = [r for r in eligible("early_blight") if r["farm_id"] in best]
    areas = {FARM_BY_ID[r["farm_id"]]["area_label"] for r in members}
    assert areas == {"Kolar North"} and len(members) == 3  # 'watch' size: 3 to 4 reports


def test_control_reports_do_not_join_the_cluster():
    by_id = {r["id"]: r for r in REPORTS}
    ids = {r["id"] for r in eligible("early_blight")}
    assert "rep_5eed0004" in ids                       # eligible report, but too far away
    c = FARM_BY_ID["farm_5eed0001"]
    assert haversine_km(c, FARM_BY_ID[by_id["rep_5eed0004"]["farm_id"]]) > RADAR_RADIUS_KM
    assert "rep_5eed0005" not in ids                   # low confidence
    assert "rep_5eed0006" not in ids                   # older than the time window
    assert "rep_5eed0013" not in ids                   # older than the time window


def test_two_late_blight_reports_make_no_cluster():
    groups = clusters_for("late_blight")
    assert groups and max(len(g) for g in groups) == 2 < RADAR_MIN_REPORTS


def test_cluster_group_has_no_severity_words():
    for r in eligible("early_blight"):
        text = (r["voice_transcript"] or "").lower()
        assert not any(s in text for s in SEVERITY_STEMS), r["id"]


# ---------- variety (leader brief) ----------
def test_data_is_varied():
    assert {f["crop"] for f in FARMS} >= {"tomato", "chilli", "potato"}
    assert len({f["area_label"] for f in FARMS}) >= 4
    assert {r["decision"] for r in REPORTS} == set(AI_DECISIONS)
    assert {r["confidence_band"] for r in REPORTS} == set(CONFIDENCE_BANDS)
    assert {r["status"] for r in REPORTS} == ALLOWED_STATUSES
    assert {r["suspected_issue"] for r in REPORTS} >= {"early_blight", "late_blight", "healthy", "unknown"}
    assert {f["language"] for f in FARMERS} == set(LANGUAGES)


def test_no_forbidden_words_anywhere():
    blob = " ".join(json.dumps(x, ensure_ascii=False).lower() for x in FARMERS + FARMS + REPORTS)
    assert "outbreak" not in blob