"""
Dev helper (P1). Writes the mock JSON files into shared/mocks/.
Run from the project root:   python -m shared.make_mocks
Every file uses the same envelope as the real API so the frontend can switch
from mock to live by changing config only (USE_MOCK).
"""
import json
from pathlib import Path

MOCK_DIR = Path(__file__).resolve().parent / "mocks"
IMG = "https://signed-url.example/"

KN_TRANSCRIPT = "ನನ್ನ ಟೊಮೇಟೊ ಗಿಡದ ಎಲೆಗಳಲ್ಲಿ ಕಲೆಗಳು ಕಾಣಿಸುತ್ತಿವೆ"
KN_REPLY_ESCALATED = "ಇದು ಪ್ರಾಥಮಿಕ ಮೌಲ್ಯಮಾಪನ ಮಾತ್ರ. ತಜ್ಞರು ಪರಿಶೀಲಿಸುತ್ತಾರೆ."
KN_REPLY_PRELIM = "ಇದು ಪ್ರಾಥಮಿಕ ಮೌಲ್ಯಮಾಪನ ಮಾತ್ರ, ದೃಢೀಕೃತ ರೋಗನಿರ್ಣಯವಲ್ಲ. ಬಾಧಿತ ಎಲೆಗಳನ್ನು ತೆಗೆದುಹಾಕಿ ಮತ್ತು ಎಲೆಗಳನ್ನು ಒಣಗಿಸಿಡಿ."
KN_REPLY_ABSTAIN = "ಫೋಟೋ ಸ್ಪಷ್ಟವಾಗಿಲ್ಲ. ದಯವಿಟ್ಟು ಎಲೆಯ ಹತ್ತಿರದ, ಬೆಳಕಿನಲ್ಲಿ ತೆಗೆದ ಇನ್ನೊಂದು ಫೋಟೋ ಕಳುಹಿಸಿ."


def ok(data):
    return {"ok": True, "data": data}


WEATHER_RAIN = {
    "fetched_at": "2026-11-12T09:14:00Z", "rain_expected": True, "rain_mm_next_48h": 12.4,
    "humidity_pct_avg": 82, "temp_c_avg": 24.5, "data_source": "live",
}
WEATHER_DRY = {
    "fetched_at": "2026-11-12T10:40:00Z", "rain_expected": False, "rain_mm_next_48h": 0.0,
    "humidity_pct_avg": 55, "temp_c_avg": 28.0, "data_source": "live",
}
NOT_CONFIRMED = {"code": "NOT_CONFIRMED",
                 "text": "This is a preliminary assessment, not a confirmed diagnosis."}


def build_report(rep_id, status, assessment, why, weather, risk, reply, events,
                 transcript, language, expert_review=None):
    return {
        "id": rep_id,
        "farm_id": "farm_4a5b6c7d",
        "crop": "tomato",
        "created_at": events[0]["timestamp"],
        "status": status,
        "data_source": "live",
        "image_url": IMG + rep_id + ".jpg",
        "voice_transcript": transcript,
        "voice_language": language,
        "assessment": assessment,
        "why": why,
        "weather": weather,
        "risk": risk,
        "farmer_reply": {"language": "kn", "text": reply, "audio_url": None},
        "events": events,
        "expert_review": expert_review,
    }


# ---- 1. clear photo -> preliminary_assessment ------------------------------------------------
report_preliminary = build_report(
    "rep_b2c3d4e5", "ai_assessed",
    {"decision": "preliminary_assessment", "suspected_issue": "early_blight", "confidence_band": "high",
     "image_quality": "good", "visible_symptoms": ["brown concentric spots", "yellowing around spots"],
     "confirmed": False},
    [{"code": "IMAGE_SYMPTOMS", "text": "The photo shows visible symptoms resembling early blight."},
     {"code": "WEATHER_CONTEXT", "text": "No rain is forecast in the next 48 hours (live forecast)."},
     NOT_CONFIRMED],
    WEATHER_DRY, {"level": "normal", "reasons": []}, KN_REPLY_PRELIM,
    [{"status": "submitted", "actor": "farmer", "timestamp": "2026-11-12T10:41:00Z"},
     {"status": "ai_assessed", "actor": "ai", "timestamp": "2026-11-12T10:41:06Z"}],
    KN_TRANSCRIPT, "kn")

# ---- 2. blurry first try -> abstain -----------------------------------------------------------
report_abstain = build_report(
    "rep_c3d4e5f6", "ai_assessed",
    {"decision": "abstain_request_better_image", "suspected_issue": "unknown", "confidence_band": "low",
     "image_quality": "poor", "visible_symptoms": [], "confirmed": False},
    [{"code": "IMAGE_QUALITY", "text": "The photo is too blurry or dark to assess."},
     {"code": "LOW_CONFIDENCE", "text": "The assessment confidence is low, so no result is given."},
     NOT_CONFIRMED],
    None, None, KN_REPLY_ABSTAIN,
    [{"status": "submitted", "actor": "farmer", "timestamp": "2026-11-12T08:50:00Z"},
     {"status": "ai_assessed", "actor": "ai", "timestamp": "2026-11-12T08:50:05Z"}],
    KN_TRANSCRIPT, "kn")

