"""Endpoint 10: scripted community scenario (key)."""
from flask import Blueprint, request

from backend.utils.auth import require_expert_key
from backend.utils.mock_loader import farm_ids, load_mock
from backend.utils.responses import err, ok
from shared.constants import CROPS, ISSUES

bp = Blueprint("demo", __name__)


@bp.post("/api/demo/simulate-cluster")
@require_expert_key
def simulate_cluster():
    body = request.get_json(silent=True) or {}
    crop = body.get("crop")
    issue = body.get("suspected_issue")
    area_label = (body.get("area_label") or "").strip()
    target = body.get("target_farm_id")
    if crop not in CROPS:
        return err("INVALID_REQUEST", "crop is invalid", 400)
    if issue not in ISSUES or issue in ("healthy", "unknown"):
        return err("INVALID_REQUEST", "suspected_issue must be a disease issue", 400)
    if not area_label:
        return err("INVALID_REQUEST", "area_label is required", 400)
    if target not in farm_ids():
        return err("NOT_FOUND", "target_farm_id not found", 404)

    # MOCK: the real version creates 3 simulated reports and runs check_cluster() in Phase 9.
    cluster = dict(load_mock("radar_clusters.json")["clusters"][0])
    cluster.update({"crop": crop, "suspected_issue": issue, "area_label": area_label})
    return ok({"cluster": cluster, "alerts_sent": 1, "data_source": "simulated"})