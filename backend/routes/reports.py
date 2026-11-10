"""Endpoints 1 and 2: submit a report, get a report."""
from flask import Blueprint, request

from backend.utils.mock_loader import farm_ids, get_mock_report, load_mock
from backend.utils.responses import err, ok

bp = Blueprint("reports", __name__)


@bp.post("/api/reports")
def create_report():
    farm_id = (request.form.get("farm_id") or "").strip()
    image = request.files.get("image")
    if not farm_id:
        return err("INVALID_REQUEST", "farm_id is required", 400)
    if image is None or not image.filename:
        return err("INVALID_REQUEST", "image is required", 400)
    if farm_id not in farm_ids():
        return err("NOT_FOUND", "Farm not found", 404)
    # MOCK: the real pipeline (process_report) replaces this in Phase 6.
    return ok(load_mock("report_preliminary.json"), 201)


@bp.get("/api/reports/<report_id>")
def get_report(report_id):
    report = get_mock_report(report_id)
    if report is None:
        return err("NOT_FOUND", "Report not found", 404)
    return ok(report)