# ---- 3. escalated to expert -------------------------------------------------------------------
ESC_EVENTS = [
    {"status": "submitted", "actor": "farmer", "timestamp": "2026-11-12T09:15:00Z"},
    {"status": "ai_assessed", "actor": "ai", "timestamp": "2026-11-12T09:15:06Z"},
    {"status": "expert_review_pending", "actor": "rules", "timestamp": "2026-11-12T09:15:07Z"},
]
ESC_WHY = [
    {"code": "IMAGE_SYMPTOMS", "text": "The photo shows visible symptoms resembling early blight."},
    {"code": "NEARBY_REPORTS", "text": "2 similar reports were submitted nearby in the last 72 hours."},
    {"code": "WEATHER_CONTEXT", "text": "Rain is forecast in the next 48 hours (live forecast)."},
    NOT_CONFIRMED,
]
ESC_RISK = {"level": "elevated", "reasons": ["Similar reports nearby", "Rain forecast"]}

report_escalated = build_report(
    "rep_a1b2c3d4", "expert_review_pending",
    {"decision": "escalate_to_expert", "suspected_issue": "early_blight", "confidence_band": "medium",
     "image_quality": "good", "visible_symptoms": ["brown concentric spots"], "confirmed": False},
    ESC_WHY, WEATHER_RAIN, ESC_RISK, KN_REPLY_ESCALATED, ESC_EVENTS, KN_TRANSCRIPT, "kn")

# ---- 4. expert reviewed -----------------------------------------------------------------------
EXPERT_REVIEW = {
    "id": "rev_5e6f7a8b", "report_id": "rep_a1b2c3d4", "expert_name": "Demo Expert",
    "guidance": "Remove affected leaves and keep foliage dry. Please share a photo in 2 days.",
    "confirmed_issue": "early_blight", "created_at": "2026-11-12T11:02:00Z",
}
report_expert_reviewed = build_report(
    "rep_a1b2c3d4", "expert_reviewed",
    {"decision": "escalate_to_expert", "suspected_issue": "early_blight", "confidence_band": "medium",
     "image_quality": "good", "visible_symptoms": ["brown concentric spots"], "confirmed": True},
    ESC_WHY, WEATHER_RAIN, ESC_RISK, KN_REPLY_ESCALATED,
    ESC_EVENTS + [{"status": "expert_reviewed", "actor": "expert", "timestamp": "2026-11-12T11:02:00Z"}],
    KN_TRANSCRIPT, "kn", expert_review=EXPERT_REVIEW)

# ---- 5. farms ---------------------------------------------------------------------------------
farms = {"farms": [
    {"id": "farm_4a5b6c7d", "crop": "tomato", "area_label": "Kolar North", "farmer_name": "Ramesh",
     "language": "kn", "report_count": 3, "data_source": "live"},
    {"id": "farm_8e9f0a1b", "crop": "tomato", "area_label": "Kolar South", "farmer_name": "Sunita",
     "language": "hi", "report_count": 1, "data_source": "simulated"},
    {"id": "farm_2c3d4e5f", "crop": "chilli", "area_label": "Chikkaballapur", "farmer_name": "Lakshmi",
     "language": "en", "report_count": 0, "data_source": "simulated"},
]}

# ---- 6. farm timeline -------------------------------------------------------------------------
farm_timeline = {
    "farm": {"id": "farm_4a5b6c7d", "crop": "tomato", "area_label": "Kolar North", "sowing_date": "2026-10-05"},
    "items": [
        {"report_id": "rep_a1b2c3d4", "created_at": "2026-11-12T09:15:00Z", "status": "expert_reviewed",
         "decision": "escalate_to_expert", "suspected_issue": "early_blight", "confidence_band": "medium",
         "image_url": IMG + "rep_a1b2c3d4.jpg",
         "expert_guidance": "Remove affected leaves and keep foliage dry. Please share a photo in 2 days."},
        {"report_id": "rep_b2c3d4e5", "created_at": "2026-11-10T10:41:00Z", "status": "ai_assessed",
         "decision": "preliminary_assessment", "suspected_issue": "early_blight", "confidence_band": "high",
         "image_url": IMG + "rep_b2c3d4e5.jpg", "expert_guidance": None},
        {"report_id": "rep_c3d4e5f6", "created_at": "2026-11-09T08:50:00Z", "status": "ai_assessed",
         "decision": "abstain_request_better_image", "suspected_issue": "unknown", "confidence_band": "low",
         "image_url": IMG + "rep_c3d4e5f6.jpg", "expert_guidance": None},
    ],
}

