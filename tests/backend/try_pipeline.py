"""End-to-end check of the pipeline against P2's REAL db_client in memory mode.
  python -m tests.backend.try_pipeline tmp\\leaf.jpg                      real vision (Groq/Gemini)
  python -m tests.backend.try_pipeline tmp\\leaf.jpg spreading fast        add the farmer's words
  python -m tests.backend.try_pipeline tmp\\leaf.jpg --issue early_blight --neighbours
        fake vision result + two neighbour farms, to exercise clustering and alerts
Add --json to print the full report. Weather, speech and reminders are skipped if P4's modules
are not in the repo yet (that is the normal 'degraded' path)."""
import argparse
import base64
import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ["DB_MODE"] = "memory"

from backend.config import Config  # noqa: E402,F401
from backend.services import report_pipeline  # noqa: E402
from database import db_client  # noqa: E402

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

ap = argparse.ArgumentParser()
ap.add_argument("image")
ap.add_argument("words", nargs="*")
ap.add_argument("--issue", help="use a fake vision result with this issue (e.g. early_blight)")
ap.add_argument("--band", default="medium")
ap.add_argument("--neighbours", action="store_true", help="create 2 neighbour farms with similar reports")
ap.add_argument("--json", action="store_true")
args = ap.parse_args()

farmer = db_client.get_or_create_farmer(900001, "Test Farmer", "en")
farm = db_client.get_or_create_farm(farmer["id"], "tomato", "2026-10-05", "Kolar North", 13.14, 78.13)

if args.neighbours:
    for i in (1, 2):
        nf = db_client.get_or_create_farmer(900001 + i, "Neighbour %d" % i, "hi" if i == 2 else "kn")
        nfarm = db_client.get_or_create_farm(nf["id"], "tomato", None, "Kolar North", 13.14 + 0.01 * i, 78.13)
        path = db_client.upload_image(TINY_PNG, nfarm["id"], "image/png")
        db_client.insert_report(
            farm_id=nfarm["id"], image_path=path, voice_transcript=None, voice_language=None,
            assessment={"decision": "preliminary_assessment", "suspected_issue": args.issue or "early_blight",
                        "confidence_band": "medium", "image_quality": "good",
                        "visible_symptoms": ["brown spots"], "confirmed": False},
            escalation_reason=None, why=[], weather=None, risk=None, reply_language="en",
            reply_text="seed", status="ai_assessed", data_source="simulated")

deps = None
if args.issue:
    assessment = {"suspected_issue": args.issue, "confidence_band": args.band, "image_quality": "good",
                  "visible_symptoms": ["brown spots"], "confirmed": False}
    deps = SimpleNamespace(vision=SimpleNamespace(
        analyse_leaf=lambda image, crop, transcript: {"ok": True, "provider": "fake", "assessment": assessment}))

path = Path(args.image)
res = report_pipeline.run_pipeline(farm["id"], path.read_bytes(), path.name,
                                   voice_text=" ".join(args.words) or None, deps=deps)
report = res["report"]
print("report id      :", report["id"])
print("decision       :", report["assessment"]["decision"], "| status:", report["status"])
print("issue/band     :", report["assessment"]["suspected_issue"], "/", report["assessment"]["confidence_band"])
print("events         :", [e["status"] for e in report["events"]])
print("why codes      :", [w["code"] for w in report["why"]])
print("risk           :", report["risk"])
print("reply          :", report["farmer_reply"]["text"])
print("cluster        :", (res["cluster"] or {}).get("cluster"))
print("alerts delivered:", res["alerts_sent"], "| degraded:", res["degraded"])
if args.json:
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))