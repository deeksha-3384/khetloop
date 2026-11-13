"""Endpoints 7 and 8: public clusters (privacy-safe), cluster detail (key)."""
from datetime import datetime, timezone

from flask import Blueprint

from backend.utils import deps
from backend.utils.auth import require_expert_key
from backend.utils.responses import err, ok
from shared.constants import CLUSTER_LABEL, COORD_DECIMALS

bp = Blueprint("radar", __name__)


def _num(value):
    try:
        return round(float(value), COORD_DECIMALS)
    except (TypeError, ValueError):
        return None


def public_cluster(c: dict) -> dict:
    """Only the fields of the public Cluster model. Never farm ids, report ids or exact coordinates."""
    return {
        "id": c.get("id"), "crop": c.get("crop"), "suspected_issue": c.get("suspected_issue"),
        "area_label": c.get("area_label"), "centroid_lat": _num(c.get("centroid_lat")),
        "centroid_lng": _num(c.get("centroid_lng")), "severity": c.get("severity"),
        "report_count": c.get("report_count"), "window_hours": c.get("window_hours"),
        "label": CLUSTER_LABEL, "data_source": c.get("data_source"), "created_at": c.get("created_at"),
    }


@bp.get("/api/radar/clusters")
def list_clusters():
    clusters = [public_cluster(c) for c in deps.get_db().list_clusters()]
    return ok({
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "has_simulated": any(c["data_source"] == "simulated" for c in clusters),
        "clusters": clusters,
    })


@bp.get("/api/radar/clusters/<cluster_id>")
@require_expert_key
def cluster_detail(cluster_id):
    detail = deps.get_db().get_cluster_detail(cluster_id)
    if detail is None:
        return err("NOT_FOUND", "Cluster not found", 404)
    return ok({"cluster": public_cluster(detail["cluster"]), "reports": detail.get("reports", []),
               "alerts": detail.get("alerts", [])})