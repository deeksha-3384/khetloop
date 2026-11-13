"""Mandi price integration (P4): reads cached prices from data/mandi_cache.json.

Contract (signature never changes):
    get_mandi(crop, market) -> envelope
        data = {"crop", "market", "price_per_quintal_inr", "price_date", "note"}
        data_source is always "cached": there is no live feed, and a cached price is
        never labelled live. ok=False if the crop/market is not in the cache.
Synchronous, never raises.
"""
import json
import logging
import re
from pathlib import Path

from integrations.common import fail, ok
from shared.constants import CROPS

log = logging.getLogger(__name__)

CACHE_FILE = Path(__file__).resolve().parents[1] / "data" / "mandi_cache.json"

# Different websites spell the same market differently.
ALIASES = {"srinivaspur": "srinivasapur", "srinivaspura": "srinivasapur",
           "bangarapet": "bangarpet", "bangarpete": "bangarpet"}


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def _market_key(text) -> str:
    key = _norm(text)
    return ALIASES.get(key, key)


def _load_rows() -> list:
    with open(CACHE_FILE, encoding="utf-8") as f:
        rows = json.load(f)["prices"]
    if not isinstance(rows, list):
        raise ValueError("prices must be a list")
    return rows


def get_mandi(crop, market) -> dict:
    try:
        if not isinstance(crop, str) or not crop.strip() or not isinstance(market, str) or not market.strip():
            return fail("INVALID_REQUEST", "crop and market are required")
        crop_key = _norm(crop)
        if crop_key not in CROPS:
            return fail("INVALID_REQUEST", "Unknown crop")

        rows = _load_rows()
        wanted = _market_key(market)
        matches = [r for r in rows
                   if _norm(r["crop"]) == crop_key and _market_key(r["market"]) == wanted]
        if not matches:
            return fail("NOT_FOUND", "No cached price for this crop and market")

        row = max(matches, key=lambda r: r["price_date"])   # newest entry wins
        note = (f"Modal price (min {row['min_price_per_quintal_inr']}, "
                f"max {row['max_price_per_quintal_inr']}) from a cached copy of "
                f"{row['source_name']}. Not a live price; please verify at your market.")
        return ok({
            "crop": crop_key,
            "market": row["market"],
            "price_per_quintal_inr": row["price_per_quintal_inr"],
            "price_date": row["price_date"],
            "note": note,
        }, "cached")
    except Exception as exc:
        log.warning("Mandi price lookup failed: %s", type(exc).__name__)
        return fail("INTERNAL_ERROR", "Mandi price data unavailable")