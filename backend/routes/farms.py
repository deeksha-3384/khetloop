"""Endpoints 3 and 4: list farms, farm timeline."""
from flask import Blueprint

from backend.utils import deps
from backend.utils.responses import err, ok

bp = Blueprint("farms", __name__)


@bp.get("/api/farms")
def list_farms():
    return ok({"farms": deps.get_db().list_farms()})


@bp.get("/api/farms/<farm_id>/timeline")
def farm_timeline(farm_id):
    db = deps.get_db()
    farm = db.get_farm(farm_id)
    if farm is None:
        return err("NOT_FOUND", "Farm not found", 404)
    return ok({
        "farm": {"id": farm.get("id"), "crop": farm.get("crop"), "area_label": farm.get("area_label"),
                 "sowing_date": farm.get("sowing_date")},
        "items": db.list_farm_reports(farm_id),
    })