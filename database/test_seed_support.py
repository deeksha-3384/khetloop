"""Tests for created_at, data_source on farms, count_simulated and delete_simulated.

    $env:DB_MODE = "memory"        (or "supabase")
    python -m database.test_seed_support

delete_simulated is only tested in memory mode: in supabase mode it would wipe the shared
simulated demo data. The supabase run cleans up the rows it creates by itself.
"""
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from database import db_client as d
from database import test_db_client as t

JPEG = b"\xff\xd8\xff\xd9"


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def remove_own_rows(farmer_id: str, paths: list) -> None:
    """Supabase mode: delete the test farmer (cascades to its farms and reports) and images."""
    if d._is_memory():
        return
    try:
        d._sb().table("farmers").delete().eq("id", farmer_id).execute()
    except Exception as exc:
        print(f"  WARNING: could not delete test farmer {farmer_id}: {exc}")
    for path in paths:
        try:
            d._sb().storage.from_(d._bucket()).remove([path])
        except Exception:
            pass


def created_at_and_source() -> None:
    print("\n== created_at and farm data_source ==")
    farmer = d.get_or_create_farmer(None, t.PREFIX + "seedsupport", "en")
    paths = []
    try:
        farm = d.get_or_create_farm(farmer["id"], "tomato", None, t.AREA, 13.14, 78.13)
        path = d.upload_image(JPEG, farm["id"])
        paths.append(path)
        issue = t.good()["suspected_issue"]

        old_dt = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=100)
        old = iso(old_dt)
        rep = d.insert_report(farm["id"], path, None, None, t.good(), None, [], None, None,
                              None, None, "ai_assessed", "simulated", old)
        ev = d.add_report_event(rep["id"], "submitted", "farmer", "seed test", old)
        gap = abs((d._parse_ts(ev["timestamp"]) - old_dt).total_seconds())
        t.check("13  a backdated event keeps its time", gap < 2)

        recent = {r["report_id"] for r in
                  d.find_similar_recent_reports("tomato", issue, 72, 13.14, 78.13, 10)}
        wide = {r["report_id"] for r in
                d.find_similar_recent_reports("tomato", issue, 200, 13.14, 78.13, 10)}
        t.check("13b a report from 100 h ago is outside a 72 h window and inside a 200 h window",
                rep["id"] not in recent and rep["id"] in wide)

        t.expect_error("13c invalid created_at on a report", d.insert_report, farm["id"], path,
                       None, None, t.good(), None, [], None, None, None, None, "ai_assessed",
                       "live", "yesterday")
        t.expect_error("13d invalid created_at on an event", d.add_report_event, rep["id"],
                       "submitted", "farmer", None, "yesterday")

        before = d.count_simulated()
        sim_farm = d.get_or_create_farm(farmer["id"], "potato", None, t.AREA, 13.15, 78.13,
                                        "simulated")
        t.check("14  a farm created with data_source=simulated is counted",
                d.count_simulated() == before + 1)
        again = d.get_or_create_farm(farmer["id"], "potato", None, None, None, None, "live")
        t.check("14b same farmer + crop returns the same farm and does not relabel it",
                again["id"] == sim_farm["id"] and d.count_simulated() == before + 1)
        t.expect_error("14c invalid farm data_source", d.get_or_create_farm, farmer["id"],
                       "chilli", None, None, None, None, "fake")
    finally:
        remove_own_rows(farmer["id"], paths)


def delete_cases() -> None:
    print("\n== count_simulated / delete_simulated (memory mode only) ==")
    if not d._is_memory():
        print("  SKIP  (in supabase mode this would wipe the shared simulated data)")
        return
    saved = deepcopy(d._MEM)
    try:
        d._reset_memory()
        issue = t.good()["suspected_issue"]
        live_farmer = d.get_or_create_farmer(555000111, t.PREFIX + "live", "en")
        live_farm = d.get_or_create_farm(live_farmer["id"], "tomato", None, t.AREA, 13.14, 78.13)
        sim_farmer = d.get_or_create_farmer(None, t.PREFIX + "sim", "en")
        sim_farm = d.get_or_create_farm(sim_farmer["id"], "tomato", None, t.AREA, 13.15, 78.13,
                                        "simulated")
        p_sim = d.upload_image(JPEG, sim_farm["id"])
        p_live = d.upload_image(JPEG, live_farm["id"])
        sim_rep = d.insert_report(sim_farm["id"], p_sim, None, None, t.good(), None, [], None,
                                  None, None, None, "ai_assessed", "simulated")
        live_rep = d.insert_report(live_farm["id"], p_live, None, None, t.good(), None, [], None,
                                   None, None, None, "ai_assessed", "live")
        d.add_report_event(sim_rep["id"], "submitted", "farmer")
        d.add_report_event(live_rep["id"], "submitted", "farmer")
        cluster = d.create_cluster("tomato", issue, t.AREA, 13.15, 78.13, "watch",
                                   [sim_rep["id"], live_rep["id"]], 72, "simulated")
        d.insert_alert(cluster["id"], live_farm["id"], "Crop health notice: test.", True,
                       "simulated")

        t.check("15  count_simulated counts the simulated farm, report, cluster and alert",
                d.count_simulated() == 4)
        counts = d.delete_simulated()
        t.check("15b delete_simulated reports what it removed",
                all(counts.get(k) == 1 for k in
                    ("farms", "reports", "clusters", "alerts", "farmers")))
        t.check("15c live farm, live report and live farmer are untouched",
                d.get_farm(live_farm["id"]) is not None
                and d.get_report(live_rep["id"]) is not None
                and d.get_farmer_for_farm(live_farm["id"]) is not None)
        t.check("15d simulated farm, report, cluster and seed farmer are gone",
                d.get_farm(sim_farm["id"]) is None and d.get_report(sim_rep["id"]) is None
                and d.get_cluster_detail(cluster["id"]) is None
                and d.count_simulated() == 0
                and not any(f["id"] == sim_farmer["id"] for f in d._MEM["farmers"]))
        t.check("15e no orphan events, cluster links or alerts are left",
                [e["report_id"] for e in d._MEM["events"]] == [live_rep["id"]]
                and d._MEM["cluster_reports"] == [] and d._MEM["alerts"] == [])
    finally:
        d._MEM = saved


def main() -> None:
    mode = "memory" if d._is_memory() else "supabase"
    print(f"KhetLoop seed-support test (DB_MODE={mode})")
    created_at_and_source()
    delete_cases()
    print(f"\nRESULT: {t.passed} passed, {t.failed} failed")
    sys.exit(1 if t.failed else 0)


if __name__ == "__main__":
    main()
