"""Self-test for all integration modules (P4). Run from the repo root, venv active:

    python -m integrations.selftest           # offline checks only (no internet needed)
    python -m integrations.selftest --live    # also calls Open-Meteo, Groq and Google TTS

Prints PASS / FAIL / SKIP per check. Exit code 0 = no FAIL, 1 = at least one FAIL.
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)  # contract C20

from integrations import prices, reminders, speech, weather  # noqa: E402

KOLAR = (13.14, 78.13)
SAMPLE_AUDIO = Path("tmp") / "stt_samples" / "kn_1.ogg"
OUT_DIR = Path("tmp") / "selftest"
ENVELOPE_KEYS = {"ok", "data", "data_source", "error"}

results = []


def report(name, status, detail=""):
    results.append(status)
    suffix = f" - {detail}" if detail else ""
    print(f"[{status}] {name}{suffix}")


def run(name, fn):
    """Run one check. A check returns (status, detail). An exception counts as FAIL."""
    try:
        status, detail = fn()
    except Exception as exc:
        status, detail = "FAIL", f"unexpected {type(exc).__name__}"
    report(name, status, detail)


def ensure(condition, detail_if_bad="unexpected result"):
    return ("PASS", "") if condition else ("FAIL", detail_if_bad)


def is_failure(r, code=None):
    if set(r) != ENVELOPE_KEYS or r["ok"] is not False or r["data"] is not None:
        return False
    return code is None or (r["error"] or {}).get("code") == code


# ---------- offline checks ----------
def weather_bad_input():
    r = weather.get_forecast(None, None)
    return ensure(is_failure(r, "WEATHER_UNAVAILABLE"), str(r))


def prices_tomato_cached():
    r = prices.get_mandi("tomato", "Kolar")
    good = (r.get("ok") is True and r.get("data_source") == "cached"
            and isinstance(r.get("data"), dict)
            and r["data"].get("price_per_quintal_inr") is not None)
    return ensure(good, str(r))


def prices_unknown_crop():
    r = prices.get_mandi("chilli", "Kolar")
    return ensure(is_failure(r), str(r))


def stt_missing_file():
    r = speech.stt("does_not_exist.ogg", "kn")
    return ensure(is_failure(r, "STT_FAILED"), str(r))


def stt_bad_language():
    r = speech.stt("does_not_exist.ogg", "fr")
    return ensure(is_failure(r, "STT_FAILED"), str(r))


def tts_empty_text():
    r = speech.tts("", "kn")
    return ensure(is_failure(r), str(r))


def reminders_bad_report_id():
    r = reminders.schedule("", 1)
    return ensure(is_failure(r, "INVALID_REQUEST"), str(r))


def reminders_bad_callback():
    r = reminders.run_due("not a function")
    return ensure(is_failure(r, "INVALID_REQUEST"), str(r))


# ---------- live checks (need internet, and keys in .env) ----------
def live_weather():
    r = weather.get_forecast(*KOLAR)
    good = r.get("ok") is True and r.get("data_source") in ("live", "cached")
    if not good:
        return ensure(False, str(r))
    return "PASS", f"source={r['data_source']}"


def live_stt():
    if not SAMPLE_AUDIO.is_file():
        return "SKIP", f"no sample at {SAMPLE_AUDIO}"
    r = speech.stt(str(SAMPLE_AUDIO), "kn")
    good = r.get("ok") is True and bool((r.get("data") or {}).get("text", "").strip())
    if not good:
        return ensure(False, str(r))
    return "PASS", r["data"]["text"]


def live_tts():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / "selftest_kn.mp3"
    r = speech.tts("ನಮಸ್ಕಾರ", "kn", out_path=str(target))
    good = r.get("ok") is True and target.is_file() and target.stat().st_size > 0
    return ensure(good, str(r))


def main():
    live = "--live" in sys.argv
    print("== offline checks ==")
    run("weather: bad coordinates give a clean failure", weather_bad_input)
    run("prices: tomato in Kolar is cached", prices_tomato_cached)
    run("prices: unknown crop is a clean failure", prices_unknown_crop)
    run("speech: missing file gives STT_FAILED", stt_missing_file)
    run("speech: unsupported language rejected", stt_bad_language)
    run("speech: empty text TTS is a clean failure", tts_empty_text)
    run("reminders: empty report_id rejected", reminders_bad_report_id)
    run("reminders: non-callable send_message rejected", reminders_bad_callback)

    if live:
        print("== live checks ==")
        run("weather: live forecast for Kolar", live_weather)
        run("speech: Kannada STT on sample audio", live_stt)
        run("speech: gTTS writes an mp3", live_tts)
    else:
        print("(live checks skipped; run with --live)")

    passed, failed, skipped = results.count("PASS"), results.count("FAIL"), results.count("SKIP")
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())