"""Endpoints 5 and 6: expert queue and review. Both need X-Expert-Key."""
import logging

from flask import Blueprint, request

from backend.services import reply_writer
from backend.utils import deps
from backend.utils.auth import require_expert_key
from backend.utils.responses import err, ok
from shared.constants import FOLLOW_UP_HOURS, ISSUES, LANGUAGES, REPORT_STATUSES

log = logging.getLogger("khetloop.routes")
bp = Blueprint("expert", __name__)


@bp.get("/api/expert/cases")
@require_expert_key
def list_cases():
    status = request.args.get("status", "expert_review_pending")
    if status not in REPORT_STATUSES:
        return err("INVALID_REQUEST", "Unknown status", 400)
    cases = deps.get_db().list_expert_cases(status)
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

    db = deps.get_db()
    report = db.get_report(report_id)
    if report is None:
        return err("NOT_FOUND", "Report not found", 404)
    if report.get("expert_review") or report.get("status") == "expert_reviewed":
        return err("CONFLICT", "Report already reviewed", 409)

    review = db.insert_expert_review(report_id, expert_name, guidance, confirmed_issue)
    db.add_report_event(report_id, "expert_reviewed", "expert")
    db.update_report_status(report_id, "expert_reviewed")

    # Message the farmer in their language. A Telegram failure must not undo the review.
    reply_lang = (report.get("farmer_reply") or {}).get("language")
    farmer = db.get_farmer_for_farm(report.get("farm_id")) or {}
    lang = reply_lang if reply_lang in LANGUAGES else (farmer.get("language") if farmer.get("language") in LANGUAGES else "en")
    chat_id = farmer.get("telegram_chat_id")
    if chat_id:
        try:
            deps.send_telegram(chat_id, reply_writer.write_expert_message(guidance, lang))
        except Exception as e:
            log.warning("expert message failed: %s", type(e).__name__)

    # Schedule the follow-up reminder (also non-fatal).
    reminders = deps.get_integration("reminders")
    if reminders:
        try:
            reminders.schedule(report_id, FOLLOW_UP_HOURS, reply_writer.write_followup(lang))
        except Exception as e:
            log.warning("reminder scheduling failed: %s", type(e).__name__)

    return ok({"report_id": report_id, "status": "expert_reviewed", "review": review}, 201)