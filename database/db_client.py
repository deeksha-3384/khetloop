"""
KhetLoop database client (owner: P2, folder database/).

Backend usage:
    from database import db_client
    farmer = db_client.get_or_create_farmer(100200300, "Ramesh", "kn")

DB_MODE (env):
    memory   -> data lives in Python lists (no Supabase needed)
    supabase -> real Supabase Postgres + Storage (added on Day 2)

Every function raises DBError(code="DB_ERROR", message=...) on failure.
"""
from __future__ import annotations

import math
import os
import uuid
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

# ---- Constants copied from shared/constants.py (Master Contract v2.0, section 4.1) ----
REPORT_STATUSES = ["submitted", "ai_assessed", "expert_review_pending", "expert_reviewed", "follow_up"]
AI_DECISIONS = ["preliminary_assessment", "abstain_request_better_image", "escalate_to_expert"]
CONFIDENCE_BANDS = ["high", "medium", "low"]
IMAGE_QUALITIES = ["good", "poor"]
LANGUAGES = ["kn", "hi", "en"]
CROPS = ["tomato", "potato", "chilli", "other"]
ISSUES = ["early_blight", "late_blight", "septoria_leaf_spot", "bacterial_spot",
          "leaf_curl", "healthy", "unknown"]
DATA_SOURCES = ["live", "cached", "simulated", "unverified"]
CLUSTER_SEVERITIES = ["watch", "elevated"]
CLUSTER_LABEL = "potential_cluster"
EVENT_ACTORS = ["farmer", "ai", "rules", "expert", "system"]
COORD_DECIMALS = 2

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


class DBError(Exception):
    """The only exception db_client raises. The backend maps it to 500 DB_ERROR."""

    def __init__(self, code: str = "DB_ERROR", message: str = "Database error"):
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _is_memory() -> bool:
    mode = os.getenv("DB_MODE", "memory").strip().lower()
    if mode == "memory":
        return True
    if mode == "supabase":
        return False
    raise DBError("DB_ERROR", f"DB_MODE must be 'memory' or 'supabase', got '{mode}'")


def _supabase_todo(name: str):
    raise DBError("DB_ERROR", f"{name}: Supabase mode is not built yet. Use DB_MODE=memory for now.")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value) -> datetime:
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        raise DBError("DB_ERROR", f"invalid timestamp: {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:8]


def _require_text(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DBError("DB_ERROR", f"{name} is required")
    return value.strip()


def _require_in(value, allowed: list, name: str):
    if value not in allowed:
        raise DBError("DB_ERROR", f"invalid {name}: {value!r} (allowed: {', '.join(allowed)})")
    return value


def _round_coord(value, name: str, limit: float):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise DBError("DB_ERROR", f"{name} must be a number, got {value!r}")
    if not -limit <= number <= limit:
        raise DBError("DB_ERROR", f"{name} out of range: {number}")
    return round(number, COORD_DECIMALS)


def _check_date(value):
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise DBError("DB_ERROR", f"invalid date (use YYYY-MM-DD): {value!r}")


# ---------------------------------------------------------------------------
# In-memory store (used when DB_MODE=memory)
# ---------------------------------------------------------------------------
_MEM: dict = {}


def _reset_memory() -> None:
    """Wipe all in-memory data (handy for tests)."""
    global _MEM
    _MEM = {
        "farmers": [], "farms": [], "reports": [], "events": [], "reviews": [],
        "clusters": [], "cluster_reports": [], "alerts": [], "reminders": [],
        "images": {},
    }


_reset_memory()


def _mem_find(table: str, row_id: str):
    for row in _MEM[table]:
        if row["id"] == row_id:
            return row
    return None


def _farmer_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "language": row["language"],
        "telegram_chat_id": row["telegram_chat_id"],
    }


def _farm_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "farmer_id": row["farmer_id"],
        "crop": row["crop"],
        "sowing_date": row["sowing_date"],
        "area_label": row["area_label"],
        "lat": row["lat"],
        "lng": row["lng"],
        "data_source": row["data_source"],
    }


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def upload_image(image_bytes: bytes, farm_id: str, content_type: str = "image/jpeg") -> str:
    """Store an image. Returns the storage path '<farm_id>/<random>.jpg' (contract C8)."""
    if not isinstance(image_bytes, (bytes, bytearray)) or len(image_bytes) == 0:
        raise DBError("DB_ERROR", "image_bytes must be non-empty bytes")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise DBError("DB_ERROR", "image is larger than 10 MB")
    farm_id = _require_text(farm_id, "farm_id")
    if "/" in farm_id or "\\" in farm_id:
        raise DBError("DB_ERROR", "farm_id must not contain slashes")
    if not isinstance(content_type, str) or not content_type.startswith("image/"):
        raise DBError("DB_ERROR", f"content_type must be an image type, got {content_type!r}")
    path = f"{farm_id}/{uuid.uuid4().hex[:12]}.jpg"
    if _is_memory():
        _MEM["images"][path] = bytes(image_bytes)
        return path
    return _sb_call("upload_image", locals())


def signed_image_url(path: str, expires_s: int = 3600) -> str:
    """Return a temporary URL for a stored image (default 1 hour)."""
    path = _require_text(path, "path")
    if not isinstance(expires_s, int) or expires_s <= 0:
        raise DBError("DB_ERROR", "expires_s must be a positive integer")
    if _is_memory():
        return f"https://signed-url.example/{path}"
    return _sb_call("signed_image_url", locals())


# ---------------------------------------------------------------------------
# Farmers and farms
# ---------------------------------------------------------------------------
def get_or_create_farmer(telegram_chat_id: int | None, name: str, language: str) -> dict:
    """Existing chat id -> update name and language, return it. None chat id -> always a new farmer."""
    name = _require_text(name, "name")
    _require_in(language, LANGUAGES, "language")
    if telegram_chat_id is not None and (
        isinstance(telegram_chat_id, bool) or not isinstance(telegram_chat_id, int)
    ):
        raise DBError("DB_ERROR", "telegram_chat_id must be an integer or None")
    if _is_memory():
        if telegram_chat_id is not None:
            for row in _MEM["farmers"]:
                if row["telegram_chat_id"] == telegram_chat_id:
                    row["name"] = name
                    row["language"] = language
                    return _farmer_out(row)
        row = {
            "id": _new_id("fmr_"),
            "name": name,
            "language": language,
            "telegram_chat_id": telegram_chat_id,
            "created_at": _now_iso(),
        }
        _MEM["farmers"].append(row)
        return _farmer_out(row)
    return _sb_call("get_or_create_farmer", locals())


def get_farmer_for_farm(farm_id: str) -> dict | None:
    """Farmer model (id, name, language, telegram_chat_id) that owns this farm, or None."""
    farm_id = _require_text(farm_id, "farm_id")
    if _is_memory():
        farm = _mem_find("farms", farm_id)
        if farm is None:
            return None
        farmer = _mem_find("farmers", farm["farmer_id"])
        return _farmer_out(farmer) if farmer else None
    return _sb_call("get_farmer_for_farm", locals())


