/* KhetLoop frontend constants (owner: P3)
 * Mirror of shared/constants.py. Same names, same values.
 * SEVERITY_KEYWORDS_KN / _HI are backend-only (C2) and intentionally omitted.
 * Loaded after config.js and before api.js.
 */

const REPORT_STATUSES = ["submitted", "ai_assessed", "expert_review_pending", "expert_reviewed", "follow_up"];
const AI_DECISIONS = ["preliminary_assessment", "abstain_request_better_image", "escalate_to_expert"];
const CONFIDENCE_BANDS = ["high", "medium", "low"]; // model self-reported, NOT calibrated
const IMAGE_QUALITIES = ["good", "poor"];
const LANGUAGES = ["kn", "hi", "en"];
const CROPS = ["tomato", "potato", "chilli", "other"];
const ISSUES = ["early_blight", "late_blight", "septoria_leaf_spot", "bacterial_spot",
                "leaf_curl", "healthy", "unknown"];
const HIGH_RISK_ISSUES = ["late_blight"];
const SEVERITY_KEYWORDS = ["spreading", "whole field", "many plants", "dying", "all plants"];
const DATA_SOURCES = ["live", "cached", "simulated", "unverified"];
const CLUSTER_SEVERITIES = ["watch", "elevated"];
const CLUSTER_LABEL = "potential_cluster";
const EVENT_ACTORS = ["farmer", "ai", "rules", "expert", "system"];
const WHY_CODES = ["IMAGE_SYMPTOMS", "IMAGE_QUALITY", "LOW_CONFIDENCE", "NEARBY_REPORTS",
                   "WEATHER_CONTEXT", "FARM_HISTORY", "NOT_CONFIRMED"];
const RISK_LEVELS = ["normal", "elevated"];
const ERROR_CODES = ["INVALID_REQUEST", "UNAUTHORIZED", "NOT_FOUND", "CONFLICT", "AI_UNAVAILABLE",
                     "STT_FAILED", "WEATHER_UNAVAILABLE", "DB_ERROR", "INTERNAL_ERROR"];
const RADAR_RADIUS_KM = 10;
const RADAR_TIME_WINDOW_HOURS = 72;
const RADAR_MIN_REPORTS = 3;
const ABSTAIN_RETRY_WINDOW_MIN = 30;
const FOLLOW_UP_HOURS = 48;
const COORD_DECIMALS = 2;
const ALERT_TEMPLATE = "Crop health notice: several recent reports of similar {crop} leaf symptoms " +
  "were recorded near {area_label}. This is not a confirmed diagnosis. " +
  "Please inspect your plants and send a photo if you notice similar symptoms.";

/* ---------- UI-only display labels (NOT part of the contract) ---------- */

const STATUS_LABELS = {
  submitted: "Submitted",
  ai_assessed: "AI Assessed",
  expert_review_pending: "Expert Review Pending",
  expert_reviewed: "Expert Reviewed",
  follow_up: "Follow-up"
};

const DECISION_LABELS = {
  preliminary_assessment: "Preliminary assessment",
  abstain_request_better_image: "Clearer photo requested",
  escalate_to_expert: "Escalated to expert"
};

const CONFIDENCE_LABELS = { high: "High confidence", medium: "Medium confidence", low: "Low confidence" };

const ISSUE_LABELS = {
  early_blight: "Early blight",
  late_blight: "Late blight",
  septoria_leaf_spot: "Septoria leaf spot",
  bacterial_spot: "Bacterial spot",
  leaf_curl: "Leaf curl",
  healthy: "Healthy",
  unknown: "Unknown"
};

const DATA_SOURCE_LABELS = { live: "Live", cached: "Cached", simulated: "Simulated", unverified: "Unverified" };

const LANGUAGE_LABELS = { kn: "Kannada", hi: "Hindi", en: "English" };

const CROP_LABELS = { tomato: "Tomato", potato: "Potato", chilli: "Chilli", other: "Other" };