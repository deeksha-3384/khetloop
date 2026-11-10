"""X-Expert-Key check for expert and admin endpoints."""
import hmac
from functools import wraps

from flask import request

from backend.config import Config
from backend.utils.responses import err


def require_expert_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        given = request.headers.get("X-Expert-Key", "")
        if not hmac.compare_digest(given.encode("utf-8"), Config.EXPERT_API_KEY.encode("utf-8")):
            return err("UNAUTHORIZED", "Missing or invalid X-Expert-Key", 401)
        return fn(*args, **kwargs)
    return wrapper