def get_or_create_farm(farmer_id: str, crop: str, sowing_date: str | None = None,
                       area_label: str | None = None, lat: float | None = None,
                       lng: float | None = None) -> dict:
    """Same (farmer_id, crop) -> return the existing farm and update any non-null values.
    lat/lng are rounded to 2 decimals before storage."""
    farmer_id = _require_text(farmer_id, "farmer_id")
    _require_in(crop, CROPS, "crop")
    sowing_date = _check_date(sowing_date)
    lat = _round_coord(lat, "lat", 90)
    lng = _round_coord(lng, "lng", 180)
    if _is_memory():
        if _mem_find("farmers", farmer_id) is None:
            raise DBError("DB_ERROR", f"farmer not found: {farmer_id}")
        for row in _MEM["farms"]:
            if row["farmer_id"] == farmer_id and row["crop"] == crop:
                if sowing_date is not None:
                    row["sowing_date"] = sowing_date
                if area_label is not None:
                    row["area_label"] = area_label
                if lat is not None:
                    row["lat"] = lat
                if lng is not None:
                    row["lng"] = lng
                return _farm_out(row)
        row = {
            "id": _new_id("farm_"),
            "farmer_id": farmer_id,
            "crop": crop,
            "sowing_date": sowing_date,
            "area_label": area_label,
            "lat": lat,
            "lng": lng,
            "data_source": "live",
            "created_at": _now_iso(),
        }
        _MEM["farms"].append(row)
        return _farm_out(row)
    return _sb_call("get_or_create_farm", locals())


def get_farm(farm_id: str) -> dict | None:
    """Farm model, or None if it does not exist."""
    farm_id = _require_text(farm_id, "farm_id")
    if _is_memory():
        row = _mem_find("farms", farm_id)
        return _farm_out(row) if row else None
    return _sb_call("get_farm", locals())


def list_farms() -> list[dict]:
    """Items as in API endpoint 3: id, crop, area_label, farmer_name, language, report_count, data_source."""
    if _is_memory():
        out = []
        for farm in _MEM["farms"]:
            farmer = _mem_find("farmers", farm["farmer_id"])
            out.append({
                "id": farm["id"],
                "crop": farm["crop"],
                "area_label": farm["area_label"],
                "farmer_name": farmer["name"] if farmer else None,
                "language": farmer["language"] if farmer else None,
                "report_count": sum(1 for r in _MEM["reports"] if r["farm_id"] == farm["id"]),
                "data_source": farm["data_source"],
            })
        return out
    return _sb_call("list_farms", locals())

# ---------------------------------------------------------------------------
# Reports, events, expert reviews
# ---------------------------------------------------------------------------
from copy import deepcopy


def _mem_review_for(report_id: str):
    for row in _MEM["reviews"]:
        if row["report_id"] == report_id:
            return row
    return None


def _review_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "report_id": row["report_id"],
        "expert_name": row["expert_name"],
        "guidance": row["guidance"],
        "confirmed_issue": row["confirmed_issue"],
        "created_at": row["created_at"],
    }


def _event_out(row: dict) -> dict:
    out = {"status": row["status"], "actor": row["actor"], "timestamp": row["created_at"]}
    if row["note"] is not None:
        out["note"] = row["note"]
    return out


def _mem_report_model(row: dict) -> dict:
    """Build the full Report model (Master Contract section 5)."""
    farm = _mem_find("farms", row["farm_id"])
    review = _mem_review_for(row["id"])
    return {
        "id": row["id"],
        "farm_id": row["farm_id"],
        "crop": farm["crop"] if farm else None,
        "created_at": row["created_at"],
        "status": row["status"],
        "data_source": row["data_source"],
        "image_url": signed_image_url(row["image_path"]),
        "voice_transcript": row["voice_transcript"],
        "voice_language": row["voice_language"],
        "assessment": {
            "decision": row["decision"],
            "suspected_issue": row["suspected_issue"],
            "confidence_band": row["confidence_band"],
            "image_quality": row["image_quality"],
            "visible_symptoms": deepcopy(row["visible_symptoms"]),
            "confirmed": bool(review is not None and review["confirmed_issue"] is not None),
        },
        "why": deepcopy(row["why"]),
        "weather": deepcopy(row["weather"]),
        "risk": deepcopy(row["risk"]),
        "farmer_reply": {
            "language": row["reply_language"],
            "text": row["reply_text"],
            "audio_url": None,
        },
        "events": [_event_out(e) for e in _MEM["events"] if e["report_id"] == row["id"]],
        "expert_review": _review_out(review) if review else None,
    }


def _mem_timeline_item(row: dict) -> dict:
    review = _mem_review_for(row["id"])
    return {
        "report_id": row["id"],
        "created_at": row["created_at"],
        "status": row["status"],
        "decision": row["decision"],
        "suspected_issue": row["suspected_issue"],
        "confidence_band": row["confidence_band"],
        "image_url": signed_image_url(row["image_path"]),
        "expert_guidance": review["guidance"] if review else None,
    }


def insert_report(farm_id: str, image_path: str, voice_transcript: str | None,
                  voice_language: str | None, assessment: dict, escalation_reason: str | None,
                  why: list, weather: dict | None, risk: dict | None,
                  reply_language: str | None, reply_text: str | None,
                  status: str, data_source: str = "live") -> dict:
    """Save a report. Returns the full Report model (events is empty until add_report_event)."""
    farm_id = _require_text(farm_id, "farm_id")
    image_path = _require_text(image_path, "image_path")
    if voice_language is not None:
        _require_in(voice_language, LANGUAGES, "voice_language")
    if not isinstance(assessment, dict):
        raise DBError("DB_ERROR", "assessment must be a dict")
    decision = _require_in(assessment.get("decision"), AI_DECISIONS, "assessment.decision")
    issue = assessment.get("suspected_issue") or "unknown"
    if not isinstance(issue, str):
        raise DBError("DB_ERROR", "assessment.suspected_issue must be text")
    band = _require_in(assessment.get("confidence_band"), CONFIDENCE_BANDS, "assessment.confidence_band")
    quality = _require_in(assessment.get("image_quality"), IMAGE_QUALITIES, "assessment.image_quality")
    symptoms = assessment.get("visible_symptoms") or []
    if not isinstance(symptoms, list):
        raise DBError("DB_ERROR", "assessment.visible_symptoms must be a list")
    if not isinstance(why, list):
        raise DBError("DB_ERROR", "why must be a list")
    if weather is not None and not isinstance(weather, dict):
        raise DBError("DB_ERROR", "weather must be a dict or None")
    if risk is not None and not isinstance(risk, dict):
        raise DBError("DB_ERROR", "risk must be a dict or None")
    _require_in(status, REPORT_STATUSES, "status")
    _require_in(data_source, DATA_SOURCES, "data_source")
    if _is_memory():
        if _mem_find("farms", farm_id) is None:
            raise DBError("DB_ERROR", f"farm not found: {farm_id}")
        row = {
            "id": _new_id("rep_"),
            "farm_id": farm_id,
            "image_path": image_path,
            "voice_transcript": voice_transcript,
            "voice_language": voice_language,
            "decision": decision,
            "suspected_issue": issue,
            "confidence_band": band,
            "image_quality": quality,
            "visible_symptoms": deepcopy(symptoms),
            "escalation_reason": escalation_reason,
            "why": deepcopy(why),
            "weather": deepcopy(weather),
            "risk": deepcopy(risk),
            "reply_language": reply_language,
            "reply_text": reply_text,
            "reply_audio_path": None,
            "status": status,
            "data_source": data_source,
            "created_at": _now_iso(),
        }
        _MEM["reports"].append(row)
        return _mem_report_model(row)
    return _sb_call("insert_report", locals())


