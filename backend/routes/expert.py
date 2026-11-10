"""Endpoints 5 and 6: expert queue and review. Both need X-Expert-Key."""
from flask import Blueprint, request

from backend.utils.auth import require_expert_key
from backend.utils.mock_loader import REVIEWED, load_mock, now_iso
from backend.utils.responses import err, ok
from shared.constants import ISSUES, REPORT_STATUSES

bp = Blueprint("expert", __name__)


@bp.get("/api/expert/cases")
@require_expert_key
def list_cases():
    status = request.args.get("status", "expert_review_pending")
    if status not in REPORT_STATUSES:
        return err("INVALID_REQUEST", "Unknown status", 400)
    cases = []
    if status == "expert_review_pending":
        cases = [c for c in load_mock("expert_cases.json")["cases"] if c["report_id"] not in REVIEWED]
    return ok({"count": len(cases), "cases": cases})


@bp.post("/api/expert/cases/<report_id>/review")
@require_expert_key
def submit_review(report_id):
    body = request.get_json(silent=True) or {}
    expert_name = (body.get("expert_name") or "").strip()
    guidance = (body.get("guidance") or "").strip()
    confirmed_issue = body.get("confirmed_issue")
    if not expert_name or not guidance:
        return err("INVALID_REQUEST", "expert_name and guidance are required", 400)
    if confirmed_issue is not None and confirmed_issue not in ISSUES:
        return err("INVALID_REQUEST", "confirmed_issue must be null or a known issue", 400)

    known = {c["report_id"] for c in load_mock("expert_cases.json")["cases"]}
    if report_id not in known:
        return err("NOT_FOUND", "Report not found", 404)
    if report_id in REVIEWED:
        return err("CONFLICT", "Report already reviewed", 409)

    # MOCK: real version saves via db_client, messages the farmer, schedules a reminder.
    review = {"id": "rev_" + report_id[-8:], "report_id": report_id, "expert_name": expert_name,
              "guidance": guidance, "confirmed_issue": confirmed_issue, "created_at": now_iso()}
    REVIEWED[report_id] = review
    return ok({"report_id": report_id, "status": "expert_reviewed", "review": review}, 201)