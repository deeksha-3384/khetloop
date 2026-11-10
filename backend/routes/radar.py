"""Endpoints 7 and 8: public clusters, cluster detail (key)."""
from flask import Blueprint

from backend.utils.auth import require_expert_key
from backend.utils.mock_loader import load_mock
from backend.utils.responses import err, ok

bp = Blueprint("radar", __name__)


@bp.get("/api/radar/clusters")
def list_clusters():
    return ok(load_mock("radar_clusters.json"))


@bp.get("/api/radar/clusters/<cluster_id>")
@require_expert_key
def cluster_detail(cluster_id):
    detail = load_mock("cluster_detail.json")
    if detail["cluster"]["id"] != cluster_id:
        return err("NOT_FOUND", "Cluster not found", 404)
    return ok(detail)