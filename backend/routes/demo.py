"""
Endpoint 10: scripted community scenario (key). Everything it creates is labelled 'simulated'.
Creates 3 simulated farms with 3 similar reports near the target farm, runs the REAL check_cluster(),
and alerts the target farm. Each call creates a fresh cluster so the demo can be repeated.
"""
import base64
from pathlib import Path

from flask import Blueprint, request

from backend.rules.clustering import check_cluster
from backend.services.report_pipeline import deliver_alerts
from backend.utils import deps
from backend.utils.auth import require_expert_key
from backend.utils.responses import err, ok
from backend.routes.radar import public_cluster
from shared.constants import COORD_DECIMALS, CROPS, ISSUES

bp = Blueprint("demo", __name__)

OFFSETS = [(0.01, 0.0), (-0.01, 0.01), (0.0, -0.01)]
SIM_LANGUAGES = ["kn", "hi", "kn"]
DEFAULT_COORDS = (13.14, 78.13)
SAMPLE_IMAGE = Path(__file__).resolve().parents[2] / "data" / "test_images" / "clear_tomato_01.jpg"
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _sample_image():
    try:
        return SAMPLE_IMAGE.read_bytes(), "image/jpeg"
    except OSError:
        return TINY_PNG, "image/png"


def _simulated_farm(db, crop, area_label, lat, lng, i):
    farmer = db.get_or_create_farmer(None, "Simulated Farmer %d" % (i + 1), SIM_LANGUAGES[i])
    try:
        return db.get_or_create_farm(farmer["id"], crop, None, area_label, lat, lng, data_source="simulated")
    except TypeError:  # P2's get_or_create_farm has no data_source argument (yet)
        return db.get_or_create_farm(farmer["id"], crop, None, area_label, lat, lng)


@bp.post("/api/demo/simulate-cluster")
@require_expert_key
def simulate_cluster():
    body = request.get_json(silent=True) or {}
    crop, issue = body.get("crop"), body.get("suspected_issue")
    area_label = (body.get("area_label") or "").strip()
    target_id = body.get("target_farm_id")
    if crop not in CROPS:
        return err("INVALID_REQUEST", "crop is invalid", 400)
    if issue not in ISSUES or issue in ("healthy", "unknown"):
        return err("INVALID_REQUEST", "suspected_issue must be a disease issue", 400)
    if not area_label:
        return err("INVALID_REQUEST", "area_label is required", 400)

    db = deps.get_db()
    target = db.get_farm(target_id) if target_id else None
    if target is None:
        return err("NOT_FOUND", "target_farm_id not found", 404)

    base_lat = target.get("lat") if target.get("lat") is not None else DEFAULT_COORDS[0]
    base_lng = target.get("lng") if target.get("lng") is not None else DEFAULT_COORDS[1]
    image_bytes, content_type = _sample_image()
    assessment = {"decision": "preliminary_assessment", "suspected_issue": issue, "confidence_band": "medium",
                  "image_quality": "good", "visible_symptoms": ["visible leaf spots"], "confirmed": False}

    last = None
    for i, (d_lat, d_lng) in enumerate(OFFSETS):
        lat, lng = round(float(base_lat) + d_lat, COORD_DECIMALS), round(float(base_lng) + d_lng, COORD_DECIMALS)
        farm = _simulated_farm(db, crop, area_label, lat, lng, i)
        path = db.upload_image(image_bytes, farm["id"], content_type)
        row = db.insert_report(
            farm_id=farm["id"], image_path=path, voice_transcript=None, voice_language=None,
            assessment=assessment, escalation_reason=None, why=[], weather=None, risk=None,
            reply_language="en", reply_text="Simulated report for the demo.", status="ai_assessed",
            data_source="simulated")
        db.add_report_event(row["id"], "submitted", "system")
        db.add_report_event(row["id"], "ai_assessed", "system")
        last = {"report_id": row["id"], "farm_id": farm["id"], "crop": crop, "suspected_issue": issue,
                "confidence_band": "medium", "lat": lat, "lng": lng, "area_label": area_label,
                "data_source": "simulated"}

    result = check_cluster(last, db, reuse_existing=False)
    if result is None:
        return err("INTERNAL_ERROR", "Could not form a cluster from the simulated reports", 500)
    alerts_sent = deliver_alerts(result, crop, db, deps.send_telegram, extra_farm_ids=[target_id]) or 0
    return ok({"cluster": public_cluster(result["cluster"]), "alerts_sent": alerts_sent,
               "data_source": "simulated"})