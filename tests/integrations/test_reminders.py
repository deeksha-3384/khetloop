from datetime import datetime, timedelta, timezone

import pytest

from integrations import reminders


class FakeDB:
    """Stands in for P2's db_client (same function names and argument order)."""

    def __init__(self, due=None):
        self.inserted, self.marked, self.events, self.statuses = [], [], [], []
        self.due = due or []
        self.due_calls = []
        self.fail_on = set()

    def _maybe_fail(self, name):
        if name in self.fail_on:
            raise RuntimeError("db down")

    def insert_reminder(self, report_id, due_at, message):
        self._maybe_fail("insert_reminder")
        self.inserted.append((report_id, due_at, message))
        return {"id": "rem_12345678", "report_id": report_id, "due_at": due_at,
                "message": message, "sent": False}

    def due_reminders(self, now_iso):
        self._maybe_fail("due_reminders")
        self.due_calls.append(now_iso)
        return self.due

    def mark_reminder_sent(self, reminder_id):
        self._maybe_fail("mark_reminder_sent")
        self.marked.append(reminder_id)

    def add_report_event(self, report_id, status, actor, note=None):
        self._maybe_fail("add_report_event")
        self.events.append((report_id, status, actor, note))
        return {}

    def update_report_status(self, report_id, status):
        self._maybe_fail("update_report_status")
        self.statuses.append((report_id, status))


def due_item(n, chat_id=1000):
    return {"id": f"rem_{n:08d}", "report_id": f"rep_{n:08d}", "due_at": "2026-11-12T09:00:00Z",
            "message": f"msg {n}", "sent": False, "telegram_chat_id": chat_id}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(reminders, "_db", lambda: fake)
    return fake


