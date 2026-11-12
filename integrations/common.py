"""Shared helpers for all integration modules (P4)."""
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ok(data: dict, data_source: str) -> dict:
    return {"ok": True, "data": data, "data_source": data_source, "error": None}


def fail(code: str, message: str) -> dict:
    return {
        "ok": False,
        "data": None,
        "data_source": None,
        "error": {"code": code, "message": message},
    }