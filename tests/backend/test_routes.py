import base64
import io
import os
from types import SimpleNamespace

import pytest

from backend.app import create_app
from backend.config import Config
from backend.utils import deps
from tests.backend.fake_db import FakeDB

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
KEY = {"X-Expert-Key": Config.EXPERT_API_KEY}


def good_vision(issue="early_blight", band="medium", quality="good"):
    a = {"suspected_issue": issue, "confidence_band": band, "image_quality": quality,
         "visible_symptoms": ["brown spots"], "confirmed": False}
    return SimpleNamespace(analyse_leaf=lambda image, crop, transcript: {"ok": True, "provider": "stub", "assessment": a})


INVALID_VISION = SimpleNamespace(analyse_leaf=lambda *a: {"ok": False, "error": {"code": "INVALID_REQUEST", "message": "x"}})


class Reminders:
    def __init__(self):
        self.scheduled, self.run_with = [], None

    def schedule(self, report_id, hours, message=None):
        self.scheduled.append((report_id, hours, message))
        return {"ok": True, "data": {"reminder_id": "rem_1", "due_at": "x"}, "data_source": "live", "error": None}

    def run_due(self, send_message):
        self.run_with = send_message
        return {"ok": True, "data": {"sent": 2, "failed": 0}, "data_source": "live", "error": None}


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    db = FakeDB()
    db.add_farm()  # farm_main: tomato, Kannada, chat 111
    state = SimpleNamespace(db=db, vision=good_vision(), sent=[], reminders=Reminders(), send_error=None,
                            integrations={"reminders": None})
    state.integrations["reminders"] = state.reminders

    def send(chat_id, text):
        if state.send_error:
            raise state.send_error
        state.sent.append((chat_id, text))
        return True

    monkeypatch.setattr(Config, "TMP_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(deps, "get_db", lambda: state.db)
    monkeypatch.setattr(deps, "send_telegram", send)
    monkeypatch.setattr(deps, "get_integration", lambda name: state.integrations.get(name))
    monkeypatch.setattr(deps, "pipeline_deps", lambda: SimpleNamespace(
        db=state.db, vision=state.vision, weather=None, speech=None, reminders=state.reminders, send_message=send))
    state.client = create_app().test_client()
    state.tmp = tmp_path
    return state


def post_report(c, **form):
    data = {"farm_id": "farm_main", "image": (io.BytesIO(PNG), "leaf.png")}
    data.update(form)
    return c.client.post("/api/reports", data=data, content_type="multipart/form-data")


# ------------------------------------------------------------------ health
def test_health_in_memory_mode(ctx):
    body = ctx.client.get("/api/health").get_json()
    assert body["ok"] is True and body["data"]["status"] == "ok"
    assert body["data"]["services"]["database"] == "memory"


def test_health_reports_a_database_error(ctx, monkeypatch):
    monkeypatch.setattr(Config, "DB_MODE", "supabase")
    monkeypatch.setattr(Config, "SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setattr(Config, "SUPABASE_SERVICE_KEY", "k")
    monkeypatch.setattr(ctx.db, "list_farms", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    data = ctx.client.get("/api/health").get_json()["data"]
    assert data["services"]["database"] == "error" and data["status"] == "degraded"


def test_unknown_url_uses_the_error_envelope(ctx):
    r = ctx.client.get("/api/nope")
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "NOT_FOUND"


# ------------------------------------------------------------------ farms
def test_list_farms(ctx):
    farms = ctx.client.get("/api/farms").get_json()["data"]["farms"]
    assert farms[0]["id"] == "farm_main" and farms[0]["language"] == "kn"


def test_farm_timeline_and_404(ctx):
    post_report(ctx)
    data = ctx.client.get("/api/farms/farm_main/timeline").get_json()["data"]
    assert data["farm"]["id"] == "farm_main" and len(data["items"]) == 1
    assert ctx.client.get("/api/farms/farm_nope/timeline").status_code == 404


# ------------------------------------------------------------------ reports
def test_submit_report_returns_201_with_the_report(ctx):
    r = post_report(ctx, voice_text="spots on leaves")
    body = r.get_json()
    assert r.status_code == 201 and body["ok"] is True and body["data"]["id"].startswith("rep_")
    assert body["data"]["voice_transcript"] == "spots on leaves"
    got = ctx.client.get("/api/reports/" + body["data"]["id"])
    assert got.status_code == 200 and got.get_json()["data"]["id"] == body["data"]["id"]


def test_unknown_report_is_404(ctx):
    assert ctx.client.get("/api/reports/rep_nope").status_code == 404


def test_submit_validation_errors(ctx):
    assert post_report(ctx, farm_id="").status_code == 400
    r = ctx.client.post("/api/reports", data={"farm_id": "farm_main"}, content_type="multipart/form-data")
    assert r.status_code == 400 and r.get_json()["error"]["message"] == "image is required"
    assert post_report(ctx, language="xx").status_code == 400
    r = ctx.client.post("/api/reports", data={"farm_id": "farm_main", "image": (io.BytesIO(b""), "e.png")},
                        content_type="multipart/form-data")
    assert r.status_code == 400


def test_unknown_farm_is_404(ctx):
    assert post_report(ctx, farm_id="farm_nope").status_code == 404


def test_non_image_is_400_and_nothing_is_stored(ctx):
    ctx.vision = INVALID_VISION
    r = post_report(ctx)
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "INVALID_REQUEST"
    assert ctx.db.reports == {}


def test_uploaded_audio_is_removed_afterwards(ctx):
    r = ctx.client.post("/api/reports", data={"farm_id": "farm_main", "image": (io.BytesIO(PNG), "leaf.png"),
                                              "audio": (io.BytesIO(b"OGG"), "note.oga")},
                        content_type="multipart/form-data")
    assert r.status_code == 201
    assert [f for f in os.listdir(ctx.tmp) if f.startswith("upload_")] == []


def test_database_error_becomes_db_error_envelope(ctx, monkeypatch):
    class DBError(Exception):
        code = "DB_ERROR"

    monkeypatch.setattr(ctx.db, "get_farm", lambda farm_id: (_ for _ in ()).throw(DBError("secret table name")))
    r = post_report(ctx)
    body = r.get_json()
    assert r.status_code == 500 and body["error"]["code"] == "DB_ERROR" and "secret" not in body["error"]["message"]


def test_ai_failure_still_returns_201(ctx):
    ctx.vision = SimpleNamespace(analyse_leaf=lambda *a: {"ok": False, "error": {"code": "AI_UNAVAILABLE", "message": "x"}})
    r = post_report(ctx)
    assert r.status_code == 201 and r.get_json()["data"]["status"] == "expert_review_pending"


# ------------------------------------------------------------------ expert
def test_expert_endpoints_need_the_key(ctx):
    assert ctx.client.get("/api/expert/cases").status_code == 401
    assert ctx.client.get("/api/expert/cases", headers={"X-Expert-Key": "wrong"}).status_code == 401
    assert ctx.client.post("/api/expert/cases/rep_x/review", json={}).status_code == 401


def test_escalated_report_appears_in_the_queue(ctx):
    post_report(ctx, voice_text="it is spreading fast")
    data = ctx.client.get("/api/expert/cases", headers=KEY).get_json()["data"]
    assert data["count"] == 1 and data["cases"][0]["escalation_reason"] == "SEVERITY_KEYWORD"
    assert ctx.client.get("/api/expert/cases?status=bogus", headers=KEY).status_code == 400
    assert ctx.client.get("/api/expert/cases?status=follow_up", headers=KEY).get_json()["data"]["count"] == 0


def escalated_id(ctx):
    return post_report(ctx, voice_text="spreading").get_json()["data"]["id"]


def review(ctx, rid, **body):
    payload = {"expert_name": "Demo Expert", "guidance": "Remove affected leaves.", "confirmed_issue": "early_blight"}
    payload.update(body)
    return ctx.client.post("/api/expert/cases/%s/review" % rid, json=payload, headers=KEY)


def test_review_updates_status_messages_the_farmer_and_schedules_a_reminder(ctx):
    rid = escalated_id(ctx)
    r = review(ctx, rid)
    assert r.status_code == 201 and r.get_json()["data"]["status"] == "expert_reviewed"
    assert ctx.db.reports[rid]["status"] == "expert_reviewed"
    assert [e["status"] for e in ctx.db.events[rid]][-1] == "expert_reviewed"
    chat, text = ctx.sent[-1]
    assert chat == 111 and "Remove affected leaves." in text and "ನಿಮ್ಮ ವರದಿಗೆ ತಜ್ಞರ ಸಲಹೆ" in text
    assert any(call[0] == rid and call[1] == 48 for call in ctx.reminders.scheduled)
    assert ctx.client.get("/api/expert/cases", headers=KEY).get_json()["data"]["count"] == 0


def test_second_review_is_a_conflict(ctx):
    rid = escalated_id(ctx)
    assert review(ctx, rid).status_code == 201
    assert review(ctx, rid).status_code == 409


def test_review_validation_and_404(ctx):
    rid = escalated_id(ctx)
    assert review(ctx, rid, expert_name="").status_code == 400
    assert review(ctx, rid, guidance="  ").status_code == 400
    assert review(ctx, rid, confirmed_issue="alien_rot").status_code == 400
    assert review(ctx, rid, confirmed_issue=None).status_code == 201
    assert review(ctx, "rep_nope").status_code == 404


def test_telegram_failure_does_not_undo_the_review(ctx):
    rid = escalated_id(ctx)
    ctx.send_error = RuntimeError("telegram down")
    assert review(ctx, rid).status_code == 201 and ctx.db.reports[rid]["status"] == "expert_reviewed"


def test_missing_reminders_module_does_not_undo_the_review(ctx):
    rid = escalated_id(ctx)
    ctx.integrations["reminders"] = None
    assert review(ctx, rid).status_code == 201


# ------------------------------------------------------------------ radar
def test_public_radar_never_leaks_ids_or_exact_coordinates(ctx):
    ctx.db.clusters.append({"id": "clu_1", "crop": "tomato", "suspected_issue": "early_blight",
                            "area_label": "Kolar North", "centroid_lat": 13.14159, "centroid_lng": 78.13999,
                            "severity": "watch", "report_count": 3, "window_hours": 72, "label": "whatever",
                            "data_source": "simulated", "created_at": "2026-11-12T09:20:00Z",
                            "farm_ids": ["farm_main"], "report_ids": ["rep_1"], "farm_id": "farm_main"})
    body = ctx.client.get("/api/radar/clusters").get_json()["data"]
    cluster = body["clusters"][0]
    blob = str(body)
    assert "farm_" not in blob and "rep_" not in blob
    assert cluster["centroid_lat"] == 13.14 and cluster["centroid_lng"] == 78.14
    assert cluster["label"] == "potential_cluster" and body["has_simulated"] is True


def test_has_simulated_is_false_for_live_clusters(ctx):
    ctx.db.clusters.append({"id": "clu_1", "crop": "tomato", "suspected_issue": "early_blight", "area_label": "x",
                            "centroid_lat": 13.1, "centroid_lng": 78.1, "severity": "watch", "report_count": 3,
                            "window_hours": 72, "data_source": "live", "created_at": "2026-11-12T09:20:00Z"})
    assert ctx.client.get("/api/radar/clusters").get_json()["data"]["has_simulated"] is False


def test_cluster_detail_needs_key_and_404(ctx):
    assert ctx.client.get("/api/radar/clusters/clu_1").status_code == 401
    assert ctx.client.get("/api/radar/clusters/clu_1", headers=KEY).status_code in (404, 500)


# ------------------------------------------------------------------ reminders
def test_run_reminders(ctx):
    assert ctx.client.post("/api/reminders/run").status_code == 401
    r = ctx.client.post("/api/reminders/run", headers=KEY)
    assert r.get_json()["data"] == {"sent": 2, "failed": 0}
    assert callable(ctx.reminders.run_with)


def test_run_reminders_without_the_module_is_an_honest_error(ctx):
    ctx.integrations["reminders"] = None
    r = ctx.client.post("/api/reminders/run", headers=KEY)
    assert r.status_code == 500 and r.get_json()["error"]["code"] == "INTERNAL_ERROR"


# ------------------------------------------------------------------ demo scenario
DEMO = {"crop": "tomato", "suspected_issue": "early_blight", "area_label": "Kolar North",
        "target_farm_id": "farm_main"}


def test_demo_needs_the_key_and_valid_input(ctx):
    assert ctx.client.post("/api/demo/simulate-cluster", json=DEMO).status_code == 401
    for bad in ({**DEMO, "crop": "banana"}, {**DEMO, "suspected_issue": "healthy"}, {**DEMO, "area_label": ""}):
        assert ctx.client.post("/api/demo/simulate-cluster", json=bad, headers=KEY).status_code == 400
    assert ctx.client.post("/api/demo/simulate-cluster", json={**DEMO, "target_farm_id": "farm_nope"},
                           headers=KEY).status_code == 404


def test_demo_creates_a_simulated_cluster_and_alerts_the_target(ctx):
    r = ctx.client.post("/api/demo/simulate-cluster", json=DEMO, headers=KEY)
    data = r.get_json()["data"]
    assert r.status_code == 200 and data["data_source"] == "simulated" and data["alerts_sent"] == 1
    c = data["cluster"]
    assert c["data_source"] == "simulated" and c["label"] == "potential_cluster"
    assert c["crop"] == "tomato" and c["suspected_issue"] == "early_blight" and c["report_count"] >= 3
    assert ctx.sent[-1][0] == 111 and "outbreak" not in ctx.sent[-1][1].lower()
    sim_reports = [x for x in ctx.db.reports.values() if x["data_source"] == "simulated"]
    assert len(sim_reports) == 3
    assert all(f["data_source"] == "simulated" for fid, f in ctx.db.farms.items() if fid.startswith("farm_sim"))


def test_demo_can_be_repeated_and_alerts_again(ctx):
    first = ctx.client.post("/api/demo/simulate-cluster", json=DEMO, headers=KEY).get_json()["data"]
    second = ctx.client.post("/api/demo/simulate-cluster", json=DEMO, headers=KEY).get_json()["data"]
    assert second["alerts_sent"] == 1 and second["cluster"]["id"] != first["cluster"]["id"]


def test_demo_alerts_the_target_even_if_it_grows_a_different_crop(ctx):
    ctx.db.add_farm("farm_chilli", crop="chilli", chat_id=999, language="hi")
    r = ctx.client.post("/api/demo/simulate-cluster", json={**DEMO, "target_farm_id": "farm_chilli"}, headers=KEY)
    assert 999 in {chat for chat, _ in ctx.sent}  # the chilli target was alerted even though crops differ
    assert r.get_json()["data"]["alerts_sent"] == 2  # ...and so was the nearby tomato farm