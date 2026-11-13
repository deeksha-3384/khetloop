"""
The one place where routes get their collaborators (database, integrations, Telegram).
Routes always call these through the module (deps.get_db()), so tests can replace them.
"""
import importlib
import logging
from types import SimpleNamespace

log = logging.getLogger("khetloop.deps")


def get_db():
    """P2's database module (database/db_client.py)."""
    from database import db_client
    return db_client


def get_integration(name: str):
    """P4's module 'weather', 'speech' or 'reminders'. None if it is not available."""
    try:
        return importlib.import_module("integrations." + name)
    except ImportError:
        log.warning("integration %s is not available", name)
        return None


def send_telegram(chat_id, text) -> bool:
    from backend.bot.bot import send_text
    return send_text(chat_id, text)


def pipeline_deps():
    """What the report pipeline should use. Only the database and Telegram are overridden here;
    vision, weather, speech and reminders fall back to the real modules inside the pipeline."""
    return SimpleNamespace(db=get_db(), send_message=send_telegram)