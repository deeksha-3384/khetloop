"""Checks P2's database/db_client.py against the Master Contract (names and parameter order).
Run:  python -m tests.backend.check_db_contract
Needs no Supabase keys: it forces DB_MODE=memory."""
import inspect
import os
import sys

os.environ["DB_MODE"] = "memory"

from backend.config import Config  # noqa: E402,F401  (loads .env)

try:
    from database import db_client  # noqa: E402
except Exception as e:  # pragma: no cover
    print("FAIL  could not import database.db_client:", type(e).__name__, e)
    sys.exit(1)

REQUIRED = {
    "upload_image": ["image_bytes", "farm_id", "content_type"],
    "signed_image_url": ["path", "expires_s"],
    "get_or_create_farmer": ["telegram_chat_id", "name", "language"],
    "get_farmer_for_farm": ["farm_id"],
    "get_or_create_farm": ["farmer_id", "crop", "sowing_date", "area_label", "lat", "lng"],
    "get_farm": ["farm_id"],
    "list_farms": [],
    "insert_report": ["farm_id", "image_path", "voice_transcript", "voice_language", "assessment",
                      "escalation_reason", "why", "weather", "risk", "reply_language", "reply_text",
                      "status", "data_source"],
    "add_report_event": ["report_id", "status", "actor", "note"],
    "update_report_status": ["report_id", "status"],
    "get_report": ["report_id"],
    "list_farm_reports": ["farm_id"],
    "count_recent_abstains": ["farm_id", "minutes"],
    "list_expert_cases": ["status"],
    "insert_expert_review": ["report_id", "expert_name", "guidance", "confirmed_issue"],
    "find_similar_recent_reports": ["crop", "suspected_issue", "since_hours", "lat", "lng", "radius_km"],
    "find_nearby_farms": ["crop", "lat", "lng", "radius_km", "exclude_farm_id"],
    "create_cluster": ["crop", "suspected_issue", "area_label", "centroid_lat", "centroid_lng", "severity",
                       "report_ids", "window_hours", "data_source"],
    "list_clusters": [],
    "get_cluster_detail": ["cluster_id"],
    "insert_alert": ["cluster_id", "farm_id", "message", "delivered", "data_source"],
    "insert_reminder": ["report_id", "due_at", "message"],
    "due_reminders": ["now_iso"],
    "mark_reminder_sent": ["reminder_id"],
}
OPTIONAL = {"update_cluster": ["cluster_id", "severity", "report_count", "report_ids"]}

failures = 0


def check(name, expected, required):
    global failures
    fn = getattr(db_client, name, None)
    if fn is None:
        print(("FAIL  " if required else "note  ") + "%s is missing%s" % (name, "" if required else " (optional)"))
        failures += 1 if required else 0
        return
    actual = list(inspect.signature(fn).parameters)
    if actual[:len(expected)] != expected:
        print("FAIL  %s parameters are %s, contract says %s" % (name, actual, expected))
        failures += 1
    else:
        print("PASS  " + name)


for fname, params in REQUIRED.items():
    check(fname, params, True)
for fname, params in OPTIONAL.items():
    check(fname, params, False)
if not hasattr(db_client, "DBError"):
    print("FAIL  DBError class is missing")
    failures += 1
else:
    print("PASS  DBError")

print("\n%s: %d contract problem(s)" % ("ALL GOOD" if failures == 0 else "NEEDS FIXES", failures))
sys.exit(1 if failures else 0)