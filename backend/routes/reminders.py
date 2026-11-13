"""Endpoint 9: send due reminders (key). Uses P4's integrations.reminders.run_due."""
import logging

from flask import Blueprint

from backend.utils import deps
from backend.utils.auth import require_expert_key
from backend.utils.responses import err, ok

log = logging.getLogger("khetloop.routes")
bp = Blueprint("reminders", __name__)


@bp.post("/api/reminders/run")
@require_expert_key
def run_reminders():
    reminders = deps.get_integration("reminders")
    if reminders is None:
        return err("INTERNAL_ERROR", "The reminders module is not available", 500)
    try:
        result = reminders.run_due(deps.send_telegram)
    except Exception as e:
        log.warning("run_due failed: %s", type(e).__name__)
        return err("INTERNAL_ERROR", "Could not run reminders", 500)
    if not result or not result.get("ok"):
        return err("INTERNAL_ERROR", "Could not run reminders", 500)
    return ok(result["data"])