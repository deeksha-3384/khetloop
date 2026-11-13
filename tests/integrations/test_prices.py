import json
import re
from pathlib import Path

import pytest

from integrations import prices
from shared.constants import CROPS

ROOT = Path(__file__).resolve().parents[2]
FIELDS = {"crop", "market", "price_per_quintal_inr", "price_date", "note"}


def assert_envelope(env):
    assert set(env) == {"ok", "data", "data_source", "error"}
    if env["ok"]:
        assert env["data"] is not None and env["error"] is None
    else:
        assert env["data"] is None and env["data_source"] is None
        assert env["error"]["code"] and env["error"]["message"]


def write_cache(tmp_path, rows):
    path = tmp_path / "mandi_cache.json"
    path.write_text(json.dumps({"prices": rows}), encoding="utf-8")
    return path


def row(**over):
    base = {"crop": "tomato", "market": "Kolar", "price_per_quintal_inr": 1000,
            "min_price_per_quintal_inr": 300, "max_price_per_quintal_inr": 2000,
            "price_date": "2026-11-07", "source_name": "example.test"}
    base.update(over)
    return base


def test_known_market_returns_cached_envelope():
    env = prices.get_mandi("tomato", "Srinivasapur")
    assert_envelope(env)
    assert env["ok"] and env["data_source"] == "cached"      # never 'live'
    assert set(env["data"]) == FIELDS
    assert env["data"]["crop"] == "tomato" and env["data"]["market"] == "Srinivasapur"
    assert isinstance(env["data"]["price_per_quintal_inr"], (int, float))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", env["data"]["price_date"])
    assert "not a live price" in env["data"]["note"].lower()


@pytest.mark.parametrize("market", ["srinivasapur", "  SRINIVASAPUR ", "Srinivaspur", "srinivasapur  "])
def test_market_matching_ignores_case_spaces_and_spelling(market):
    env = prices.get_mandi("Tomato", market)
    assert env["ok"] and env["data"]["market"] == "Srinivasapur"


def test_unknown_market_fails_cleanly():
    env = prices.get_mandi("tomato", "Atlantis")
    assert_envelope(env)
    assert not env["ok"] and env["error"]["code"] == "NOT_FOUND"


def test_crop_with_no_cached_price_fails_cleanly():
    env = prices.get_mandi("chilli", "Kolar")
    assert_envelope(env)
    assert not env["ok"] and env["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("crop,market", [("", ""), (None, "Kolar"), ("tomato", None), ("tomato", "   "),
                                         (123, 456), ("banana", "Kolar"), (["tomato"], {"a": 1})])
def test_bad_input_never_raises(crop, market):
    env = prices.get_mandi(crop, market)
    assert_envelope(env)
    assert not env["ok"] and env["error"]["code"] == "INVALID_REQUEST"


def test_missing_cache_file(monkeypatch, tmp_path):
    monkeypatch.setattr(prices, "CACHE_FILE", tmp_path / "nope.json")
    env = prices.get_mandi("tomato", "Kolar")
    assert_envelope(env)
    assert not env["ok"] and env["error"]["code"] == "INTERNAL_ERROR"


def test_corrupt_cache_file(monkeypatch, tmp_path):
    bad = tmp_path / "mandi_cache.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(prices, "CACHE_FILE", bad)
    env = prices.get_mandi("tomato", "Kolar")
    assert_envelope(env)
    assert not env["ok"] and env["error"]["code"] == "INTERNAL_ERROR"


def test_row_missing_a_field_does_not_crash(monkeypatch, tmp_path):
    bad_row = row()
    del bad_row["source_name"]
    monkeypatch.setattr(prices, "CACHE_FILE", write_cache(tmp_path, [bad_row]))
    env = prices.get_mandi("tomato", "Kolar")
    assert_envelope(env)
    assert not env["ok"]


def test_newest_entry_wins(monkeypatch, tmp_path):
    rows = [row(price_per_quintal_inr=900, price_date="2026-11-01"),
            row(price_per_quintal_inr=1100, price_date="2026-11-09")]
    monkeypatch.setattr(prices, "CACHE_FILE", write_cache(tmp_path, rows))
    env = prices.get_mandi("tomato", "Kolar")
    assert env["data"]["price_per_quintal_inr"] == 1100 and env["data"]["price_date"] == "2026-11-09"


def test_shipped_cache_file_is_sane():
    with open(ROOT / "data" / "mandi_cache.json", encoding="utf-8") as f:
        cache = json.load(f)
    retrieved = cache["retrieved_on"]
    seen = set()
    assert cache["prices"]
    for r in cache["prices"]:
        assert r["crop"] in CROPS
        assert r["market"].strip() and r["source_name"].strip() and r["source_url"].startswith("https://")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["price_date"]) and r["price_date"] <= retrieved
        lo, mid, hi = (r["min_price_per_quintal_inr"], r["price_per_quintal_inr"], r["max_price_per_quintal_inr"])
        assert 0 < lo <= mid <= hi, r
        key = (r["crop"], r["market"].lower(), r["price_date"])
        assert key not in seen
        seen.add(key)
    blob = json.dumps(cache).lower()
    assert "outbreak" not in blob and '"live"' not in blob