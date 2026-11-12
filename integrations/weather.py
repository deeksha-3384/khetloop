"""Weather integration (P4): Open-Meteo forecast with last-result cache.

Contract: get_forecast(lat, lng) -> standard envelope. Never raises.
"""
import json
import logging
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from integrations.common import fail, ok, utc_now_iso
from shared.constants import COORD_DECIMALS

load_dotenv(override=True)  # contract C20

log = logging.getLogger(__name__)

API_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 8             # contract: 8 seconds per external call
FORECAST_HOURS = 48
RAIN_EXPECTED_MM = 1.0    # rain_expected is True when 48h total >= this (our choice)

_cache: dict = {}         # key "lat,lng" -> weather dict (no data_source)


def _cache_file() -> Path:
    return Path(os.getenv("TMP_DIR", "./tmp")) / "weather_cache.json"


def _key(lat: float, lng: float) -> str:
    return f"{lat:.{COORD_DECIMALS}f},{lng:.{COORD_DECIMALS}f}"


def _read_cached(key: str):
    if key in _cache:
        return _cache[key]
    try:
        with open(_cache_file(), encoding="utf-8") as f:
            return json.load(f).get(key)
    except Exception:
        return None


def _store(key: str, data: dict) -> None:
    _cache[key] = data
    try:
        path = _cache_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}
        existing[key] = data
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f)
    except Exception:
        pass  # cache write problems must never break a report


def _clean(values) -> list:
    return [v for v in (values or []) if isinstance(v, (int, float))]


def _parse(payload: dict) -> dict:
    hourly = payload["hourly"]
    rain = _clean(hourly.get("precipitation"))
    humidity = _clean(hourly.get("relative_humidity_2m"))
    temps = _clean(hourly.get("temperature_2m"))
    if not rain or not humidity or not temps:
        raise ValueError("incomplete forecast data")
    rain_total = round(sum(rain), 1)
    return {
        "fetched_at": utc_now_iso(),
        "rain_expected": rain_total >= RAIN_EXPECTED_MM,
        "rain_mm_next_48h": rain_total,
        "humidity_pct_avg": round(sum(humidity) / len(humidity)),
        "temp_c_avg": round(sum(temps) / len(temps), 1),
    }


def _fetch(lat: float, lng: float) -> dict:
    resp = requests.get(
        API_URL,
        params={
            "latitude": lat,
            "longitude": lng,
            "hourly": "temperature_2m,relative_humidity_2m,precipitation",
            "forecast_hours": FORECAST_HOURS,
            "timezone": "UTC",
        },
        timeout=TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()


def get_forecast(lat, lng) -> dict:
    try:
        lat = round(float(lat), COORD_DECIMALS)
        lng = round(float(lng), COORD_DECIMALS)
    except (TypeError, ValueError):
        return fail("WEATHER_UNAVAILABLE", "Invalid coordinates")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return fail("WEATHER_UNAVAILABLE", "Coordinates out of range")

    key = _key(lat, lng)
    try:
        data = _parse(_fetch(lat, lng))
    except Exception as exc:
        # Log only the error type: messages can contain the URL with coordinates.
        log.warning("Weather fetch failed: %s", type(exc).__name__)
        cached = _read_cached(key)
        if cached:
            return ok(cached, "cached")
        return fail("WEATHER_UNAVAILABLE", "Weather service unavailable")

    _store(key, data)
    return ok(data, "live")