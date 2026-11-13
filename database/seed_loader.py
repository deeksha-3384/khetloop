"""Seed loader for KhetLoop (Person 2).

Reads data/seed/farmers.json, farms.json and reports.json and loads them as
SIMULATED data. Run from the project root:

    python -m database.seed_loader            # load (refuses if simulated data already exists)
    python -m database.seed_loader --reset    # delete ALL simulated rows first, then load

Rules:
  * every inserted row is labelled data_source="simulated" (farmers have no such column;
    see delete_simulated in db_client.py for how they are cleaned up)
  * seed farmers always get telegram_chat_id = null
  * report time is relative: created_at = now - hours_ago, at load time
  * report events (submitted, ai_assessed, expert_review_pending) are timestamped to match
  * image_file is a file name in data/test_images/ and is uploaded with upload_image
  * ids in the files only link farm -> farmer and report -> farm; the database makes its own ids

Everything is checked BEFORE anything is deleted or inserted, so a typo in a file
cannot leave you with a wiped database and nothing loaded.
"""
import argparse
import json
import mimetypes
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from database import db_client as d

ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / "data" / "seed"
IMAGE_DIR = ROOT / "data" / "test_images"
SRC = "simulated"

# status -> the events a report of that status has gone through, in order
STATUS_EVENTS = {
    "submitted": [("submitted", "farmer")],
    "ai_assessed": [("submitted", "farmer"), ("ai_assessed", "ai")],
    "expert_review_pending": [("submitted", "farmer"), ("ai_assessed", "ai"),
                              ("expert_review_pending", "rules")],
    "follow_up": [("submitted", "farmer"), ("ai_assessed", "ai"),
                  ("expert_review_pending", "rules"), ("follow_up", "system")],
}


def fail(message: str):
    print(f"  ERROR: {message}")
    sys.exit(1)


def iso_z(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_list(name: str) -> list:
    path = SEED_DIR / name
    if not path.is_file():
        fail(f"missing seed file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        fail(f"{name} is not valid JSON: {exc}")
    if not isinstance(data, list):
        fail(f"{name} must contain a JSON list")
    return data


def need(row: dict, keys: list, where: str):
    for key in keys:
        if key not in row:
            fail(f"{where}: missing field '{key}'")


def validate(farmers: list, farms: list, reports: list) -> None:
    farmer_ids = set()
    for i, row in enumerate(farmers):
        where = f"farmers.json item {i + 1}"
        need(row, ["id", "name", "language"], where)
        farmer_ids.add(row["id"])
    farm_ids = set()
    for i, row in enumerate(farms):
        where = f"farms.json item {i + 1}"
        need(row, ["id", "farmer_id", "crop"], where)
        if row["farmer_id"] not in farmer_ids:
            fail(f"{where}: farmer_id '{row['farmer_id']}' is not in farmers.json")
        farm_ids.add(row["id"])
    for i, row in enumerate(reports):
        where = f"reports.json item {i + 1} ({row.get('id')})"
        need(row, ["id", "farm_id", "image_file", "hours_ago", "suspected_issue",
                   "confidence_band", "image_quality", "decision", "status"], where)
        if row["farm_id"] not in farm_ids:
            fail(f"{where}: farm_id '{row['farm_id']}' is not in farms.json")
        if row["status"] not in STATUS_EVENTS:
            fail(f"{where}: status '{row['status']}' is not supported by the loader yet "
                 f"(supported: {', '.join(STATUS_EVENTS)}). expert_reviewed and follow_up "
                 f"need an expert review record in the seed file.")
        try:
            if float(row["hours_ago"]) < 0:
                raise ValueError
        except (TypeError, ValueError):
            fail(f"{where}: hours_ago must be a number, 0 or more")
        if not (IMAGE_DIR / row["image_file"]).is_file():
            fail(f"{where}: image not found: {IMAGE_DIR / row['image_file']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Load KhetLoop simulated seed data")
    parser.add_argument("--reset", action="store_true",
                        help="delete ALL simulated rows first, then load the seed")
    args = parser.parse_args()

    mode = "memory" if d._is_memory() else "supabase"
    print(f"KhetLoop seed loader (DB_MODE={mode})")
    if mode == "memory":
        print("  NOTE: memory mode forgets everything when the script ends.")

    farmers = load_list("farmers.json")
    farms = load_list("farms.json")
    reports = load_list("reports.json")
    validate(farmers, farms, reports)
    print(f"  files OK: {len(farmers)} farmers, {len(farms)} farms, {len(reports)} reports")

    if args.reset:
        counts = d.delete_simulated()
        print("  reset: deleted simulated rows -> "
              + ", ".join(f"{k}: {v}" for k, v in counts.items()))
    else:
        existing = d.count_simulated()
        if existing:
            print(f"  {existing} simulated rows already exist - nothing added. "
                  f"Run with --reset to wipe them and reload (this refreshes timestamps).")
            return 0

    try:
        farmer_map = {}
        farmer_language = {}
        for row in farmers:
            if row.get("telegram_chat_id") is not None:
                print(f"  note: ignoring telegram_chat_id for seed farmer {row['id']} (must be null)")
            farmer = d.get_or_create_farmer(None, row["name"], row["language"])
            farmer_map[row["id"]] = farmer["id"]
            farmer_language[row["id"]] = row["language"]

        farm_map = {}
        farm_language = {}
        for row in farms:
            farm = d.get_or_create_farm(farmer_map[row["farmer_id"]], row["crop"],
                                        row.get("sowing_date"), row.get("area_label"),
                                        row.get("lat"), row.get("lng"), SRC)
            farm_map[row["id"]] = farm["id"]
            farm_language[row["id"]] = farmer_language[row["farmer_id"]]

        now = datetime.now(timezone.utc)
        for row in reports:
            created = now - timedelta(hours=float(row["hours_ago"]))
            farm_id = farm_map[row["farm_id"]]
            image_bytes = (IMAGE_DIR / row["image_file"]).read_bytes()
            content_type = mimetypes.guess_type(row["image_file"])[0] or "image/jpeg"
            path = d.upload_image(image_bytes, farm_id, content_type)

            assessment = {
                "decision": row["decision"],
                "suspected_issue": row["suspected_issue"],
                "confidence_band": row["confidence_band"],
                "image_quality": row["image_quality"],
                "visible_symptoms": row.get("visible_symptoms") or [],
            }
            transcript = row.get("voice_transcript")
            voice_language = row.get("voice_language") or (
                farm_language[row["farm_id"]] if transcript else None)
            report = d.insert_report(
                farm_id, path, transcript, voice_language, assessment,
                row.get("escalation_reason"), row.get("why") or [],
                row.get("weather"), row.get("risk"),
                row.get("reply_language"), row.get("reply_text"),
                row["status"], SRC, iso_z(created))

            for i, (status, actor) in enumerate(STATUS_EVENTS[row["status"]]):
                d.add_report_event(report["id"], status, actor, "Simulated seed data",
                                   iso_z(created + timedelta(seconds=i)))
            print(f"  report {row['id']} -> {report['id']} "
                  f"({row['hours_ago']}h ago, {row['status']})")
    except SystemExit:
        raise
    except Exception as exc:
        print(f"  ERROR while loading: {exc}")
        print("  The load stopped part-way. Run again with --reset to clean up and retry.")
        return 1

    print(f"  DONE. Loaded {len(farmers)} farmers, {len(farms)} farms, {len(reports)} reports "
          f"- all simulated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
