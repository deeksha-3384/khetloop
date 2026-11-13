"""
Loads .env into one Config class. Variable names match section 5 of the plan.
Everyone in the backend imports:  from backend.config import Config
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)


def _get_int(name: str, default: int) -> int:
    """Read an integer env var; fall back to the default if missing or invalid."""
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _get_db_mode() -> str:
    mode = os.getenv("DB_MODE", "memory").strip().lower()
    return mode if mode in ("supabase", "memory") else "memory"


def _get_tmp_dir() -> str:
    raw = os.getenv("TMP_DIR", "./tmp")
    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


class Config:
    # Database (P2)
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
    SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "report-images")
    DB_MODE = _get_db_mode()

    # AI
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "")

    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # App
    EXPERT_API_KEY = os.getenv("EXPERT_API_KEY", "demo-expert-key")
    API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:5000")
    APP_PORT = _get_int("APP_PORT", 5000)

    # Integrations (P4)
    SPEECH_PROVIDER = os.getenv("SPEECH_PROVIDER", "groq_gtts")
    TMP_DIR = _get_tmp_dir()

    @classmethod
    def summary(cls) -> dict:
        """Safe-to-print overview. Shows True/False for secrets, never the values."""
        return {
            "DB_MODE": cls.DB_MODE,
            "APP_PORT": cls.APP_PORT,
            "GEMINI_MODEL": cls.GEMINI_MODEL,
            "TMP_DIR": cls.TMP_DIR,
            "supabase_configured": bool(cls.SUPABASE_URL and cls.SUPABASE_SERVICE_KEY),
            "gemini_configured": bool(cls.GEMINI_API_KEY),
            "groq_configured": bool(cls.GROQ_API_KEY),
            "telegram_configured": bool(cls.TELEGRAM_BOT_TOKEN),
        }