def add_report_event(report_id: str, status: str, actor: str, note: str | None = None) -> dict:
    """Add one timeline entry. Returns {status, actor, timestamp[, note]}."""
    report_id = _require_text(report_id, "report_id")
    _require_in(status, REPORT_STATUSES, "status")
    _require_in(actor, EVENT_ACTORS, "actor")
    if _is_memory():
        if _mem_find("reports", report_id) is None:
            raise DBError("DB_ERROR", f"report not found: {report_id}")
        row = {
            "report_id": report_id,
            "status": status,
            "actor": actor,
            "note": note,
            "created_at": _now_iso(),
        }
        _MEM["events"].append(row)
        return _event_out(row)
    return _sb_call("add_report_event", locals())


def update_report_status(report_id: str, status: str) -> None:
    """Set the report's current status (does not add an event)."""
    report_id = _require_text(report_id, "report_id")
    _require_in(status, REPORT_STATUSES, "status")
    if _is_memory():
        row = _mem_find("reports", report_id)
        if row is None:
            raise DBError("DB_ERROR", f"report not found: {report_id}")
        row["status"] = status
        return None
    return _sb_call("update_report_status", locals())


def get_report(report_id: str) -> dict | None:
    """The full Report model (assessment, weather, risk, why, reply, events, review, signed image URL)."""
    report_id = _require_text(report_id, "report_id")
    if _is_memory():
        row = _mem_find("reports", report_id)
        return _mem_report_model(row) if row else None
    return _sb_call("get_report", locals())


def list_farm_reports(farm_id: str) -> list[dict]:
    """Timeline items for one farm (API endpoint 4), newest first. Unknown farm -> []."""
    farm_id = _require_text(farm_id, "farm_id")
    if _is_memory():
        rows = [r for r in _MEM["reports"] if r["farm_id"] == farm_id]
        return [_mem_timeline_item(r) for r in reversed(rows)]
    return _sb_call("list_farm_reports", locals())


def count_recent_abstains(farm_id: str, minutes: int) -> int:
    """CONSECUTIVE abstain reports within the window, counting back from the newest (contract C16)."""
    farm_id = _require_text(farm_id, "farm_id")
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or minutes < 0:
        raise DBError("DB_ERROR", "minutes must be a non-negative number")
    if _is_memory():
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        count = 0
        for row in reversed(_MEM["reports"]):
            if row["farm_id"] != farm_id:
                continue
            if _parse_ts(row["created_at"]) < cutoff:
                break
            if row["decision"] != "abstain_request_better_image":
                break
            count += 1
        return count
    return _sb_call("count_recent_abstains", locals())


def list_expert_cases(status: str = "expert_review_pending") -> list[dict]:
    """Expert queue (API endpoint 5), oldest first."""
    _require_in(status, REPORT_STATUSES, "status")
    if _is_memory():
        out = []
        for row in _MEM["reports"]:
            if row["status"] != status:
                continue
            farm = _mem_find("farms", row["farm_id"])
            out.append({
                "report_id": row["id"],
                "created_at": row["created_at"],
                "farm_id": row["farm_id"],
                "crop": farm["crop"] if farm else None,
                "area_label": farm["area_label"] if farm else None,
                "suspected_issue": row["suspected_issue"],
                "confidence_band": row["confidence_band"],
                "decision": row["decision"],
                "escalation_reason": row["escalation_reason"],
                "image_url": signed_image_url(row["image_path"]),
                "rain_expected": bool((row["weather"] or {}).get("rain_expected", False)),
                "data_source": row["data_source"],
            })
        return out
    return _sb_call("list_expert_cases", locals())


def insert_expert_review(report_id: str, expert_name: str, guidance: str,
                         confirmed_issue: str | None) -> dict:
    """Save an expert review. One review per report: a second one raises DBError."""
    report_id = _require_text(report_id, "report_id")
    expert_name = _require_text(expert_name, "expert_name")
    guidance = _require_text(guidance, "guidance")
    if confirmed_issue is not None:
        _require_in(confirmed_issue, ISSUES, "confirmed_issue")
    if _is_memory():
        if _mem_find("reports", report_id) is None:
            raise DBError("DB_ERROR", f"report not found: {report_id}")
        if _mem_review_for(report_id) is not None:
            raise DBError("DB_ERROR", f"expert review already exists for report {report_id}")
        row = {
            "id": _new_id("rev_"),
            "report_id": report_id,
            "expert_name": expert_name,
            "guidance": guidance,
            "confirmed_issue": confirmed_issue,
            "created_at": _now_iso(),
        }
        _MEM["reviews"].append(row)
        return _review_out(row)
    return _sb_call("insert_expert_review", locals())


# ---------------------------------------------------------------------------
# Nearby search, clusters, alerts, reminders
# ---------------------------------------------------------------------------
def _number(value, name: str) -> float:
    if isinstance(value, bool):
        raise DBError("DB_ERROR", f"{name} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise DBError("DB_ERROR", f"{name} must be a number, got {value!r}")


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def _cluster_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "crop": row["crop"],
        "suspected_issue": row["suspected_issue"],
        "area_label": row["area_label"],
        "centroid_lat": row["centroid_lat"],
        "centroid_lng": row["centroid_lng"],
        "severity": row["severity"],
        "report_count": row["report_count"],
        "window_hours": row["window_hours"],
        "label": CLUSTER_LABEL,
        "data_source": row["data_source"],
        "created_at": row["created_at"],
    }


def _alert_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "cluster_id": row["cluster_id"],
        "farm_id": row["farm_id"],
        "message": row["message"],
        "channel": row["channel"],
        "delivered": row["delivered"],
        "sent_at": row["sent_at"],
        "data_source": row["data_source"],
    }


