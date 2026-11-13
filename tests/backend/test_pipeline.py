import base64
from types import SimpleNamespace

import pytest

from backend.services import report_pipeline as rp
from tests.backend.fake_db import FakeDB

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def vision(issue="early_blight", band="medium", quality="good", symptoms=("brown spots",)):
    a = {"suspected_issue": issue, "confidence_band": band, "image_quality": quality,
         "visible_symptoms": list(symptoms), "confirmed": False}
    return SimpleNamespace(analyse_leaf=lambda image, crop, transcript: {"ok": True, "provider": "stub", "assessment": a})


VISION_DOWN = SimpleNamespace(analyse_leaf=lambda *a: {"ok": False, "error": {"code": "AI_UNAVAILABLE", "message": "x"}})
VISION_CRASH = SimpleNamespace(analyse_leaf=lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
VISION_INVALID = SimpleNamespace(analyse_leaf=lambda *a: {"ok": False, "error": {"code": "INVALID_REQUEST", "message": "Not a supported image"}})

WEATHER_OK = SimpleNamespace(get_forecast=lambda lat, lng: {
    "ok": True, "data_source": "live", "error": None,
    "data": {"rain_expected": True, "rain_mm_next_48h": 12.4, "humidity_pct_avg": 82, "temp_c_avg": 24.5,
             "fetched_at": "2026-11-12T09:14:00Z"}})
WEATHER_DOWN = SimpleNamespace(get_forecast=lambda lat, lng: {
    "ok": False, "data": None, "data_source": None, "error": {"code": "WEATHER_UNAVAILABLE", "message": "x"}})


def speech(stt_text="my leaves have spots", stt_ok=True, tts_ok=True):
    return SimpleNamespace(
        stt=lambda path, lang: {"ok": True, "data": {"text": stt_text, "language": lang}, "data_source": "live", "error": None}
        if stt_ok else {"ok": False, "data": None, "data_source": None, "error": {"code": "STT_FAILED", "message": "x"}},
        tts=lambda text, lang, out_path=None: {"ok": True, "data": {"audio_path": "tmp/reply.mp3"}, "data_source": "live", "error": None}
        if tts_ok else {"ok": False, "data": None, "data_source": None, "error": {"code": "INTERNAL_ERROR", "message": "x"}})


class Reminders:
    def __init__(self, ok=True):
        self.calls, self.ok = [], ok

    def schedule(self, report_id, hours, message=None):
        self.calls.append((report_id, hours, message))
        return {"ok": self.ok, "data": {"reminder_id": "rem_1", "due_at": "x"}, "data_source": "live", "error": None}


@pytest.fixture
def db():
    d = FakeDB()
    d.add_farm()
    return d


def run(db, **kw):
    deps = SimpleNamespace(db=db, vision=kw.pop("vision", vision()), weather=kw.pop("weather", WEATHER_OK),
                           speech=kw.pop("speech", speech()), reminders=kw.pop("reminders", Reminders()),
                           send_message=kw.pop("send_message", None))
    args = dict(farm_id="farm_main", image_bytes=PNG, image_filename="leaf.png")
    args.update(kw)
    return rp.run_pipeline(deps=deps, **args)


def statuses(db, report_id):
    return [e["status"] for e in db.events[report_id]]


# ------------------------------------------------------------------ the three outcomes
def test_clear_photo_gives_preliminary_assessment(db):
    res = run(db, vision=vision(band="high"))
    r = res["report"]
    assert r["decision"] == "preliminary_assessment" and r["status"] == "ai_assessed"
    assert statuses(db, r["id"]) == ["submitted", "ai_assessed"]
    assert r["farmer_reply"]["text"] and r["farmer_reply"]["language"] == "kn"
    assert r["assessment"]["confirmed"] is False
    assert res["degraded"] == []


def test_blurry_first_try_abstains_and_schedules_no_reminder(db):
    rem = Reminders()
    res = run(db, vision=vision(issue="unknown", band="low", quality="poor"), reminders=rem)
    r = res["report"]
    assert r["decision"] == "abstain_request_better_image" and r["status"] == "ai_assessed"
    assert statuses(db, r["id"]) == ["submitted", "ai_assessed"]
    assert rem.calls == [] and r["risk"] is None


def test_blurry_again_after_retry_escalates(db):
    db.abstains = 1
    r = run(db, vision=vision(issue="unknown", band="low", quality="poor"))["report"]
    assert r["decision"] == "escalate_to_expert" and r["status"] == "expert_review_pending"
    assert r["escalation_reason"] == "UNCLEAR_AFTER_RETRY"
    assert statuses(db, r["id"]) == ["submitted", "ai_assessed", "expert_review_pending"]


def test_low_confidence_never_gives_preliminary(db):
    r = run(db, vision=vision(band="low"))["report"]
    assert r["decision"] != "preliminary_assessment"


def test_severity_word_in_the_transcript_escalates(db):
    r = run(db, voice_text="it is spreading fast", audio_path=None, vision=vision(band="high"))["report"]
    assert r["decision"] == "escalate_to_expert" and r["escalation_reason"] == "SEVERITY_KEYWORD"


# ------------------------------------------------------------------ graceful failure
def test_ai_down_still_saves_and_escalates(db):
    res = run(db, vision=VISION_DOWN)
    r = res["report"]
    assert r["decision"] == "escalate_to_expert" and r["escalation_reason"] == "AI_UNAVAILABLE"
    assert statuses(db, r["id"]) == ["submitted", "expert_review_pending"]  # AI never assessed it
    assert any("not available" in w["text"] for w in r["why"])
    assert "vision" in res["degraded"] and r["farmer_reply"]["text"]


def test_vision_that_crashes_is_treated_as_down(db):
    r = run(db, vision=VISION_CRASH)["report"]
    assert r["escalation_reason"] == "AI_UNAVAILABLE"


def test_weather_down_saves_null_weather_and_no_weather_line(db):
    res = run(db, weather=WEATHER_DOWN)
    r = res["report"]
    assert r["weather"] is None
    assert "WEATHER_CONTEXT" not in [w["code"] for w in r["why"]]
    assert "weather" in res["degraded"]


def test_weather_ok_is_stored_with_its_data_source(db):
    r = run(db)["report"]
    assert r["weather"]["data_source"] == "live" and r["weather"]["rain_expected"] is True
    assert "WEATHER_CONTEXT" in [w["code"] for w in r["why"]]


def test_farm_without_coordinates_skips_weather_and_clusters(db):
    db.add_farm("farm_nocoords", lat=None, lng=None)
    res = run(db, farm_id="farm_nocoords")
    assert res["report"]["weather"] is None and res["cluster"] is None


def test_tts_failure_still_returns_the_text_reply(db):
    res = run(db, speech=speech(tts_ok=False))
    assert res["audio_path"] is None and res["report"]["farmer_reply"]["text"]
    assert "tts" in res["degraded"]


def test_tts_success_returns_the_audio_path(db):
    assert run(db)["audio_path"] == "tmp/reply.mp3"


def test_missing_integration_modules_do_not_break_the_report(db):
    deps = SimpleNamespace(db=db, vision=vision(), weather=None, speech=None, reminders=None, send_message=None)
    res = rp.run_pipeline("farm_main", PNG, "leaf.png", deps=deps)
    assert res["report"]["id"] and res["audio_path"] is None


def test_reminder_failure_is_recorded_not_raised(db):
    assert "reminder" in run(db, reminders=Reminders(ok=False))["degraded"]


# ------------------------------------------------------------------ speech input
def test_stt_text_becomes_the_transcript(db):
    r = run(db, audio_path="x.oga", speech=speech(stt_text="spots on my tomato"))["report"]
    assert r["voice_transcript"] == "spots on my tomato" and r["voice_language"] == "kn"


def test_stt_failure_falls_back_to_typed_text(db):
    res = run(db, audio_path="x.oga", voice_text="typed words", speech=speech(stt_ok=False))
    assert res["report"]["voice_transcript"] == "typed words" and "stt" in res["degraded"]


def test_no_voice_at_all_stores_no_transcript(db):
    r = run(db)["report"]
    assert r["voice_transcript"] is None and r["voice_language"] is None


def test_language_argument_overrides_the_farmers_language(db):
    assert run(db, language="hi")["report"]["farmer_reply"]["language"] == "hi"
    assert run(db, language="xx")["report"]["farmer_reply"]["language"] == "kn"


# ------------------------------------------------------------------ errors the route must handle
def test_unknown_farm_raises_lookup_error(db):
    with pytest.raises(LookupError):
        run(db, farm_id="farm_nope")


def test_non_image_raises_value_error_and_stores_nothing(db):
    with pytest.raises(ValueError):
        run(db, vision=VISION_INVALID)
    assert db.reports == {} and db.images == []


def test_missing_database_module_raises_runtime_error():
    with pytest.raises(RuntimeError):
        rp.run_pipeline("farm_main", PNG, "leaf.png", deps=SimpleNamespace(db=None))


# ------------------------------------------------------------------ rules inside the pipeline
def test_process_report_returns_the_report_dict(db):
    deps = SimpleNamespace(db=db, vision=vision(), weather=WEATHER_OK, speech=speech(), reminders=Reminders(), send_message=None)
    r = rp.process_report("farm_main", PNG, "leaf.png", deps=deps)
    assert r["id"].startswith("rep_") and "events" in r


def test_nearby_reports_add_why_line_and_raise_risk(db):
    db.add_farm("farm_b")
    db.add_farm("farm_c")
    db.add_similar_report("farm_b")
    db.add_similar_report("farm_c")
    r = run(db)["report"]
    assert "NEARBY_REPORTS" in [w["code"] for w in r["why"]]
    assert r["risk"]["level"] == "elevated" and "Similar reports nearby" in r["risk"]["reasons"]


def test_history_adds_a_farm_history_line(db):
    db.add_similar_report("farm_main", issue="leaf_curl")
    assert "FARM_HISTORY" in [w["code"] for w in run(db)["report"]["why"]]


def test_simulated_farm_makes_a_simulated_report(db):
    db.add_farm("farm_sim", data_source="simulated")
    assert run(db, farm_id="farm_sim")["report"]["data_source"] == "simulated"


def test_followup_reminder_is_scheduled_48_hours_out(db):
    rem = Reminders()
    r = run(db, reminders=rem)["report"]
    assert rem.calls[0][0] == r["id"] and rem.calls[0][1] == 48 and rem.calls[0][2]


def test_no_output_ever_says_outbreak(db):
    for kwargs in ({}, {"vision": VISION_DOWN}, {"vision": vision(issue="unknown", band="low", quality="poor")}):
        r = run(db, **kwargs)["report"]
        blob = (r["farmer_reply"]["text"] + " ".join(w["text"] for w in r["why"])).lower()
        assert "outbreak" not in blob


# ------------------------------------------------------------------ cluster and alerts
def make_neighbourhood(db, with_chat=True):
    for i, fid in enumerate(("farm_b", "farm_c")):
        db.add_farm(fid, chat_id=200 + i if with_chat else None, language="hi" if i else "kn")
        db.add_similar_report(fid)


def test_three_farms_create_a_cluster_and_alerts_are_sent_once(db):
    make_neighbourhood(db)
    sent = []
    res = run(db, send_message=lambda chat, text: sent.append((chat, text)) or True)
    assert res["cluster"]["created"] is True and res["cluster"]["cluster"]["label"] == "potential_cluster"
    assert res["alerts_sent"] == 3 and len(sent) == 3
    assert all("outbreak" not in text.lower() for _, text in sent)
    # a second report in the same area must not re-alert the same farms
    sent.clear()
    res2 = run(db, send_message=lambda chat, text: sent.append((chat, text)) or True)
    assert res2["cluster"]["created"] is False and sent == []


def test_alerts_use_each_farms_language(db):
    make_neighbourhood(db)
    sent = {}
    run(db, send_message=lambda chat, text: sent.update({chat: text}) or True)
    assert sent[200] != sent[201]  # kn vs hi


def test_alert_failure_is_recorded_but_does_not_break_the_report(db):
    make_neighbourhood(db)

    def broken(chat, text):
        raise RuntimeError("telegram down")

    res = run(db, send_message=broken)
    assert res["report"]["id"] and res["alerts_sent"] == 0
    assert all(a["delivered"] is False for a in db.alerts)


def test_farms_without_telegram_still_get_an_undelivered_alert_record(db):
    make_neighbourhood(db, with_chat=False)
    db.farmers["farm_main"]["telegram_chat_id"] = None
    res = run(db, send_message=lambda chat, text: True)
    assert res["alerts_sent"] == 0 and len(db.alerts) == 3


def test_two_farms_make_no_cluster(db):
    db.add_farm("farm_b")
    db.add_similar_report("farm_b")
    assert run(db)["cluster"] is None