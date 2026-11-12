from datetime import datetime, timedelta, timezone

from backend.rules.clustering import check_cluster
from backend.rules.decision import decide, has_severity_keyword
from backend.rules.risk import compute_risk
from backend.rules.why import build_why
from shared.constants import (AI_DECISIONS, SEVERITY_KEYWORDS_HI, SEVERITY_KEYWORDS_KN, WHY_CODES)


def A(issue="early_blight", band="medium", quality="good"):
    return {"suspected_issue": issue, "confidence_band": band, "image_quality": quality,
            "visible_symptoms": [], "confirmed": False}


# ---------------------------------------------------------------- decide()
def test_clear_photo_gives_preliminary():
    assert decide(A(band="high"), "spots on leaves", 0) == {
        "decision": "preliminary_assessment", "escalation_reason": None}


def test_medium_confidence_ordinary_issue_is_preliminary():
    assert decide(A(), "spots on leaves", 0)["decision"] == "preliminary_assessment"


def test_poor_image_first_time_abstains():
    assert decide(A(quality="poor"), "", 0)["decision"] == "abstain_request_better_image"


def test_poor_image_after_retry_escalates():
    r = decide(A(quality="poor"), "", 1)
    assert r == {"decision": "escalate_to_expert", "escalation_reason": "UNCLEAR_AFTER_RETRY"}


def test_low_confidence_never_gives_preliminary():
    for retry in (0, 1, 2):
        assert decide(A(band="low"), "", retry)["decision"] != "preliminary_assessment"


def test_unknown_issue_abstains_then_escalates():
    assert decide(A(issue="unknown", band="medium"), "", 0)["decision"] == "abstain_request_better_image"
    assert decide(A(issue="unknown", band="medium"), "", 1)["decision"] == "escalate_to_expert"


def test_ai_failure_escalates():
    assert decide(None, "anything", 0) == {"decision": "escalate_to_expert", "escalation_reason": "AI_UNAVAILABLE"}


def test_english_severity_keyword_escalates():
    r = decide(A(band="high"), "It is SPREADING fast in my field", 0)
    assert r == {"decision": "escalate_to_expert", "escalation_reason": "SEVERITY_KEYWORD"}


def test_kannada_and_hindi_severity_keywords_escalate():
    kn = "ನನ್ನ ಟೊಮೇಟೊ " + SEVERITY_KEYWORDS_KN[0]
    hi = "मेरे टमाटर " + SEVERITY_KEYWORDS_HI[0]
    assert decide(A(band="high"), kn, 0)["escalation_reason"] == "SEVERITY_KEYWORD"
    assert decide(A(band="high"), hi, 0)["escalation_reason"] == "SEVERITY_KEYWORD"


def test_english_keyword_needs_whole_word():
    assert has_severity_keyword("I was studying my plants") is False
    assert has_severity_keyword("plants are dying") is True


def test_none_or_empty_transcript_is_safe():
    assert has_severity_keyword(None) is False
    assert decide(A(band="high"), None, 0)["decision"] == "preliminary_assessment"


def test_medium_confidence_high_risk_issue_escalates():
    r = decide(A(issue="late_blight", band="medium"), "", 0)
    assert r == {"decision": "escalate_to_expert", "escalation_reason": "MEDIUM_CONFIDENCE_HIGH_RISK"}


def test_high_confidence_high_risk_issue_is_preliminary():
    assert decide(A(issue="late_blight", band="high"), "", 0)["decision"] == "preliminary_assessment"


def test_decisions_are_always_valid_constants():
    for assessment in (None, A(), A(quality="poor"), A(band="low"), A(issue="late_blight")):
        for retry in (0, 1):
            assert decide(assessment, "spreading", retry)["decision"] in AI_DECISIONS


# ---------------------------------------------------------------- compute_risk()
WET = {"rain_expected": True, "humidity_pct_avg": 82}
DRY = {"rain_expected": False, "humidity_pct_avg": 55}


def test_risk_matches_contract_example():
    assert compute_risk(A(), WET, 2) == {
        "level": "elevated",
        "reasons": ["Similar reports nearby", "Rain forecast", "High humidity"]}


def test_risk_normal_when_dry_and_alone():
    assert compute_risk(A(), DRY, 0) == {"level": "normal", "reasons": []}


