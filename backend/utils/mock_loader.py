"""Temporary helper: serves data from shared/mocks/. Replaced by db_client in Phase 8."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

MOCK_DIR = Path(__file__).resolve().parent.parent.parent / "shared" / "mocks"

# report_id -> mock file
KNOWN_REPORTS = {
    "rep_a1b2c3d4": "report_escalated.json",
    "rep_b2c3d4e5": "report_preliminary.json",
    "rep_c3d4e5f6": "report_abstain.json",
}
# report_id -> expert review dict (in memory only, resets when the server restarts)
REVIEWED = {}


def load_mock(name: str):
    """Return the 'data' part of a mock file."""
    with open(MOCK_DIR / name, encoding="utf-8") as f:
        return json.load(f)["data"]


def farm_ids() -> set:
    return {f["id"] for f in load_mock("farms.json")["farms"]}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_mock_report(report_id: str):
    """Mock report, with any in-memory expert review applied. None if unknown."""
    filename = KNOWN_REPORTS.get(report_id)
    if filename is None:
        return None
    report = copy.deepcopy(load_mock(filename))
    review = REVIEWED.get(report_id)
    if review:
        report["status"] = "expert_reviewed"
        report["events"].append({"status": "expert_reviewed", "actor": "expert", "timestamp": review["created_at"]})
        report["expert_review"] = review
        report["assessment"]["confirmed"] = review["confirmed_issue"] is not None
    return report