def _reminder_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "report_id": row["report_id"],
        "due_at": row["due_at"],
        "message": row["message"],
        "sent": row["sent"],
    }


def find_similar_recent_reports(crop: str, suspected_issue: str, since_hours: int,
                                lat: float, lng: float, radius_km: float) -> list[dict]:
    """Reports with the same crop and issue, confidence medium/high, inside the radius and
    time window. Includes the newest report if already stored. Newest first."""
    _require_in(crop, CROPS, "crop")
    suspected_issue = _require_text(suspected_issue, "suspected_issue")
    since_hours = _number(since_hours, "since_hours")
    lat = _number(lat, "lat")
    lng = _number(lng, "lng")
    radius_km = _number(radius_km, "radius_km")
    if since_hours < 0 or radius_km < 0:
        raise DBError("DB_ERROR", "since_hours and radius_km must not be negative")
    if _is_memory():
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        out = []
        for row in reversed(_MEM["reports"]):
            if row["suspected_issue"] != suspected_issue:
                continue
            if row["confidence_band"] not in ("medium", "high"):
                continue
            if _parse_ts(row["created_at"]) < cutoff:
                continue
            farm = _mem_find("farms", row["farm_id"])
            if farm is None or farm["crop"] != crop:
                continue
            if farm["lat"] is None or farm["lng"] is None:
                continue
            if _haversine_km(lat, lng, farm["lat"], farm["lng"]) > radius_km:
                continue
            out.append({
                "report_id": row["id"],
                "farm_id": row["farm_id"],
                "confidence_band": row["confidence_band"],
                "created_at": row["created_at"],
                "lat": farm["lat"],
                "lng": farm["lng"],
                "area_label": farm["area_label"],
                "suspected_issue": row["suspected_issue"],
                "data_source": row.get("data_source") or "live",
            })
        return out
    return _sb_call("find_similar_recent_reports", locals())


def find_nearby_farms(crop: str, lat: float, lng: float, radius_km: float,
                      exclude_farm_id: str | None = None) -> list[dict]:
    """Farms with the same crop inside the radius (contract C7). Farms without a Telegram chat are included."""
    _require_in(crop, CROPS, "crop")
    lat = _number(lat, "lat")
    lng = _number(lng, "lng")
    radius_km = _number(radius_km, "radius_km")
    if radius_km < 0:
        raise DBError("DB_ERROR", "radius_km must not be negative")
    if _is_memory():
        out = []
        for farm in _MEM["farms"]:
            if farm["crop"] != crop or farm["id"] == exclude_farm_id:
                continue
            if farm["lat"] is None or farm["lng"] is None:
                continue
            if _haversine_km(lat, lng, farm["lat"], farm["lng"]) > radius_km:
                continue
            farmer = _mem_find("farmers", farm["farmer_id"])
            out.append({
                "farm_id": farm["id"],
                "farmer_id": farm["farmer_id"],
                "telegram_chat_id": farmer["telegram_chat_id"] if farmer else None,
                "language": farmer["language"] if farmer else None,
                "area_label": farm["area_label"],
                "lat": farm["lat"],
                "lng": farm["lng"],
            })
        return out
    return _sb_call("find_nearby_farms", locals())


def create_cluster(crop: str, suspected_issue: str, area_label: str, centroid_lat: float,
                   centroid_lng: float, severity: str, report_ids: list[str],
                   window_hours: int, data_source: str = "live") -> dict:
    """Create a potential_cluster and link its reports. Returns the public Cluster model."""
    _require_in(crop, CROPS, "crop")
    suspected_issue = _require_text(suspected_issue, "suspected_issue")
    if area_label is not None and not isinstance(area_label, str):
        raise DBError("DB_ERROR", "area_label must be text")
    if centroid_lat is None or centroid_lng is None:
        raise DBError("DB_ERROR", "centroid_lat and centroid_lng are required")
    centroid_lat = _round_coord(centroid_lat, "centroid_lat", 90)
    centroid_lng = _round_coord(centroid_lng, "centroid_lng", 180)
    _require_in(severity, CLUSTER_SEVERITIES, "severity")
    if not isinstance(report_ids, list) or not report_ids:
        raise DBError("DB_ERROR", "report_ids must be a non-empty list")
    unique_ids = list(dict.fromkeys(_require_text(r, "report_id") for r in report_ids))
    if isinstance(window_hours, bool) or not isinstance(window_hours, int) or window_hours <= 0:
        raise DBError("DB_ERROR", "window_hours must be a positive integer")
    _require_in(data_source, DATA_SOURCES, "data_source")
    if _is_memory():
        for report_id in unique_ids:
            if _mem_find("reports", report_id) is None:
                raise DBError("DB_ERROR", f"report not found: {report_id}")
        row = {
            "id": _new_id("clu_"),
            "crop": crop,
            "suspected_issue": suspected_issue,
            "area_label": area_label,
            "centroid_lat": centroid_lat,
            "centroid_lng": centroid_lng,
            "severity": severity,
            "report_count": len(unique_ids),
            "window_hours": window_hours,
            "data_source": data_source,
            "created_at": _now_iso(),
        }
        _MEM["clusters"].append(row)
        for report_id in unique_ids:
            _MEM["cluster_reports"].append({"cluster_id": row["id"], "report_id": report_id})
        return _cluster_out(row)
    return _sb_call("create_cluster", locals())


def update_cluster(cluster_id: str, severity: str, report_count: int, report_ids: list[str]) -> dict:
    """OPTIONAL (contract C11): upgrade a cluster and link any new reports."""
    cluster_id = _require_text(cluster_id, "cluster_id")
    _require_in(severity, CLUSTER_SEVERITIES, "severity")
    if isinstance(report_count, bool) or not isinstance(report_count, int) or report_count < 1:
        raise DBError("DB_ERROR", "report_count must be a positive integer")
    if not isinstance(report_ids, list):
        raise DBError("DB_ERROR", "report_ids must be a list")
    unique_ids = list(dict.fromkeys(_require_text(r, "report_id") for r in report_ids))
    if _is_memory():
        row = _mem_find("clusters", cluster_id)
        if row is None:
            raise DBError("DB_ERROR", f"cluster not found: {cluster_id}")
        for report_id in unique_ids:
            if _mem_find("reports", report_id) is None:
                raise DBError("DB_ERROR", f"report not found: {report_id}")
        linked = {c["report_id"] for c in _MEM["cluster_reports"] if c["cluster_id"] == cluster_id}
        for report_id in unique_ids:
            if report_id not in linked:
                _MEM["cluster_reports"].append({"cluster_id": cluster_id, "report_id": report_id})
        row["severity"] = severity
        row["report_count"] = report_count
        return _cluster_out(row)
    return _sb_call("update_cluster", locals())