# ---------- schedule ----------
def test_schedule_success_default_message(db):
    before = datetime.now(timezone.utc)
    r = reminders.schedule("rep_a1b2c3d4", 48)
    assert r["ok"] is True and r["data_source"] == "live" and r["error"] is None
    assert r["data"]["reminder_id"] == "rem_12345678"
    report_id, due_at, message = db.inserted[0]
    assert report_id == "rep_a1b2c3d4"
    assert message == "Have the spots spread? Please send a new photo."
    due = datetime.strptime(due_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert timedelta(hours=47, minutes=59) < due - before < timedelta(hours=48, minutes=1)
    assert r["data"]["due_at"] == due_at


def test_schedule_custom_and_blank_message(db):
    reminders.schedule("rep_1", 1, "ಕಲೆಗಳು ಹರಡಿವೆಯೇ?")
    reminders.schedule("rep_2", 1, "   ")
    reminders.schedule("rep_3", 1, None)
    assert db.inserted[0][2] == "ಕಲೆಗಳು ಹರಡಿವೆಯೇ?"
    assert db.inserted[1][2] == reminders.DEFAULT_MESSAGE
    assert db.inserted[2][2] == reminders.DEFAULT_MESSAGE


def test_schedule_zero_hours_is_allowed(db):
    assert reminders.schedule("rep_1", 0)["ok"] is True


@pytest.mark.parametrize("report_id,hours", [
    (None, 48), ("", 48), ("   ", 48), (123, 48),
    ("rep_1", -1), ("rep_1", float("nan")), ("rep_1", float("inf")),
    ("rep_1", "48"), ("rep_1", None), ("rep_1", True), ("rep_1", 10**6),
])
def test_schedule_invalid_arguments(db, report_id, hours):
    r = reminders.schedule(report_id, hours)
    assert r["ok"] is False and r["error"]["code"] == "INVALID_REQUEST"
    assert db.inserted == []


def test_schedule_db_failure(db):
    db.fail_on.add("insert_reminder")
    r = reminders.schedule("rep_1", 48)
    assert r["ok"] is False and r["error"]["code"] == "DB_ERROR"
    assert r["data"] is None and r["data_source"] is None


def test_schedule_row_without_id(monkeypatch):
    class Bad(FakeDB):
        def insert_reminder(self, *a):
            return {"no": "id"}
    monkeypatch.setattr(reminders, "_db", lambda: Bad())
    assert reminders.schedule("rep_1", 48)["error"]["code"] == "DB_ERROR"


def test_db_module_unavailable(monkeypatch):
    def boom():
        raise ImportError("no database package")
    monkeypatch.setattr(reminders, "_db", boom)
    assert reminders.schedule("rep_1", 48)["error"]["code"] == "DB_ERROR"
    assert reminders.run_due(lambda c, t: True)["error"]["code"] == "DB_ERROR"


# ---------- run_due ----------
def test_run_due_sends_and_updates_everything(db):
    db.due = [due_item(1, 111), due_item(2, 222)]
    sent_msgs = []

    def send(chat_id, text):
        sent_msgs.append((chat_id, text))
        return True

    r = reminders.run_due(send)
    assert r == {"ok": True, "data": {"sent": 2, "failed": 0}, "data_source": "live", "error": None}
    assert sent_msgs == [(111, "msg 1"), (222, "msg 2")]
    assert db.marked == ["rem_00000001", "rem_00000002"]
    # contract C9: follow_up event by actor 'system', then status follow_up
    assert [e[:3] for e in db.events] == [("rep_00000001", "follow_up", "system"),
                                          ("rep_00000002", "follow_up", "system")]
    assert db.statuses == [("rep_00000001", "follow_up"), ("rep_00000002", "follow_up")]
    assert db.due_calls[0].endswith("Z") and "T" in db.due_calls[0]


def test_failed_send_continues_and_is_not_marked(db):
    db.due = [due_item(1), due_item(2), due_item(3)]
    results = iter([False, True, True])
    r = reminders.run_due(lambda c, t: next(results))
    assert r["data"] == {"sent": 2, "failed": 1}
    assert db.marked == ["rem_00000002", "rem_00000003"]
    assert [s[0] for s in db.statuses] == ["rep_00000002", "rep_00000003"]


def test_send_that_raises_is_a_failure_not_a_crash(db):
    db.due = [due_item(1), due_item(2)]
    calls = []

    def send(chat_id, text):
        calls.append(text)
        if text == "msg 1":
            raise RuntimeError("telegram down")
        return True

    r = reminders.run_due(send)
    assert r["data"] == {"sent": 1, "failed": 1} and len(calls) == 2
    assert db.marked == ["rem_00000002"]


def test_no_chat_id_is_not_sent_or_marked(db):
    db.due = [due_item(1, chat_id=None)]
    calls = []
    r = reminders.run_due(lambda c, t: calls.append(1) or True)
    assert r["data"] == {"sent": 0, "failed": 1}
    assert calls == [] and db.marked == [] and db.statuses == []


def test_item_without_id_or_report_id_is_not_sent(db):
    broken = due_item(1)
    del broken["report_id"]
    db.due = [broken, {"report_id": "rep_1", "telegram_chat_id": 5}, "junk", None]
    calls = []
    r = reminders.run_due(lambda c, t: calls.append(1) or True)
    assert r["data"] == {"sent": 0, "failed": 4} and calls == []


@pytest.mark.parametrize("failing", ["mark_reminder_sent", "add_report_event", "update_report_status"])
def test_bookkeeping_failure_does_not_undo_a_delivered_message(db, failing):
    db.due = [due_item(1)]
    db.fail_on.add(failing)
    r = reminders.run_due(lambda c, t: True)
    assert r["ok"] is True and r["data"] == {"sent": 1, "failed": 0}


def test_due_reminders_failure(db):
    db.fail_on.add("due_reminders")
    r = reminders.run_due(lambda c, t: True)
    assert r["ok"] is False and r["error"]["code"] == "DB_ERROR"


def test_empty_and_none_due_lists(db):
    assert reminders.run_due(lambda c, t: True)["data"] == {"sent": 0, "failed": 0}
    db.due = None
    assert reminders.run_due(lambda c, t: True)["data"] == {"sent": 0, "failed": 0}


def test_send_message_must_be_callable(db):
    for bad in (None, "x", 5):
        r = reminders.run_due(bad)
        assert r["ok"] is False and r["error"]["code"] == "INVALID_REQUEST"