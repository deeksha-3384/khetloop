"""
The complete report pipeline (Master Contract section 9.1).
Imported by: backend/routes/reports.py, backend/bot/handlers.py, backend/routes/demo.py

process_report(farm_id, image_bytes, image_filename, audio_path=None, voice_text=None, language=None)
    -> the Report model dict (exactly what db_client.get_report returns).
run_pipeline(...same arguments...)
    -> {"report": Report, "audio_path": str | None, "cluster": dict | None,
        "alerts_sent": int, "degraded": [names of services that failed]}
    The Telegram bot uses this one, because it also needs the local audio file to send.

Raises (so the route can answer correctly):
    LookupError  farm not found           -> 404 NOT_FOUND
    ValueError   image is not a real image -> 400 INVALID_REQUEST
    DBError      from db_client            -> 500 DB_ERROR
Every other failure (vision, speech, weather, reminders, clustering) is absorbed: the report is still
saved and the farmer still gets a reply. Failures are listed in result["degraded"].

deps (optional, used by tests): any object with some of the attributes
    db, vision, weather, speech, reminders, send_message
Missing attributes fall back to the real modules (P2 database.db_client, P4 integrations.*).
"""
import importlib
import logging
from datetime import datetime, timezone

from backend.rules.clustering import check_cluster
from backend.rules.decision import decide
from backend.rules.risk import compute_risk
from backend.rules.why import build_why
from backend.services import reply_writer
from shared.constants import (ABSTAIN_RETRY_WINDOW_MIN, FOLLOW_UP_HOURS, LANGUAGES, RADAR_RADIUS_KM,
                              RADAR_TIME_WINDOW_HOURS)

log = logging.getLogger("khetloop.pipeline")

NOT_RECOGNISED = ("unknown", "healthy")
CLUSTERABLE_BANDS = ("medium", "high")
_DEFAULT_MODULES = {
    "db": "database.db_client",
    "vision": "backend.services.gemini_vision",
    "weather": "integrations.weather",
    "speech": "integrations.speech",
    "reminders": "integrations.reminders",
}


def _dep(deps, name):
    if deps is not None and hasattr(deps, name):
        return getattr(deps, name)
    if name == "send_message":
        return None
    try:
        return importlib.import_module(_DEFAULT_MODULES[name])
    except ImportError:
        log.warning("module for %s is not available yet", name)
        return None


def _safe_call(fn, *args):
    """Call fn and return its result, or None if it raised. Used for everything non-critical."""
    try:
        return fn(*args)
    except Exception as e:
        log.warning("%s failed: %s", getattr(fn, "__name__", "call"), type(e).__name__)
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _content_type(filename, image_bytes: bytes) -> str:
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _stored_assessment(assessment, decision: str) -> dict:
    """Assessment in the shape insert_report wants. If the AI failed, store safe 'unknown' values."""
    base = assessment or {"suspected_issue": "unknown", "confidence_band": "low",
                          "image_quality": "poor", "visible_symptoms": []}
    return {"decision": decision, "suspected_issue": base["suspected_issue"],
            "confidence_band": base["confidence_band"], "image_quality": base["image_quality"],
            "visible_symptoms": list(base.get("visible_symptoms") or []), "confirmed": False}


def deliver_alerts(cluster_result: dict, crop: str, db, send_message=None) -> int:
    """Send the cautious notice once per farm per cluster. Returns how many were delivered."""
    cluster = cluster_result["cluster"]
    detail = db.get_cluster_detail(cluster["id"]) or {}
    already = {a.get("farm_id") for a in detail.get("alerts", [])}
    farms = db.find_nearby_farms(crop, cluster["centroid_lat"], cluster["centroid_lng"], RADAR_RADIUS_KM)
    delivered_count = 0
    for farm in farms:
        farm_id = farm.get("farm_id")
        if not farm_id or farm_id in already:
            continue
        lang = farm.get("language") if farm.get("language") in LANGUAGES else "en"
        message = reply_writer.write_alert(crop, cluster.get("area_label"), lang)
        chat_id = farm.get("telegram_chat_id")
        delivered = False
        if chat_id and send_message:
            try:
                delivered = bool(send_message(chat_id, message))
            except Exception as e:
                log.warning("alert send failed: %s", type(e).__name__)
        row = db.insert_alert(cluster["id"], farm_id, message, delivered, cluster.get("data_source", "live"))
        if row is not None and delivered:
            delivered_count += 1
    return delivered_count


