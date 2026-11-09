"""
Standard response envelopes (section 6 of the plan).
Success: {"ok": true, "data": {...}}
Error:   {"ok": false, "error": {"code": "NOT_FOUND", "message": "..."}}
Every route returns ok(...) or err(...), nothing else.
"""
from flask import jsonify

from shared.constants import ERROR_CODES


def ok(data, status: int = 200):
    """Build a success response. `data` must be JSON-serialisable."""
    return jsonify({"ok": True, "data": data}), status


def err(code: str, message: str, status: int):
    """Build an error response. `code` must be one of shared.constants.ERROR_CODES."""
    if code not in ERROR_CODES:
        code = "INTERNAL_ERROR"
    return jsonify({"ok": False, "error": {"code": code, "message": message}}), status