"""Endpoints 3 and 4: list farms, farm timeline."""
from flask import Blueprint

from backend.utils.mock_loader import load_mock
from backend.utils.responses import err, ok

bp = Blueprint("farms", __name__)


@bp.get("/api/farms")
def list_farms():
    return ok(load_mock("farms.json"))


@bp.get("/api/farms/<farm_id>/timeline")
def farm_timeline(farm_id):
    farms = {f["id"]: f for f in load_mock("farms.json")["farms"]}
    farm = farms.get(farm_id)
    if farm is None:
        return err("NOT_FOUND", "Farm not found", 404)
    timeline = load_mock("farm_timeline.json")
    if timeline["farm"]["id"] == farm_id:
        return ok(timeline)
    # Other mock farms have no history yet.
    return ok({"farm": {"id": farm_id, "crop": farm["crop"], "area_label": farm["area_label"],
                        "sowing_date": None}, "items": []})