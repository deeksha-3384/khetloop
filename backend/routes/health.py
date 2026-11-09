"""
GET /api/health  (endpoint 11)
Reports whether the server is up and which services are configured.
Never prints secret values.
"""
from flask import Blueprint

from backend.config import Config
from backend.utils.responses import ok

bp = Blueprint("health", __name__)


@bp.get("/api/health")
def health():
    # Database: in memory mode there is nothing to connect to yet.
    if Config.DB_MODE == "memory":
        database = "memory"
    else:
        database = "configured" if (Config.SUPABASE_URL and Config.SUPABASE_SERVICE_KEY) else "not_configured"

    gemini = "configured" if Config.GEMINI_API_KEY else "not_configured"

    # Weather comes from P4's module. We will do a real check when it is integrated.
    weather = "not_checked"

    return ok({
        "status": "ok",
        "services": {
            "database": database,
            "gemini": gemini,
            "weather": weather,
        },
    })