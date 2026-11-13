"""Real integration check: the Flask routes against P2's REAL db_client (memory mode), in one process.
Vision is stubbed (it is tested separately by try_vision) so the steps are predictable. Weather is the
real live call. Telegram messages are NOT sent.
Run:  python -m tests.backend.try_routes"""
import io
import os
import sys
from types import SimpleNamespace

os.environ["DB_MODE"] = "memory"

import base64  # noqa: E402

from backend.app import create_app  # noqa: E402
from backend.config import Config  # noqa: E402
from backend.utils import deps  # noqa: E402
from database import db_client  # noqa: E402

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
ASSESSMENT = {"suspected_issue": "early_blight", "confidence_band": "high", "image_quality": "good",
              "visible_symptoms": ["brown spots"], "confirmed": False}
STUB_VISION = SimpleNamespace(analyse_leaf=lambda image, crop, transcript: {
    "ok": True, "provider": "stub", "assessment": ASSESSMENT})
KEY = {"X-Expert-Key": Config.EXPERT_API_KEY}

deps.send_telegram = lambda chat_id, text: False  # never message anyone from this script
deps.pipeline_deps = lambda: SimpleNamespace(db=db_client, vision=STUB_VISION, send_message=deps.send_telegram)

client = create_app().test_client()
failures = 0


def check(name, condition, detail=""):
    global failures
    print(("PASS  " if condition else "FAIL  ") + name + ("" if condition else "   <- " + str(detail)[:300]))
    failures += 0 if condition else 1


farmer = db_client.get_or_create_farmer(900100, "Route Test", "en")
farm = db_client.get_or_create_farm(farmer["id"], "tomato", "2026-10-05", "Kolar North", 13.14, 78.13)
fid = farm["id"]

r = client.get("/api/health")
check("health", r.status_code == 200 and r.get_json()["data"]["services"]["database"] == "memory", r.get_json())

r = client.get("/api/farms")
check("list farms contains the test farm", any(f["id"] == fid for f in r.get_json()["data"]["farms"]), r.get_json())

r = client.post("/api/reports", data={"farm_id": fid, "image": (io.BytesIO(PNG), "leaf.png"),
                                      "voice_text": "it is spreading fast"}, content_type="multipart/form-data")
body = r.get_json()
check("submit report returns 201", r.status_code == 201, body)
report = body.get("data") or {}
rid = report.get("id", "")
check("report escalated for the severity word", (report.get("assessment") or {}).get("decision") == "escalate_to_expert"
      and report.get("status") == "expert_review_pending", report.get("assessment"))
check("report has why list ending in NOT_CONFIRMED", (report.get("why") or [{}])[-1].get("code") == "NOT_CONFIRMED")
check("events start with submitted", [e["status"] for e in report.get("events", [])][:1] == ["submitted"])
check("weather stored (live) or cleanly null", report.get("weather") is None
      or report["weather"].get("data_source") in ("live", "cached"), report.get("weather"))
check("image url present", bool(report.get("image_url")), report.get("image_url"))

r = client.get("/api/reports/" + rid)
check("get report", r.status_code == 200 and r.get_json()["data"]["id"] == rid, r.get_json())
r = client.get("/api/farms/%s/timeline" % fid)
check("farm timeline has the report", any(i.get("report_id") == rid for i in r.get_json()["data"]["items"]), r.get_json())
r = client.get("/api/expert/cases", headers=KEY)
check("expert queue lists the report", any(c.get("report_id") == rid for c in r.get_json()["data"]["cases"]), r.get_json())
check("expert queue needs the key", client.get("/api/expert/cases").status_code == 401)

r = client.post("/api/expert/cases/%s/review" % rid, headers=KEY, json={
    "expert_name": "Demo Expert", "guidance": "Remove affected leaves.", "confirmed_issue": "early_blight"})
check("review accepted (201)", r.status_code == 201, r.get_json())
check("second review is a conflict (409)", client.post("/api/expert/cases/%s/review" % rid, headers=KEY, json={
    "expert_name": "X", "guidance": "Y"}).status_code == 409)
r = client.get("/api/reports/" + rid)
data = r.get_json()["data"]
check("report is now expert_reviewed with the review attached",
      data["status"] == "expert_reviewed" and (data.get("expert_review") or {}).get("guidance") == "Remove affected leaves.",
      {"status": data.get("status"), "review": data.get("expert_review")})

r = client.post("/api/demo/simulate-cluster", headers=KEY, json={
    "crop": "tomato", "suspected_issue": "early_blight", "area_label": "Kolar North", "target_farm_id": fid})
body = r.get_json()
check("demo scenario returns 200", r.status_code == 200, body)
cluster = (body.get("data") or {}).get("cluster") or {}
check("demo cluster is a simulated potential_cluster",
      cluster.get("data_source") == "simulated" and cluster.get("label") == "potential_cluster", cluster)

r = client.get("/api/radar/clusters")
radar = r.get_json()["data"]
check("public radar lists the cluster and flags simulated data",
      radar["has_simulated"] is True and any(c["id"] == cluster.get("id") for c in radar["clusters"]), radar)
check("public radar leaks no farm or report ids", "farm_" not in str(radar) and "rep_" not in str(radar))
r = client.get("/api/radar/clusters/" + str(cluster.get("id")), headers=KEY)
check("cluster detail (key)", r.status_code == 200 and len(r.get_json()["data"]["reports"]) >= 3, r.get_json())

r = client.post("/api/reminders/run", headers=KEY)
print("info  reminders/run ->", r.status_code, r.get_json())

print("\n%s: %d problem(s)" % ("ALL GOOD" if failures == 0 else "NEEDS ATTENTION", failures))
sys.exit(1 if failures else 0)