def test_risk_handles_missing_weather_and_assessment():
    assert compute_risk(A(), None, 0) == {"level": "normal", "reasons": []}
    assert compute_risk(None, WET, 3) == {"level": "normal", "reasons": []}


def test_risk_ignores_healthy_and_unknown():
    assert compute_risk(A(issue="healthy"), WET, 5)["level"] == "normal"
    assert compute_risk(A(issue="unknown"), WET, 5)["level"] == "normal"


def test_high_risk_issue_is_elevated_even_in_dry_weather():
    assert compute_risk(A(issue="late_blight"), DRY, 0)["level"] == "elevated"


# ---------------------------------------------------------------- build_why()
def test_why_for_escalated_report_has_expected_codes_in_order():
    w = build_why(A(), {**WET, "data_source": "live"}, 2, {"decision": "escalate_to_expert"})
    assert [i["code"] for i in w] == ["IMAGE_SYMPTOMS", "NEARBY_REPORTS", "WEATHER_CONTEXT", "NOT_CONFIRMED"]
    assert w[1]["text"] == "2 similar reports were submitted nearby in the last 72 hours."
    assert w[2]["text"] == "Rain is forecast in the next 48 hours (live forecast)."


def test_why_for_blurry_photo():
    w = build_why(A(issue="unknown", band="low", quality="poor"), None, 0, "abstain_request_better_image")
    assert [i["code"] for i in w] == ["IMAGE_QUALITY", "LOW_CONFIDENCE", "NOT_CONFIRMED"]


def test_why_when_ai_failed():
    w = build_why(None, None, 0, {"decision": "escalate_to_expert"})
    assert "not available" in w[0]["text"] and w[-1]["code"] == "NOT_CONFIRMED"


def test_why_singular_and_no_weather_line_when_missing():
    w = build_why(A(), None, 1, "preliminary_assessment")
    assert "WEATHER_CONTEXT" not in [i["code"] for i in w]
    assert w[1]["text"] == "1 similar report was submitted nearby in the last 72 hours."


def test_why_codes_valid_always_ends_not_confirmed_and_never_says_outbreak():
    cases = [A(), A(issue="healthy"), A(quality="poor"), A(band="low"), None]
    for assessment in cases:
        w = build_why(assessment, {**WET, "data_source": "cached"}, 3, "escalate_to_expert", history_count=2)
        assert all(i["code"] in WHY_CODES for i in w)
        assert w[-1]["code"] == "NOT_CONFIRMED"
        assert "outbreak" not in " ".join(i["text"] for i in w).lower()


# ---------------------------------------------------------------- check_cluster()
class FakeDB:
    def __init__(self, rows=None, clusters=None):
        self.rows = rows or []
        self.clusters = clusters or []
        self.created = []

    def find_similar_recent_reports(self, crop, suspected_issue, since_hours, lat, lng, radius_km):
        return list(self.rows)

    def list_clusters(self):
        return list(self.clusters)

    def create_cluster(self, crop, suspected_issue, area_label, centroid_lat, centroid_lng, severity,
                       report_ids, window_hours, data_source="live"):
        c = {"id": "clu_test0001", "crop": crop, "suspected_issue": suspected_issue, "area_label": area_label,
             "centroid_lat": centroid_lat, "centroid_lng": centroid_lng, "severity": severity,
             "report_count": len(report_ids), "window_hours": window_hours, "label": "potential_cluster",
             "data_source": data_source, "created_at": "2026-11-12T09:20:00Z"}
        self.created.append(c)
        return c


def R(n, farm=None, band="medium", ds="live", issue="early_blight"):
    return {"report_id": "rep_%d" % n, "farm_id": farm or "farm_%d" % n, "confidence_band": band,
            "created_at": "2026-11-12T0%d:00:00Z" % n, "lat": 13.14 + n * 0.01, "lng": 78.13,
            "area_label": "Kolar North", "suspected_issue": issue, "data_source": ds}


NEW = {"report_id": "rep_new", "farm_id": "farm_new", "crop": "tomato", "suspected_issue": "early_blight",
       "confidence_band": "medium", "lat": 13.14, "lng": 78.13, "area_label": "Kolar North",
       "data_source": "live"}


def test_two_farms_make_no_cluster():
    assert check_cluster(NEW, FakeDB([R(1)])) is None