def list_clusters() -> list[dict]:
    """Public Cluster models (no farm or report ids), newest first."""
    if _is_memory():
        return [_cluster_out(row) for row in reversed(_MEM["clusters"])]
    return _sb_call("list_clusters", locals())


def get_cluster_detail(cluster_id: str) -> dict | None:
    """{"cluster": ..., "reports": [...], "alerts": [...]} or None if the cluster does not exist."""
    cluster_id = _require_text(cluster_id, "cluster_id")
    if _is_memory():
        row = _mem_find("clusters", cluster_id)
        if row is None:
            return None
        reports = []
        for link in _MEM["cluster_reports"]:
            if link["cluster_id"] != cluster_id:
                continue
            report = _mem_find("reports", link["report_id"])
            if report is None:
                continue
            farm = _mem_find("farms", report["farm_id"])
            reports.append({
                "report_id": report["id"],
                "created_at": report["created_at"],
                "crop": farm["crop"] if farm else None,
                "suspected_issue": report["suspected_issue"],
                "confidence_band": report["confidence_band"],
                "area_label": farm["area_label"] if farm else None,
                "image_url": signed_image_url(report["image_path"]),
            })
        alerts = [_alert_out(a) for a in _MEM["alerts"] if a["cluster_id"] == cluster_id]
        return {"cluster": _cluster_out(row), "reports": reports, "alerts": alerts}
    return _sb_call("get_cluster_detail", locals())


def insert_alert(cluster_id: str, farm_id: str, message: str, delivered: bool,
                 data_source: str = "live") -> dict | None:
    """Save an alert. Returns None if this farm already has an alert for this cluster."""
    cluster_id = _require_text(cluster_id, "cluster_id")
    farm_id = _require_text(farm_id, "farm_id")
    message = _require_text(message, "message")
    if not isinstance(delivered, bool):
        raise DBError("DB_ERROR", "delivered must be true or false")
    _require_in(data_source, DATA_SOURCES, "data_source")
    if _is_memory():
        if _mem_find("clusters", cluster_id) is None:
            raise DBError("DB_ERROR", f"cluster not found: {cluster_id}")
        if _mem_find("farms", farm_id) is None:
            raise DBError("DB_ERROR", f"farm not found: {farm_id}")
        for existing in _MEM["alerts"]:
            if existing["cluster_id"] == cluster_id and existing["farm_id"] == farm_id:
                return None
        row = {
            "id": _new_id("alt_"),
            "cluster_id": cluster_id,
            "farm_id": farm_id,
            "message": message,
            "channel": "telegram",
            "delivered": delivered,
            "sent_at": _now_iso() if delivered else None,
            "data_source": data_source,
        }
        _MEM["alerts"].append(row)
        return _alert_out(row)
    return _sb_call("insert_alert", locals())


def insert_reminder(report_id: str, due_at: str, message: str) -> dict:
    """Schedule a follow-up reminder. due_at is an ISO 8601 timestamp."""
    report_id = _require_text(report_id, "report_id")
    due = _parse_ts(due_at)
    message = _require_text(message, "message")
    if _is_memory():
        if _mem_find("reports", report_id) is None:
            raise DBError("DB_ERROR", f"report not found: {report_id}")
        row = {
            "id": _new_id("rem_"),
            "report_id": report_id,
            "due_at": due.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "message": message,
            "sent": False,
            "sent_at": None,
        }
        _MEM["reminders"].append(row)
        return _reminder_out(row)
    return _sb_call("insert_reminder", locals())


def due_reminders(now_iso: str) -> list[dict]:
    """Unsent reminders due at or before now_iso, oldest first.
    Each row has the reminder fields plus report_id and telegram_chat_id."""
    now = _parse_ts(now_iso)
    if _is_memory():
        due = [r for r in _MEM["reminders"] if not r["sent"] and _parse_ts(r["due_at"]) <= now]
        due.sort(key=lambda r: _parse_ts(r["due_at"]))
        out = []
        for row in due:
            report = _mem_find("reports", row["report_id"])
            farm = _mem_find("farms", report["farm_id"]) if report else None
            farmer = _mem_find("farmers", farm["farmer_id"]) if farm else None
            item = _reminder_out(row)
            item["telegram_chat_id"] = farmer["telegram_chat_id"] if farmer else None
            out.append(item)
        return out
    return _sb_call("due_reminders", locals())


def mark_reminder_sent(reminder_id: str) -> None:
    """Mark a reminder as sent."""
    reminder_id = _require_text(reminder_id, "reminder_id")
    if _is_memory():
        row = _mem_find("reminders", reminder_id)
        if row is None:
            raise DBError("DB_ERROR", f"reminder not found: {reminder_id}")
        row["sent"] = True
        row["sent_at"] = _now_iso()
        return None
    return _sb_call("mark_reminder_sent", locals())


# ---------------------------------------------------------------------------
# Supabase mode (DB_MODE=supabase)
# ---------------------------------------------------------------------------
import inspect

_SB_CLIENT = None


