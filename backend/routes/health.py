"""
GET /api/health  (endpoint 11). Reports whether the server is up and what is configured.
Never prints secret values. Extra service keys (groq, telegram, speech) are harmless for the frontend.
"""
from flask import Blueprint

from backend.config import Config
from backend.utils import deps
from backend.utils.responses import ok

bp = Blueprint("health", __name__)


@bp.get("/api/health")
def health():
    if Config.DB_MODE == "memory":
        database = "memory"
    elif not (Config.SUPABASE_URL and Config.SUPABASE_SERVICE_KEY):
        database = "not_configured"
    else:
        try:
            deps.get_db().list_farms()
            database = "ok"
        except Exception:
            database = "error"

    return ok({
        "status": "degraded" if database == "error" else "ok",
        "services": {
            "database": database,
            "gemini": "configured" if Config.GEMINI_API_KEY else "not_configured",
            "groq": "configured" if Config.GROQ_API_KEY else "not_configured",
            "telegram": "configured" if Config.TELEGRAM_BOT_TOKEN else "not_configured",
            "weather": "ok" if deps.get_integration("weather") else "not_available",
            "speech": "ok" if deps.get_integration("speech") else "not_available",
        },
    })