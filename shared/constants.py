"""
Shared constants for KhetLoop.
Owner: P1. Changes need approval from all 4 team members (contract PR).
Frontend mirrors this file in frontend/js/constants.js (same names and values).
"""

REPORT_STATUSES = ["submitted", "ai_assessed", "expert_review_pending", "expert_reviewed", "follow_up"]
AI_DECISIONS = ["preliminary_assessment", "abstain_request_better_image", "escalate_to_expert"]
CONFIDENCE_BANDS = ["high", "medium", "low"]  # model self-reported, NOT calibrated
IMAGE_QUALITIES = ["good", "poor"]
LANGUAGES = ["kn", "hi", "en"]
CROPS = ["tomato", "potato", "chilli", "other"]
ISSUES = [
    "early_blight", "late_blight", "septoria_leaf_spot", "bacterial_spot",
    "leaf_curl", "healthy", "unknown",
]
HIGH_RISK_ISSUES = ["late_blight"]
SEVERITY_KEYWORDS = ["spreading", "whole field", "many plants", "dying", "all plants"]
DATA_SOURCES = ["live", "cached", "simulated", "unverified"]
CLUSTER_SEVERITIES = ["watch", "elevated"]
CLUSTER_LABEL = "potential_cluster"
EVENT_ACTORS = ["farmer", "ai", "rules", "expert", "system"]
WHY_CODES = [
    "IMAGE_SYMPTOMS", "IMAGE_QUALITY", "LOW_CONFIDENCE", "NEARBY_REPORTS",
    "WEATHER_CONTEXT", "FARM_HISTORY", "NOT_CONFIRMED",
]
RISK_LEVELS = ["normal", "elevated"]
ERROR_CODES = [
    "INVALID_REQUEST", "UNAUTHORIZED", "NOT_FOUND", "CONFLICT", "AI_UNAVAILABLE",
    "STT_FAILED", "WEATHER_UNAVAILABLE", "DB_ERROR", "INTERNAL_ERROR",
]
RADAR_RADIUS_KM = 10
RADAR_TIME_WINDOW_HOURS = 72
RADAR_MIN_REPORTS = 3
ABSTAIN_RETRY_WINDOW_MIN = 30
FOLLOW_UP_HOURS = 48
COORD_DECIMALS = 2

# NOTE (open issue, needs a contract PR before Phase 4):
# This template is copied EXACTLY from the plan, but it contains the word
# "outbreak", which the plan itself forbids in any output. Proposed fix:
# "...This is not a confirmed diagnosis. Please inspect..."
ALERT_TEMPLATE = (
    "Crop health notice: several recent reports of similar {crop} leaf symptoms "
    "were recorded near {area_label}. This is not a confirmed outbreak. "
    "Please inspect your plants and send a photo if you notice similar symptoms."
)