# ---- 7. expert cases --------------------------------------------------------------------------
expert_cases = {"count": 3, "cases": [
    {"report_id": "rep_a1b2c3d4", "created_at": "2026-11-12T09:15:00Z", "farm_id": "farm_4a5b6c7d",
     "crop": "tomato", "area_label": "Kolar North", "suspected_issue": "early_blight",
     "confidence_band": "medium", "decision": "escalate_to_expert", "escalation_reason": "SEVERITY_KEYWORD",
     "image_url": IMG + "rep_a1b2c3d4.jpg", "rain_expected": True, "data_source": "live"},
    {"report_id": "rep_d4e5f6a7", "created_at": "2026-11-12T09:40:00Z", "farm_id": "farm_8e9f0a1b",
     "crop": "tomato", "area_label": "Kolar South", "suspected_issue": "late_blight",
     "confidence_band": "medium", "decision": "escalate_to_expert",
     "escalation_reason": "MEDIUM_CONFIDENCE_HIGH_RISK",
     "image_url": IMG + "rep_d4e5f6a7.jpg", "rain_expected": True, "data_source": "simulated"},
    {"report_id": "rep_e5f6a7b8", "created_at": "2026-11-12T10:05:00Z", "farm_id": "farm_2c3d4e5f",
     "crop": "chilli", "area_label": "Chikkaballapur", "suspected_issue": "unknown",
     "confidence_band": "low", "decision": "escalate_to_expert", "escalation_reason": "UNCLEAR_AFTER_RETRY",
     "image_url": IMG + "rep_e5f6a7b8.jpg", "rain_expected": False, "data_source": "simulated"},
]}

# ---- 8. radar clusters (public form, no farm or report ids) -----------------------------------
CLUSTER_1 = {
    "id": "clu_1a2b3c4d", "crop": "tomato", "suspected_issue": "early_blight", "area_label": "Kolar North",
    "centroid_lat": 13.14, "centroid_lng": 78.13, "severity": "watch", "report_count": 3,
    "window_hours": 72, "label": "potential_cluster", "data_source": "simulated",
    "created_at": "2026-11-12T09:20:00Z",
}
CLUSTER_2 = {
    "id": "clu_5f6a7b8c", "crop": "tomato", "suspected_issue": "late_blight", "area_label": "Kolar South",
    "centroid_lat": 13.1, "centroid_lng": 78.16, "severity": "elevated", "report_count": 5,
    "window_hours": 72, "label": "potential_cluster", "data_source": "simulated",
    "created_at": "2026-11-12T09:25:00Z",
}
radar_clusters = {"generated_at": "2026-11-12T09:30:00Z", "has_simulated": True,
                  "clusters": [CLUSTER_1, CLUSTER_2]}

# ---- 9. cluster detail (key required) ---------------------------------------------------------
cluster_detail = {
    "cluster": CLUSTER_1,
    "reports": [
        {"report_id": "rep_a1b2c3d4", "created_at": "2026-11-12T09:15:00Z", "crop": "tomato",
         "suspected_issue": "early_blight", "confidence_band": "medium", "area_label": "Kolar North",
         "image_url": IMG + "rep_a1b2c3d4.jpg"},
        {"report_id": "rep_f6a7b8c9", "created_at": "2026-11-12T08:55:00Z", "crop": "tomato",
         "suspected_issue": "early_blight", "confidence_band": "high", "area_label": "Kolar North",
         "image_url": IMG + "rep_f6a7b8c9.jpg"},
        {"report_id": "rep_a7b8c9d0", "created_at": "2026-11-11T17:30:00Z", "crop": "tomato",
         "suspected_issue": "early_blight", "confidence_band": "medium", "area_label": "Kolar North",
         "image_url": IMG + "rep_a7b8c9d0.jpg"},
    ],
    "alerts": [
        {"id": "alt_7d8e9f0a", "cluster_id": "clu_1a2b3c4d", "farm_id": "farm_4a5b6c7d",
         "message": ("Crop health notice: several recent reports of similar tomato leaf symptoms were "
                     "recorded near Kolar North. This is not a confirmed diagnosis. Please inspect your "
                     "plants and send a photo if you notice similar symptoms."),
         "channel": "telegram", "delivered": True, "sent_at": "2026-11-12T09:21:00Z",
         "data_source": "simulated"},
    ],
}

error_example = {"ok": False, "error": {"code": "NOT_FOUND", "message": "Report not found"}}

FILES = {
    "farms.json": ok(farms),
    "report_preliminary.json": ok(report_preliminary),
    "report_abstain.json": ok(report_abstain),
    "report_escalated.json": ok(report_escalated),
    "report_expert_reviewed.json": ok(report_expert_reviewed),
    "farm_timeline.json": ok(farm_timeline),
    "expert_cases.json": ok(expert_cases),
    "radar_clusters.json": ok(radar_clusters),
    "cluster_detail.json": ok(cluster_detail),
    "error_example.json": error_example,
}


def main():
    MOCK_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in FILES.items():
        (MOCK_DIR / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Self-check: every file reloads, has the envelope, and never contains the forbidden word.
    for name in FILES:
        text = (MOCK_DIR / name).read_text(encoding="utf-8")
        parsed = json.loads(text)
        assert "ok" in parsed, name + " is missing the ok key"
        assert "outbreak" not in text.lower(), name + " contains the forbidden word"
        print("ok  ", name)
    print("Wrote %d mock files to %s" % (len(FILES), MOCK_DIR))


if __name__ == "__main__":
    main()