def test_three_farms_make_a_watch_cluster():
    db = FakeDB([R(1), R(2)])
    res = check_cluster(NEW, db)
    assert res["created"] is True and len(db.created) == 1
    assert res["cluster"]["severity"] == "watch" and res["cluster"]["report_count"] == 3
    assert res["cluster"]["label"] == "potential_cluster"
    assert "rep_new" in res["report_ids"]


def test_five_farms_make_an_elevated_cluster():
    res = check_cluster(NEW, FakeDB([R(1), R(2), R(3), R(4)]))
    assert res["cluster"]["severity"] == "elevated" and res["cluster"]["report_count"] == 5


def test_one_farm_sending_many_reports_does_not_count():
    rows = [R(1, farm="farm_a"), R(2, farm="farm_a"), R(3, farm="farm_a"), R(4, farm="farm_a")]
    assert check_cluster(NEW, FakeDB(rows)) is None


def test_stored_triggering_report_is_not_double_counted():
    rows = [R(1), {**R(2), "report_id": "rep_new", "farm_id": "farm_new"}]
    assert check_cluster(NEW, FakeDB(rows)) is None  # only 2 distinct farms


def test_low_confidence_unknown_healthy_or_no_location_never_cluster():
    db = FakeDB([R(1), R(2), R(3)])
    assert check_cluster({**NEW, "confidence_band": "low"}, db) is None
    assert check_cluster({**NEW, "suspected_issue": "unknown"}, db) is None
    assert check_cluster({**NEW, "suspected_issue": "healthy"}, db) is None
    assert check_cluster({**NEW, "lat": None}, db) is None


def test_low_confidence_neighbours_are_ignored():
    assert check_cluster(NEW, FakeDB([R(1, band="low"), R(2, band="low")])) is None


def test_existing_nearby_cluster_is_reused_not_duplicated():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing = {"id": "clu_old00001", "crop": "tomato", "suspected_issue": "early_blight",
                "centroid_lat": 13.15, "centroid_lng": 78.13, "severity": "watch", "report_count": 3,
                "created_at": now}
    db = FakeDB([R(1), R(2)], clusters=[existing])
    res = check_cluster(NEW, db)
    assert res["created"] is False and res["cluster"]["id"] == "clu_old00001" and db.created == []


def test_old_cluster_outside_the_time_window_is_not_reused():
    old = (datetime.now(timezone.utc) - timedelta(hours=100)).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing = {"id": "clu_old00001", "crop": "tomato", "suspected_issue": "early_blight",
                "centroid_lat": 13.15, "centroid_lng": 78.13, "severity": "watch", "report_count": 3,
                "created_at": old}
    res = check_cluster(NEW, FakeDB([R(1), R(2)], clusters=[existing]))
    assert res["created"] is True


def test_far_away_cluster_is_not_reused():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    far = {"id": "clu_far00001", "crop": "tomato", "suspected_issue": "early_blight",
           "centroid_lat": 14.50, "centroid_lng": 78.13, "severity": "watch", "report_count": 3,
           "created_at": now}
    assert check_cluster(NEW, FakeDB([R(1), R(2)], clusters=[far]))["created"] is True


def test_any_simulated_member_makes_the_cluster_simulated():
    res = check_cluster(NEW, FakeDB([R(1, ds="simulated"), R(2)]))
    assert res["cluster"]["data_source"] == "simulated"
    assert check_cluster(NEW, FakeDB([R(1), R(2)]))["cluster"]["data_source"] == "live"


def test_centroid_is_rounded_to_two_decimals():
    c = check_cluster(NEW, FakeDB([R(1), R(2)]))["cluster"]
    assert c["centroid_lat"] == round(c["centroid_lat"], 2) and c["centroid_lng"] == round(c["centroid_lng"], 2)



def test_spread_stems_match_common_spellings_and_inflections():
    for words in ("ಎಲೆಗಳು ಹರಡುತ್ತಿವೆ", "ಹರಡಿದೆ", "पत्ते फैल रहे हैं", "फैला हुआ है"):
        assert has_severity_keyword(words), words


def test_bare_field_words_do_not_trigger_severity():
    for words in ("ನನ್ನ ಹೊಲದಲ್ಲಿ ಟೊಮೇಟೊ ಗಿಡ", "मेरे खेत में टमाटर है"):
        assert not has_severity_keyword(words), words


def test_missing_data_source_makes_the_cluster_unverified():
    res = check_cluster(NEW, FakeDB([R(1, ds=None), R(2, ds=None)]))
    assert res["cluster"]["data_source"] == "unverified"