def run_pipeline(farm_id, image_bytes, image_filename, audio_path=None, voice_text=None,
                 language=None, deps=None) -> dict:
    db = _dep(deps, "db")
    if db is None:
        raise RuntimeError("The database module (database/db_client.py) is not available")
    vision = _dep(deps, "vision")
    weather_mod = _dep(deps, "weather")
    speech = _dep(deps, "speech")
    reminders = _dep(deps, "reminders")
    send_message = _dep(deps, "send_message")
    degraded = []

    # 1. Farm and farmer
    farm = db.get_farm(farm_id)
    if farm is None:
        raise LookupError("Farm not found")
    farmer = db.get_farmer_for_farm(farm_id) or {}
    farmer_lang = farmer.get("language")
    lang = language if language in LANGUAGES else (farmer_lang if farmer_lang in LANGUAGES else "en")
    crop = farm.get("crop") or "other"
    lat, lng = farm.get("lat"), farm.get("lng")
    has_location = lat is not None and lng is not None
    data_source = "simulated" if farm.get("data_source") == "simulated" else "live"

    # 2. Speech to text (falls back to the typed text)
    transcript = (voice_text or "").strip()
    voice_language = lang if transcript else None
    if audio_path:
        res = _safe_call(speech.stt, audio_path, lang) if speech else None
        text = ((res or {}).get("data") or {}).get("text", "").strip() if res and res.get("ok") else ""
        if text:
            transcript = text
            said_lang = res["data"].get("language")
            voice_language = said_lang if said_lang in LANGUAGES else lang
        else:
            degraded.append("stt")

    # 3. Vision. A file that is not an image is rejected before anything is stored.
    vis = _safe_call(vision.analyse_leaf, image_bytes, crop, transcript) if vision else None
    if vis and not vis.get("ok") and (vis.get("error") or {}).get("code") == "INVALID_REQUEST":
        raise ValueError((vis["error"] or {}).get("message") or "Not a valid image")
    assessment = vis["assessment"] if vis and vis.get("ok") else None
    if assessment is None:
        degraded.append("vision")

    # 4. Weather
    weather = None
    if has_location and weather_mod:
        res = _safe_call(weather_mod.get_forecast, lat, lng)
        if res and res.get("ok") and res.get("data"):
            weather = dict(res["data"])
            weather["data_source"] = res.get("data_source") or "live"
            weather.setdefault("fetched_at", _now_iso())
        else:
            degraded.append("weather")

    # 5. Farm history, retry count, nearby similar reports (all read BEFORE this report is stored)
    history = _safe_call(db.list_farm_reports, farm_id) or []
    retry_count = _safe_call(db.count_recent_abstains, farm_id, ABSTAIN_RETRY_WINDOW_MIN) or 0
    nearby_count = 0
    if (assessment and has_location and assessment["suspected_issue"] not in NOT_RECOGNISED
            and assessment["confidence_band"] in CLUSTERABLE_BANDS):
        rows = _safe_call(db.find_similar_recent_reports, crop, assessment["suspected_issue"],
                          RADAR_TIME_WINDOW_HOURS, lat, lng, RADAR_RADIUS_KM) or []
        nearby_count = len({r.get("farm_id") for r in rows if r.get("farm_id") and r.get("farm_id") != farm_id})

    # 6. Rules decide. The LLM never does.
    decision = decide(assessment, transcript, retry_count)
    d = decision["decision"]
    risk = compute_risk(assessment, weather, nearby_count) if (assessment and d != "abstain_request_better_image") else None
    why = build_why(assessment, weather, nearby_count, decision, history_count=len(history))

    # 7. Reply text
    reply_text = reply_writer.write_reply({"decision": decision, "assessment": assessment, "crop": crop}, lang)

    # 8. Save (image, report, events). From here on a database failure is a real error.
    image_path = db.upload_image(image_bytes, farm_id, _content_type(image_filename, image_bytes))
    status = "expert_review_pending" if d == "escalate_to_expert" else "ai_assessed"
    row = db.insert_report(
        farm_id=farm_id, image_path=image_path, voice_transcript=transcript or None,
        voice_language=voice_language, assessment=_stored_assessment(assessment, d),
        escalation_reason=decision.get("escalation_reason"), why=why, weather=weather, risk=risk,
        reply_language=lang, reply_text=reply_text, status=status, data_source=data_source)
    report_id = row["id"]
    db.add_report_event(report_id, "submitted", "farmer")
    if assessment is not None:
        db.add_report_event(report_id, "ai_assessed", "ai", (vis or {}).get("provider"))
    if d == "escalate_to_expert":
        db.add_report_event(report_id, "expert_review_pending", "rules", decision.get("escalation_reason"))

    # 9. Spoken reply (the text reply is already saved, so a failure here costs nothing)
    audio_out = None
    if speech:
        res = _safe_call(speech.tts, reply_text, lang)
        out = ((res or {}).get("data") or {}).get("audio_path") if res and res.get("ok") else None
        if out:
            audio_out = out
        else:
            degraded.append("tts")

    # 10. Community cluster and alerts
    cluster_result, alerts_sent = None, 0
    if assessment:
        cluster_result = _safe_call(check_cluster, {
            "report_id": report_id, "farm_id": farm_id, "crop": crop,
            "suspected_issue": assessment["suspected_issue"], "confidence_band": assessment["confidence_band"],
            "lat": lat, "lng": lng, "area_label": farm.get("area_label"), "data_source": data_source}, db)
        if cluster_result:
            alerts_sent = _safe_call(deliver_alerts, cluster_result, crop, db, send_message) or 0

    # 11. Follow-up reminder (not when we asked for a better photo: they should resend now)
    if d != "abstain_request_better_image" and reminders:
        res = _safe_call(reminders.schedule, report_id, FOLLOW_UP_HOURS, reply_writer.write_followup(lang))
        if not (res and res.get("ok")):
            degraded.append("reminder")

    if degraded:
        log.info("report %s saved with degraded services: %s", report_id, ", ".join(degraded))
    return {"report": db.get_report(report_id), "audio_path": audio_out, "cluster": cluster_result,
            "alerts_sent": alerts_sent, "degraded": degraded}


def process_report(farm_id, image_bytes, image_filename, audio_path=None, voice_text=None,
                   language=None, deps=None) -> dict:
    return run_pipeline(farm_id, image_bytes, image_filename, audio_path, voice_text, language, deps)["report"]