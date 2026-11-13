"""Reminder integration (P4): schedule follow-ups and send the ones that are due.

Contract (signatures never change):
    schedule(report_id, hours, message=None) -> envelope, data = {"reminder_id", "due_at"}
    run_due(send_message)                    -> envelope, data = {"sent", "failed"}
send_message(chat_id, text) -> bool is supplied by the backend (Telegram).
All database work goes through P2's database.db_client. Never raises.
"""
import logging
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from integrations.common import fail, ok, utc_now_iso

load_dotenv(override=True)  # contract C20

log = logging.getLogger(__name__)

DEFAULT_MESSAGE = "Have the spots spread? Please send a new photo."
FOLLOW_UP_NOTE = "Follow-up reminder sent to the farmer"
MAX_HOURS = 24 * 365


def _db():
    """P2's database module, imported lazily so importing this file never fails."""
    from database import db_client
    return db_client


def schedule(report_id, hours, message=None) -> dict:
    try:
        if not isinstance(report_id, str) or not report_id.strip():
            return fail("INVALID_REQUEST", "report_id is required")
        if (isinstance(hours, bool) or not isinstance(hours, (int, float))
                or hours != hours or hours < 0 or hours > MAX_HOURS):
            return fail("INVALID_REQUEST", "hours must be a number between 0 and 8760")

        text = message.strip() if isinstance(message, str) and message.strip() else DEFAULT_MESSAGE
        due_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

        row = _db().insert_reminder(report_id.strip(), due_at, text)
        reminder_id = row.get("id") if isinstance(row, dict) else None
        if not reminder_id:
            return fail("DB_ERROR", "Could not save reminder")
        return ok({"reminder_id": reminder_id, "due_at": due_at}, "live")
    except Exception as exc:
        log.warning("Reminder schedule failed: %s", type(exc).__name__)
        return fail("DB_ERROR", "Could not schedule reminder")


def _deliver(db, item, send_message) -> bool:
    """Send one reminder. True only if the message was delivered."""
    if not isinstance(item, dict):
        return False
    reminder_id = item.get("id")
    report_id = item.get("report_id")
    chat_id = item.get("telegram_chat_id")
    if not reminder_id or not report_id:
        return False          # cannot be marked as sent afterwards, so do not send it
    if chat_id is None:
        return False          # e.g. a simulated farmer with no Telegram chat
    if not send_message(chat_id, item.get("message") or DEFAULT_MESSAGE):
        return False

    # The message is out. Bookkeeping problems below must not turn it into a failure.
    steps = (
        ("mark_sent", lambda: db.mark_reminder_sent(reminder_id)),
        ("event", lambda: db.add_report_event(report_id, "follow_up", "system", FOLLOW_UP_NOTE)),  # C9
        ("status", lambda: db.update_report_status(report_id, "follow_up")),                      # C9
    )
    for name, call in steps:
        try:
            call()
        except Exception as exc:
            log.warning("Reminder step %s failed: %s", name, type(exc).__name__)
    return True


def run_due(send_message) -> dict:
    if not callable(send_message):
        return fail("INVALID_REQUEST", "send_message must be a function")
    try:
        db = _db()
        due = db.due_reminders(utc_now_iso())
    except Exception as exc:
        log.warning("Loading due reminders failed: %s", type(exc).__name__)
        return fail("DB_ERROR", "Could not load due reminders")

    sent = failed = 0
    for item in due or []:
        try:
            if _deliver(db, item, send_message):
                sent += 1
            else:
                failed += 1
        except Exception as exc:
            failed += 1
            log.warning("Reminder delivery failed: %s", type(exc).__name__)
    return ok({"sent": sent, "failed": failed}, "live")