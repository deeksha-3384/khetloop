"""Manual end-to-end check of reminders against P2's REAL db_client (memory mode only).

Usage (from repo root, venv active, after merging origin/dev):
    python -m tests.integrations.check_reminders

Refuses to run unless DB_MODE=memory, so it can never write test rows to Supabase.
"""
import os
import time

os.environ.setdefault("DB_MODE", "memory")

from database import db_client  # noqa: E402
from integrations import reminders  # noqa: E402

CHAT_ID = 999000111


def check(label: str, condition: bool) -> bool:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
    return bool(condition)


def main() -> None:
    mode = os.getenv("DB_MODE")
    print(f"DB_MODE = {mode}")
    if mode != "memory":
        print("Refusing to run: set DB_MODE=memory in .env first.")
        return

    farmer = db_client.get_or_create_farmer(CHAT_ID, "Reminder Test", "en")
    farm = db_client.get_or_create_farm(farmer["id"], "tomato", area_label="Test Area",
                                        lat=13.14, lng=78.13)
    report = db_client.insert_report(
        farm_id=farm["id"], image_path="test/none.jpg", voice_transcript=None,
        voice_language=None,
        assessment={"decision": "preliminary_assessment", "suspected_issue": "early_blight",
                    "confidence_band": "medium", "image_quality": "good",
                    "visible_symptoms": []},
        escalation_reason=None, why=[], weather=None, risk=None,
        reply_language="en", reply_text="test reply", status="ai_assessed",
        data_source="simulated",
    )
    print(f"Created report {report['id']}")

    sched = reminders.schedule(report["id"], 0, "Test reminder: have the spots spread?")
    print("schedule ->", sched)
    time.sleep(1.1)  # make sure the reminder counts as due

    delivered = []

    def fake_send(chat_id, text):
        delivered.append((chat_id, text))
        return True

    first = reminders.run_due(fake_send)
    print("run_due #1 ->", first)
    second = reminders.run_due(fake_send)
    print("run_due #2 ->", second)

    after = db_client.get_report(report["id"])
    statuses = [e["status"] for e in after["events"]]
    print("report status:", after["status"], "| events:", statuses)

    results = [
        check("schedule returned ok", sched["ok"]),
        check("first run sent exactly 1", first["ok"] and first["data"]["sent"] == 1
              and first["data"]["failed"] == 0),
        check("message went to the farmer's chat id", delivered == [(CHAT_ID, "Test reminder: have the spots spread?")]),
        check("report status is follow_up", after["status"] == "follow_up"),
        check("last event is follow_up by system",
              bool(after["events"]) and after["events"][-1]["status"] == "follow_up"
              and after["events"][-1]["actor"] == "system"),
        check("second run sent nothing (not re-sent)", second["ok"] and second["data"]["sent"] == 0),
    ]
    print("ALL CHECKS PASSED" if all(results) else "SOME CHECKS FAILED - send me this output")


if __name__ == "__main__":
    main()