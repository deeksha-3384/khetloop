"""Endpoint 9: send due reminders (key)."""
from flask import Blueprint

from backend.utils.auth import require_expert_key
from backend.utils.responses import ok

bp = Blueprint("reminders", __name__)


@bp.post("/api/reminders/run")
@require_expert_key
def run_reminders():
    # MOCK: the real version calls integrations.reminders.run_due in Phase 9.
    return ok({"sent": 0, "failed": 0})