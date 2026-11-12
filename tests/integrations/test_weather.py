import pytest
import requests

from integrations import weather


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError("bad status")

    def json(self):
        return self._payload


def make_payload(rain_per_hour=0.25):
    return {"hourly": {
        "time": [f"t{i}" for i in range(48)],
        "temperature_2m": [24.0] * 24 + [25.0] * 24,
        "relative_humidity_2m": [80] * 24 + [84] * 24,
        "precipitation": [rain_per_hour] * 48,
    }}


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path, monkeypatch):
    weather._cache.clear()
    monkeypatch.setattr(weather, "_cache_file", lambda: tmp_path / "weather_cache.json")


def test_success_live(monkeypatch):
    monkeypatch.setattr(weather.requests, "get", lambda *a, **k: FakeResponse(make_payload()))
    r = weather.get_forecast(13.14, 78.13)
    assert r["ok"] is True and r["data_source"] == "live" and r["error"] is None
    d = r["data"]
    assert d["rain_mm_next_48h"] == 12.0
    assert d["rain_expected"] is True
    assert d["humidity_pct_avg"] == 82
    assert d["temp_c_avg"] == 24.5
    assert set(d) == {"fetched_at", "rain_expected", "rain_mm_next_48h",
                      "humidity_pct_avg", "temp_c_avg"}


def test_no_rain(monkeypatch):
    monkeypatch.setattr(weather.requests, "get",
                        lambda *a, **k: FakeResponse(make_payload(rain_per_hour=0.0)))
    d = weather.get_forecast(13.14, 78.13)["data"]
    assert d["rain_expected"] is False and d["rain_mm_next_48h"] == 0.0


def test_timeout_without_cache(monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.Timeout("slow")
    monkeypatch.setattr(weather.requests, "get", boom)
    r = weather.get_forecast(13.14, 78.13)
    assert r["ok"] is False and r["data"] is None and r["data_source"] is None
    assert r["error"]["code"] == "WEATHER_UNAVAILABLE"


def test_cached_fallback_after_failure(monkeypatch):
    monkeypatch.setattr(weather.requests, "get", lambda *a, **k: FakeResponse(make_payload()))
    live = weather.get_forecast(13.14, 78.13)

    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("down")
    monkeypatch.setattr(weather.requests, "get", boom)
    r = weather.get_forecast(13.14, 78.13)
    assert r["ok"] is True and r["data_source"] == "cached"
    assert r["data"] == live["data"]


def test_cache_survives_restart_via_file(monkeypatch):
    monkeypatch.setattr(weather.requests, "get", lambda *a, **k: FakeResponse(make_payload()))
    weather.get_forecast(13.14, 78.13)
    weather._cache.clear()  # simulate a restart

    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("down")
    monkeypatch.setattr(weather.requests, "get", boom)
    assert weather.get_forecast(13.14, 78.13)["data_source"] == "cached"


def test_cache_is_per_location(monkeypatch):
    monkeypatch.setattr(weather.requests, "get", lambda *a, **k: FakeResponse(make_payload()))
    weather.get_forecast(13.14, 78.13)

    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("down")
    monkeypatch.setattr(weather.requests, "get", boom)
    assert weather.get_forecast(26.91, 75.79)["ok"] is False


def test_bad_json_and_http_error(monkeypatch):
    monkeypatch.setattr(weather.requests, "get",
                        lambda *a, **k: FakeResponse({"unexpected": 1}))
    assert weather.get_forecast(13.14, 78.13)["ok"] is False
    monkeypatch.setattr(weather.requests, "get",
                        lambda *a, **k: FakeResponse({}, status=500))
    assert weather.get_forecast(13.14, 78.13)["ok"] is False


@pytest.mark.parametrize("lat,lng", [(None, 78), ("abc", 78), (91, 78), (13, 181),
                                     (float("nan"), 78)])
def test_invalid_coordinates(lat, lng):
    r = weather.get_forecast(lat, lng)
    assert r["ok"] is False and r["error"]["code"] == "WEATHER_UNAVAILABLE"