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
    _supabase_todo("upload_image")


def signed_image_url(path: str, expires_s: int = 3600) -> str:
    """Return a temporary URL for a stored image (default 1 hour)."""
    path = _require_text(path, "path")
    if not isinstance(expires_s, int) or expires_s <= 0:
        raise DBError("DB_ERROR", "expires_s must be a positive integer")
    if _is_memory():
        return f"https://signed-url.example/{path}"
    _supabase_todo("signed_image_url")


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
    _supabase_todo("get_or_create_farmer")


def get_farmer_for_farm(farm_id: str) -> dict | None:
    """Farmer model (id, name, language, telegram_chat_id) that owns this farm, or None."""
    farm_id = _require_text(farm_id, "farm_id")
    if _is_memory():
        farm = _mem_find("farms", farm_id)
        if farm is None:
            return None
        farmer = _mem_find("farmers", farm["farmer_id"])
        return _farmer_out(farmer) if farmer else None
    _supabase_todo("get_farmer_for_farm")


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
    _supabase_todo("get_or_create_farm")


def get_farm(farm_id: str) -> dict | None:
    """Farm model, or None if it does not exist."""
    farm_id = _require_text(farm_id, "farm_id")
    if _is_memory():
        row = _mem_find("farms", farm_id)
        return _farm_out(row) if row else None
    _supabase_todo("get_farm")


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
    _supabase_todo("list_farms")

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
    _supabase_todo("insert_report")


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
    _supabase_todo("add_report_event")


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
    _supabase_todo("update_report_status")


def get_report(report_id: str) -> dict | None:
    """The full Report model (assessment, weather, risk, why, reply, events, review, signed image URL)."""
    report_id = _require_text(report_id, "report_id")
    if _is_memory():
        row = _mem_find("reports", report_id)
        return _mem_report_model(row) if row else None
    _supabase_todo("get_report")


def list_farm_reports(farm_id: str) -> list[dict]:
    """Timeline items for one farm (API endpoint 4), newest first. Unknown farm -> []."""
    farm_id = _require_text(farm_id, "farm_id")
    if _is_memory():
        rows = [r for r in _MEM["reports"] if r["farm_id"] == farm_id]
        return [_mem_timeline_item(r) for r in reversed(rows)]
    _supabase_todo("list_farm_reports")


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
    _supabase_todo("count_recent_abstains")


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
    _supabase_todo("list_expert_cases")


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
    _supabase_todo("insert_expert_review")


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
            })
        return out
    _supabase_todo("find_similar_recent_reports")


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
    _supabase_todo("find_nearby_farms")


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
    _supabase_todo("create_cluster")


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
    _supabase_todo("update_cluster")


def list_clusters() -> list[dict]:
    """Public Cluster models (no farm or report ids), newest first."""
    if _is_memory():
        return [_cluster_out(row) for row in reversed(_MEM["clusters"])]
    _supabase_todo("list_clusters")


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
    _supabase_todo("get_cluster_detail")


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
    _supabase_todo("insert_alert")


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
    _supabase_todo("insert_reminder")


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
    _supabase_todo("due_reminders")


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
    _supabase_todo("mark_reminder_sent")