def _sb():
    """Create the Supabase client once (server-side, uses the service key)."""
    global _SB_CLIENT
    if _SB_CLIENT is None:
        url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        if url.endswith("/rest/v1"):
            url = url[: -len("/rest/v1")]
        key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
        if not url or not key:
            raise DBError("DB_ERROR", "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        try:
            from supabase import create_client
            _SB_CLIENT = create_client(url, key)
        except Exception as exc:
            raise DBError("DB_ERROR", f"could not connect to Supabase: {exc}")
    return _SB_CLIENT


def _bucket() -> str:
    return os.getenv("SUPABASE_STORAGE_BUCKET", "report-images").strip() or "report-images"


def _sb_call(name: str, local_vars: dict):
    """Call _sb_<name> with only the arguments it declares. Any failure becomes a DBError."""
    func = globals().get("_sb_" + name)
    if func is None:
        raise DBError("DB_ERROR", f"{name}: Supabase mode is not built yet. Use DB_MODE=memory for now.")
    wanted = inspect.signature(func).parameters
    kwargs = {k: local_vars[k] for k in wanted if k in local_vars}
    try:
        return func(**kwargs)
    except DBError:
        raise
    except Exception as exc:
        raise DBError("DB_ERROR", f"{name} failed: {exc}")


def _sb_upload_image(image_bytes, farm_id, content_type):
    path = f"{farm_id}/{uuid.uuid4().hex[:12]}.jpg"
    _sb().storage.from_(_bucket()).upload(
        path=path,
        file=bytes(image_bytes),
        file_options={"content-type": content_type},
    )
    return path


def _sb_signed_image_url(path, expires_s):
    result = _sb().storage.from_(_bucket()).create_signed_url(path, expires_s)
    url = None
    if isinstance(result, dict):
        url = result.get("signedURL") or result.get("signedUrl")
    if not url:
        raise DBError("DB_ERROR", f"could not sign image path: {path}")
    if not url.startswith("http"):
        base = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        url = f"{base}/storage/v1{url}"
    return url


# ---- Supabase: farmers and farms ----
def _sb_get_or_create_farmer(telegram_chat_id, name, language):
    table = _sb().table("farmers")
    if telegram_chat_id is not None:
        found = table.select("*").eq("telegram_chat_id", telegram_chat_id).limit(1).execute().data
        if found:
            updated = table.update({"name": name, "language": language}).eq("id", found[0]["id"]).execute().data
            return _farmer_out(updated[0] if updated else {**found[0], "name": name, "language": language})
    try:
        created = table.insert({
            "name": name,
            "language": language,
            "telegram_chat_id": telegram_chat_id,
        }).execute().data
    except Exception:
        # two requests may race on the same chat id: read the row the other one created
        if telegram_chat_id is not None:
            found = table.select("*").eq("telegram_chat_id", telegram_chat_id).limit(1).execute().data
            if found:
                return _farmer_out(found[0])
        raise
    return _farmer_out(created[0])


def _sb_get_farmer_for_farm(farm_id):
    farms = _sb().table("farms").select("farmer_id").eq("id", farm_id).limit(1).execute().data
    if not farms:
        return None
    farmers = _sb().table("farmers").select("*").eq("id", farms[0]["farmer_id"]).limit(1).execute().data
    return _farmer_out(farmers[0]) if farmers else None


def _sb_get_or_create_farm(farmer_id, crop, sowing_date, area_label, lat, lng):
    table = _sb().table("farms")
    found = (table.select("*").eq("farmer_id", farmer_id).eq("crop", crop)
             .order("created_at").limit(1).execute().data)
    if found:
        changes = {}
        if sowing_date is not None:
            changes["sowing_date"] = sowing_date
        if area_label is not None:
            changes["area_label"] = area_label
        if lat is not None:
            changes["lat"] = lat
        if lng is not None:
            changes["lng"] = lng
        if not changes:
            return _farm_out(found[0])
        updated = table.update(changes).eq("id", found[0]["id"]).execute().data
        return _farm_out(updated[0] if updated else {**found[0], **changes})
    created = table.insert({
        "farmer_id": farmer_id,
        "crop": crop,
        "sowing_date": sowing_date,
        "area_label": area_label,
        "lat": lat,
        "lng": lng,
    }).execute().data
    return _farm_out(created[0])


def _sb_get_farm(farm_id):
    found = _sb().table("farms").select("*").eq("id", farm_id).limit(1).execute().data
    return _farm_out(found[0]) if found else None


def _sb_list_farms():
    farms = _sb().table("farms").select("*").order("created_at").execute().data or []
    farmers = _sb().table("farmers").select("id,name,language").execute().data or []
    reports = _sb().table("reports").select("farm_id").execute().data or []
    by_farmer = {f["id"]: f for f in farmers}
    counts = {}
    for r in reports:
        counts[r["farm_id"]] = counts.get(r["farm_id"], 0) + 1
    out = []
    for farm in farms:
        farmer = by_farmer.get(farm["farmer_id"])
        out.append({
            "id": farm["id"],
            "crop": farm["crop"],
            "area_label": farm["area_label"],
            "farmer_name": farmer["name"] if farmer else None,
            "language": farmer["language"] if farmer else None,
            "report_count": counts.get(farm["id"], 0),
            "data_source": farm["data_source"],
        })
    return out


# ---- Supabase: reports, events, expert reviews ----
import re


def _ts(value):
    """Postgres timestamp -> '2026-11-12T09:15:00Z' (the format the contract uses)."""
    if value is None:
        return None
    return _parse_ts(re.sub(r"\.\d+", "", str(value))).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_z(moment) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_url(path):
    """Signed URL, or None if the image is missing (so one bad image never breaks a whole report)."""
    try:
        return signed_image_url(path)
    except DBError:
        return None


def _sb_review_out(row):
    return {
        "id": row["id"],
        "report_id": row["report_id"],
        "expert_name": row["expert_name"],
        "guidance": row["guidance"],
        "confirmed_issue": row["confirmed_issue"],
        "created_at": _ts(row["created_at"]),
    }


def _sb_event_out(row):
    out = {"status": row["status"], "actor": row["actor"], "timestamp": _ts(row["created_at"])}
    if row.get("note") is not None:
        out["note"] = row["note"]
    return out


def _sb_report_model(row, farm, events, review):
    return {
        "id": row["id"],
        "farm_id": row["farm_id"],
        "crop": farm["crop"] if farm else None,
        "created_at": _ts(row["created_at"]),
        "status": row["status"],
        "data_source": row["data_source"],
        "image_url": _safe_url(row["image_path"]),
        "voice_transcript": row["voice_transcript"],
        "voice_language": row["voice_language"],
        "assessment": {
            "decision": row["decision"],
            "suspected_issue": row["suspected_issue"],
            "confidence_band": row["confidence_band"],
            "image_quality": row["image_quality"],
            "visible_symptoms": row["visible_symptoms"] or [],
            "confirmed": bool(review is not None and review["confirmed_issue"] is not None),
        },
        "why": row["why"] or [],
        "weather": row["weather"],
        "risk": row["risk"],
        "farmer_reply": {
            "language": row["reply_language"],
            "text": row["reply_text"],
            "audio_url": None,
        },
        "events": [_sb_event_out(e) for e in events],
        "expert_review": _sb_review_out(review) if review else None,
    }


def _sb_reviews_by_report(report_ids):
    if not report_ids:
        return {}
    rows = _sb().table("expert_reviews").select("*").in_("report_id", report_ids).execute().data or []
    return {r["report_id"]: r for r in rows}


def _sb_insert_report(farm_id, image_path, voice_transcript, voice_language, decision, issue,
                      band, quality, symptoms, escalation_reason, why, weather, risk,
                      reply_language, reply_text, status, data_source):
    farm = _sb().table("farms").select("*").eq("id", farm_id).limit(1).execute().data
    if not farm:
        raise DBError("DB_ERROR", f"farm not found: {farm_id}")
    created = _sb().table("reports").insert({
        "farm_id": farm_id,
        "image_path": image_path,
        "voice_transcript": voice_transcript,
        "voice_language": voice_language,
        "decision": decision,
        "suspected_issue": issue,
        "confidence_band": band,
        "image_quality": quality,
        "visible_symptoms": symptoms,
        "escalation_reason": escalation_reason,
        "why": why,
        "weather": weather,
        "risk": risk,
        "reply_language": reply_language,
        "reply_text": reply_text,
        "status": status,
        "data_source": data_source,
    }).execute().data
    return _sb_report_model(created[0], farm[0], [], None)


def _sb_add_report_event(report_id, status, actor, note):
    found = _sb().table("reports").select("id").eq("id", report_id).limit(1).execute().data
    if not found:
        raise DBError("DB_ERROR", f"report not found: {report_id}")
    created = _sb().table("report_events").insert({
        "report_id": report_id,
        "status": status,
        "actor": actor,
        "note": note,
    }).execute().data
    return _sb_event_out(created[0])


def _sb_update_report_status(report_id, status):
    updated = _sb().table("reports").update({"status": status}).eq("id", report_id).execute().data
    if not updated:
        raise DBError("DB_ERROR", f"report not found: {report_id}")
    return None


def _sb_get_report(report_id):
    rows = _sb().table("reports").select("*").eq("id", report_id).limit(1).execute().data
    if not rows:
        return None
    row = rows[0]
    farms = _sb().table("farms").select("*").eq("id", row["farm_id"]).limit(1).execute().data
    events = (_sb().table("report_events").select("*").eq("report_id", report_id)
              .order("created_at").order("id").execute().data or [])
    reviews = _sb().table("expert_reviews").select("*").eq("report_id", report_id).limit(1).execute().data
    return _sb_report_model(row, farms[0] if farms else None, events, reviews[0] if reviews else None)


def _sb_list_farm_reports(farm_id):
    rows = (_sb().table("reports").select("*").eq("farm_id", farm_id)
            .order("created_at", desc=True).execute().data or [])
    reviews = _sb_reviews_by_report([r["id"] for r in rows])
    out = []
    for row in rows:
        review = reviews.get(row["id"])
        out.append({
            "report_id": row["id"],
            "created_at": _ts(row["created_at"]),
            "status": row["status"],
            "decision": row["decision"],
            "suspected_issue": row["suspected_issue"],
            "confidence_band": row["confidence_band"],
            "image_url": _safe_url(row["image_path"]),
            "expert_guidance": review["guidance"] if review else None,
        })
    return out


def _sb_count_recent_abstains(farm_id, minutes):
    cutoff = _iso_z(datetime.now(timezone.utc) - timedelta(minutes=minutes))
    rows = (_sb().table("reports").select("decision").eq("farm_id", farm_id)
            .gte("created_at", cutoff).order("created_at", desc=True).execute().data or [])
    count = 0
    for row in rows:
        if row["decision"] != "abstain_request_better_image":
            break
        count += 1
    return count


def _sb_list_expert_cases(status):
    rows = (_sb().table("reports").select("*").eq("status", status)
            .order("created_at").execute().data or [])
    if not rows:
        return []
    farm_ids = list({r["farm_id"] for r in rows})
    farms = _sb().table("farms").select("id,crop,area_label").in_("id", farm_ids).execute().data or []
    by_id = {f["id"]: f for f in farms}
    out = []
    for row in rows:
        farm = by_id.get(row["farm_id"])
        out.append({
            "report_id": row["id"],
            "created_at": _ts(row["created_at"]),
            "farm_id": row["farm_id"],
            "crop": farm["crop"] if farm else None,
            "area_label": farm["area_label"] if farm else None,
            "suspected_issue": row["suspected_issue"],
            "confidence_band": row["confidence_band"],
            "decision": row["decision"],
            "escalation_reason": row["escalation_reason"],
            "image_url": _safe_url(row["image_path"]),
            "rain_expected": bool((row["weather"] or {}).get("rain_expected", False)),
            "data_source": row["data_source"],
        })
    return out


def _sb_insert_expert_review(report_id, expert_name, guidance, confirmed_issue):
    found = _sb().table("reports").select("id").eq("id", report_id).limit(1).execute().data
    if not found:
        raise DBError("DB_ERROR", f"report not found: {report_id}")
    existing = _sb().table("expert_reviews").select("id").eq("report_id", report_id).limit(1).execute().data
    if existing:
        raise DBError("DB_ERROR", f"expert review already exists for report {report_id}")
    created = _sb().table("expert_reviews").insert({
        "report_id": report_id,
        "expert_name": expert_name,
        "guidance": guidance,
        "confirmed_issue": confirmed_issue,
    }).execute().data
    return _sb_review_out(created[0])



# ---- Supabase: nearby search, clusters, alerts, reminders ----
def _sb_cluster(row):
    return _cluster_out({**row, "created_at": _ts(row["created_at"])})


def _sb_alert(row):
    return _alert_out({**row, "sent_at": _ts(row.get("sent_at"))})


def _sb_find_similar_recent_reports(crop, suspected_issue, since_hours, lat, lng, radius_km):
    cutoff = _iso_z(datetime.now(timezone.utc) - timedelta(hours=since_hours))
    rows = (_sb().table("reports").select("*").eq("suspected_issue", suspected_issue)
            .in_("confidence_band", ["medium", "high"]).gte("created_at", cutoff)
            .order("created_at", desc=True).execute().data or [])
    if not rows:
        return []
    farm_ids = list({r["farm_id"] for r in rows})
    farms = _sb().table("farms").select("*").in_("id", farm_ids).execute().data or []
    by_id = {f["id"]: f for f in farms}
    out = []
    for row in rows:
        farm = by_id.get(row["farm_id"])
        if farm is None or farm["crop"] != crop:
            continue
        if farm["lat"] is None or farm["lng"] is None:
            continue
        if _haversine_km(lat, lng, float(farm["lat"]), float(farm["lng"])) > radius_km:
            continue
        out.append({
            "report_id": row["id"],
            "farm_id": row["farm_id"],
            "confidence_band": row["confidence_band"],
            "created_at": _ts(row["created_at"]),
            "lat": float(farm["lat"]),
            "lng": float(farm["lng"]),
            "area_label": farm["area_label"],
            "suspected_issue": row["suspected_issue"],
            "data_source": row.get("data_source") or "live",
        })
    return out


def _sb_find_nearby_farms(crop, lat, lng, radius_km, exclude_farm_id):
    farms = _sb().table("farms").select("*").eq("crop", crop).execute().data or []
    farmer_ids = list({f["farmer_id"] for f in farms})
    farmers = []
    if farmer_ids:
        farmers = _sb().table("farmers").select("*").in_("id", farmer_ids).execute().data or []
    by_id = {f["id"]: f for f in farmers}
    out = []
    for farm in farms:
        if farm["id"] == exclude_farm_id:
            continue
        if farm["lat"] is None or farm["lng"] is None:
            continue
        if _haversine_km(lat, lng, float(farm["lat"]), float(farm["lng"])) > radius_km:
            continue
        farmer = by_id.get(farm["farmer_id"])
        out.append({
            "farm_id": farm["id"],
            "farmer_id": farm["farmer_id"],
            "telegram_chat_id": farmer["telegram_chat_id"] if farmer else None,
            "language": farmer["language"] if farmer else None,
            "area_label": farm["area_label"],
            "lat": float(farm["lat"]),
            "lng": float(farm["lng"]),
        })
    return out


def _sb_check_reports_exist(report_ids):
    if not report_ids:
        return
    found = _sb().table("reports").select("id").in_("id", report_ids).execute().data or []
    missing = set(report_ids) - {r["id"] for r in found}
    if missing:
        raise DBError("DB_ERROR", f"report not found: {sorted(missing)[0]}")


def _sb_create_cluster(crop, suspected_issue, area_label, centroid_lat, centroid_lng, severity,
                       unique_ids, window_hours, data_source):
    _sb_check_reports_exist(unique_ids)
    created = _sb().table("clusters").insert({
        "crop": crop,
        "suspected_issue": suspected_issue,
        "area_label": area_label,
        "centroid_lat": centroid_lat,
        "centroid_lng": centroid_lng,
        "severity": severity,
        "report_count": len(unique_ids),
        "window_hours": window_hours,
        "data_source": data_source,
    }).execute().data
    cluster = created[0]
    try:
        _sb().table("cluster_reports").insert(
            [{"cluster_id": cluster["id"], "report_id": rid} for rid in unique_ids]
        ).execute()
    except Exception:
        _sb().table("clusters").delete().eq("id", cluster["id"]).execute()
        raise
    return _sb_cluster(cluster)


def _sb_update_cluster(cluster_id, severity, report_count, unique_ids):
    found = _sb().table("clusters").select("id").eq("id", cluster_id).limit(1).execute().data
    if not found:
        raise DBError("DB_ERROR", f"cluster not found: {cluster_id}")
    _sb_check_reports_exist(unique_ids)
    links = _sb().table("cluster_reports").select("report_id").eq("cluster_id", cluster_id).execute().data or []
    linked = {link["report_id"] for link in links}
    new_links = [{"cluster_id": cluster_id, "report_id": rid} for rid in unique_ids if rid not in linked]
    if new_links:
        _sb().table("cluster_reports").insert(new_links).execute()
    updated = _sb().table("clusters").update(
        {"severity": severity, "report_count": report_count}
    ).eq("id", cluster_id).execute().data
    return _sb_cluster(updated[0])


def _sb_list_clusters():
    rows = _sb().table("clusters").select("*").order("created_at", desc=True).execute().data or []
    return [_sb_cluster(r) for r in rows]


def _sb_get_cluster_detail(cluster_id):
    rows = _sb().table("clusters").select("*").eq("id", cluster_id).limit(1).execute().data
    if not rows:
        return None
    links = _sb().table("cluster_reports").select("report_id").eq("cluster_id", cluster_id).execute().data or []
    report_ids = [link["report_id"] for link in links]
    reports = []
    if report_ids:
        report_rows = (_sb().table("reports").select("*").in_("id", report_ids)
                       .order("created_at").execute().data or [])
        farm_ids = list({r["farm_id"] for r in report_rows})
        farms = _sb().table("farms").select("id,crop,area_label").in_("id", farm_ids).execute().data or []
        by_id = {f["id"]: f for f in farms}
        for report in report_rows:
            farm = by_id.get(report["farm_id"])
            reports.append({
                "report_id": report["id"],
                "created_at": _ts(report["created_at"]),
                "crop": farm["crop"] if farm else None,
                "suspected_issue": report["suspected_issue"],
                "confidence_band": report["confidence_band"],
                "area_label": farm["area_label"] if farm else None,
                "image_url": _safe_url(report["image_path"]),
            })
    alert_rows = _sb().table("alerts").select("*").eq("cluster_id", cluster_id).execute().data or []
    return {
        "cluster": _sb_cluster(rows[0]),
        "reports": reports,
        "alerts": [_sb_alert(a) for a in alert_rows],
    }


def _sb_insert_alert(cluster_id, farm_id, message, delivered, data_source):
    if not _sb().table("clusters").select("id").eq("id", cluster_id).limit(1).execute().data:
        raise DBError("DB_ERROR", f"cluster not found: {cluster_id}")
    if not _sb().table("farms").select("id").eq("id", farm_id).limit(1).execute().data:
        raise DBError("DB_ERROR", f"farm not found: {farm_id}")

    def already_exists():
        return bool(_sb().table("alerts").select("id").eq("cluster_id", cluster_id)
                    .eq("farm_id", farm_id).limit(1).execute().data)

    if already_exists():
        return None
    try:
        created = _sb().table("alerts").insert({
            "cluster_id": cluster_id,
            "farm_id": farm_id,
            "message": message,
            "channel": "telegram",
            "delivered": delivered,
            "sent_at": _now_iso() if delivered else None,
            "data_source": data_source,
        }).execute().data
    except Exception:
        if already_exists():  # two requests raced: the unique (cluster, farm) rule caught the second
            return None
        raise
    return _sb_alert(created[0])


def _sb_reminder_out(row):
    return {
        "id": row["id"],
        "report_id": row["report_id"],
        "due_at": _ts(row["due_at"]),
        "message": row["message"],
        "sent": row["sent"],
    }


def _sb_insert_reminder(report_id, due, message):
    if not _sb().table("reports").select("id").eq("id", report_id).limit(1).execute().data:
        raise DBError("DB_ERROR", f"report not found: {report_id}")
    created = _sb().table("reminders").insert({
        "report_id": report_id,
        "due_at": _iso_z(due),
        "message": message,
    }).execute().data
    return _sb_reminder_out(created[0])


def _sb_due_reminders(now):
    rows = (_sb().table("reminders").select("*").eq("sent", False)
            .lte("due_at", _iso_z(now)).order("due_at").execute().data or [])
    if not rows:
        return []
    report_ids = list({r["report_id"] for r in rows})
    reports = _sb().table("reports").select("id,farm_id").in_("id", report_ids).execute().data or []
    farm_of_report = {r["id"]: r["farm_id"] for r in reports}
    farm_ids = list(set(farm_of_report.values()))
    farms = _sb().table("farms").select("id,farmer_id").in_("id", farm_ids).execute().data or [] if farm_ids else []
    farmer_of_farm = {f["id"]: f["farmer_id"] for f in farms}
    farmer_ids = list(set(farmer_of_farm.values()))
    farmers = _sb().table("farmers").select("id,telegram_chat_id").in_("id", farmer_ids).execute().data or [] if farmer_ids else []
    chat_of_farmer = {f["id"]: f["telegram_chat_id"] for f in farmers}
    out = []
    for row in rows:
        item = _sb_reminder_out(row)
        farm_id = farm_of_report.get(row["report_id"])
        farmer_id = farmer_of_farm.get(farm_id)
        item["telegram_chat_id"] = chat_of_farmer.get(farmer_id)
        out.append(item)
    return out


def _sb_mark_reminder_sent(reminder_id):
    updated = _sb().table("reminders").update(
        {"sent": True, "sent_at": _now_iso()}
    ).eq("id", reminder_id).execute().data
    if not updated:
        raise DBError("DB_ERROR", f"reminder not found: {reminder_id}")
    return None

