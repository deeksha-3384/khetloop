"""
Weather and neighbourhood risk indicator.
Imported by: backend/services/report_pipeline.py

compute_risk(assessment, weather, nearby_count) -> {"level": "normal"|"elevated", "reasons": [str]}
weather may be None (no coordinates or weather service down). assessment may be None (AI failed).
"""
from shared.constants import HIGH_RISK_ISSUES

HUMIDITY_ELEVATED_PCT = 80
NEARBY_ELEVATED_MIN = 1
NO_RISK_ISSUES = ("healthy", "unknown")


def compute_risk(assessment, weather, nearby_count: int) -> dict:
    reasons = []
    issue = (assessment or {}).get("suspected_issue", "unknown")

    # Risk is only about suspected diseases, never about healthy or unclear photos.
    if issue not in NO_RISK_ISSUES:
        if nearby_count >= NEARBY_ELEVATED_MIN:
            reasons.append("Similar reports nearby")
        if weather and weather.get("rain_expected"):
            reasons.append("Rain forecast")
        humidity = (weather or {}).get("humidity_pct_avg")
        if isinstance(humidity, (int, float)) and humidity >= HUMIDITY_ELEVATED_PCT:
            reasons.append("High humidity")
        if issue in HIGH_RISK_ISSUES:
            reasons.append("Higher-risk issue type")

    return {"level": "elevated" if reasons else "normal", "reasons": reasons}