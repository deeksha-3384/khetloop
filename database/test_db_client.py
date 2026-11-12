"""
Full database test for KhetLoop (owner: P2).

Run from the repo root:
    python -m database.test_db_client

Uses whichever DB_MODE is active (memory or supabase). Every row it creates is named
TEST_DB_... and is deleted at the end (and also at the start, in case an earlier run crashed).
"""
import os
import random
import sys

from database import db_client as d

PREFIX = "TEST_DB_"
AREA = "TEST_DB_AREA"
CHAT = 987650000 + random.randint(0, 9000)

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def expect_error(name, func, *args, **kwargs):
    """Passes only if func raises DBError (not a raw crash, not a silent success)."""
    global passed, failed
    try:
        func(*args, **kwargs)
    except d.DBError as exc:
        passed += 1
        print(f"  PASS  {name}  ({exc.code}: {exc.message[:60]})")
    except Exception as exc:
        failed += 1
        print(f"  FAIL  {name}: raised {type(exc).__name__} instead of DBError: {exc}")
    else:
        failed += 1
        print(f"  FAIL  {name}: no error was raised")


def good(issue="early_blight", band="medium"):
    return {"decision": "preliminary_assessment", "suspected_issue": issue,
            "confidence_band": band, "image_quality": "good",
            "visible_symptoms": ["brown concentric spots"]}


def abstain():
    return {"decision": "abstain_request_better_image", "suspected_issue": "unknown",
            "confidence_band": "low", "image_quality": "poor", "visible_symptoms": []}


WHY = [{"code": "NOT_CONFIRMED", "text": "This is a preliminary assessment, not a confirmed diagnosis."}]


def make_farm(index, lat, chat=None):
    farmer = d.get_or_create_farmer(chat, f"{PREFIX}Farmer{index}", "kn")
    farm = d.get_or_create_farm(farmer["id"], "tomato", "2026-10-05", AREA, lat, 78.13)
    return farmer, farm


def make_report(farm, path, assessment, status="ai_assessed", source="live"):
    return d.insert_report(farm["id"], path, "test voice note", "kn", assessment, None, WHY,
                           None, None, "kn", "test reply", status, source)


def cleanup(ctx):
    try:
        if d._is_memory():
            d._reset_memory()
            return
        sb = d._sb()
        if ctx["paths"]:
            sb.storage.from_(d._bucket()).remove(ctx["paths"])
        sb.table("clusters").delete().eq("area_label", AREA).execute()
        sb.table("farmers").delete().like("name", PREFIX + "%").execute()
    except Exception as exc:
        print(f"  WARNING: cleanup problem: {exc}")


def run(ctx):
    print("\n== Happy path ==")
    farmer = d.get_or_create_farmer(CHAT, PREFIX + "Farmer", "kn")
    check("1  create farmer", farmer["id"].startswith("fmr_") and farmer["language"] == "kn"
          and farmer["telegram_chat_id"] == CHAT)
    same = d.get_or_create_farmer(CHAT, PREFIX + "Renamed", "hi")
    check("1b same chat id returns the same farmer and updates it",
          same["id"] == farmer["id"] and same["name"] == PREFIX + "Renamed" and same["language"] == "hi")
    d.get_or_create_farmer(CHAT, PREFIX + "Farmer", "kn")

    farm = d.get_or_create_farm(farmer["id"], "tomato", "2026-10-05", AREA, 13.1399, 78.1299)
    check("2  create farm (lat/lng rounded to 2 decimals)", farm["id"].startswith("farm_")
          and farm["lat"] == 13.14 and farm["lng"] == 78.13 and farm["data_source"] == "live")
    check("2b same farmer + crop returns the same farm", d.get_or_create_farm(farmer["id"], "tomato") == farm)
    check("2c get_farm, get_farmer_for_farm, list_farms",
          d.get_farm(farm["id"]) == farm and d.get_farmer_for_farm(farm["id"])["id"] == farmer["id"]
          and any(f["id"] == farm["id"] for f in d.list_farms()))

    path = d.upload_image(b"fake-jpeg-bytes", farm["id"])
    ctx["paths"].append(path)
    url = d.signed_image_url(path)
    check("3  upload image returns '<farm_id>/<name>.jpg'",
          path.startswith(farm["id"] + "/") and path.endswith(".jpg"))
    check("3b signed URL is a link", url.startswith("http") and (d._is_memory() or "token" in url))

    escalated = good()
    escalated["decision"] = "escalate_to_expert"
    weather = {"fetched_at": "2026-11-12T09:14:00Z", "rain_expected": True, "rain_mm_next_48h": 12.4,
               "humidity_pct_avg": 82, "temp_c_avg": 24.5, "data_source": "live"}
    risk = {"level": "elevated", "reasons": ["Similar reports nearby", "Rain forecast"]}
    report = d.insert_report(farm["id"], path, "test voice note", "kn", escalated,
                             "MEDIUM_CONFIDENCE_HIGH_RISK", WHY, weather, risk, "kn", "test reply",
                             "expert_review_pending")
    check("4  insert report", report["id"].startswith("rep_") and report["events"] == []
          and report["status"] == "expert_review_pending")

    events = [d.add_report_event(report["id"], s, a) for s, a in
              [("submitted", "farmer"), ("ai_assessed", "ai"), ("expert_review_pending", "rules")]]
    check("5  add 3 report events", all({"status", "actor", "timestamp"} <= set(e) for e in events))

    got = d.get_report(report["id"])
    expected_keys = {"id", "farm_id", "crop", "created_at", "status", "data_source", "image_url",
                     "voice_transcript", "voice_language", "assessment", "why", "weather", "risk",
                     "farmer_reply", "events", "expert_review"}
    check("6  get_report returns exactly the contract keys", set(got) == expected_keys,
          str(set(got) ^ expected_keys))
    check("6b assessment, weather, risk, why, reply, crop",
          set(got["assessment"]) == {"decision", "suspected_issue", "confidence_band", "image_quality",
                                     "visible_symptoms", "confirmed"}
          and got["assessment"]["suspected_issue"] == "early_blight"
          and got["assessment"]["confirmed"] is False
          and got["weather"]["rain_expected"] is True and got["risk"]["level"] == "elevated"
          and got["why"][0]["code"] == "NOT_CONFIRMED"
          and got["farmer_reply"] == {"language": "kn", "text": "test reply", "audio_url": None}
          and got["crop"] == "tomato")
    check("6c events are in order and have timestamps",
          [e["status"] for e in got["events"]] == ["submitted", "ai_assessed", "expert_review_pending"]
          and all(e["timestamp"].endswith("Z") for e in got["events"]))
    check("6d signed image URL present and no review yet",
          bool(got["image_url"]) and got["expert_review"] is None and got["created_at"].endswith("Z"))

    check("7  expert queue contains the case",
          any(c["report_id"] == report["id"] and c["rain_expected"] is True for c in d.list_expert_cases()))
    review = d.insert_expert_review(report["id"], "Demo Expert",
                                    "Remove affected leaves and keep foliage dry.", "early_blight")
    check("7b insert expert review", review["id"].startswith("rev_") and review["report_id"] == report["id"])
    d.update_report_status(report["id"], "expert_reviewed")
    got = d.get_report(report["id"])
    check("7c report is now confirmed, with review and new status",
          got["status"] == "expert_reviewed" and got["assessment"]["confirmed"] is True
          and got["expert_review"]["expert_name"] == "Demo Expert")
    items = d.list_farm_reports(farm["id"])
    check("7d farm timeline shows the expert guidance",
          items[0]["report_id"] == report["id"] and items[0]["expert_guidance"].startswith("Remove affected"))

    print("\n== Abstain counting ==")
    check("A  no abstains yet", d.count_recent_abstains(farm["id"], 30) == 0)
    make_report(farm, path, abstain())
    make_report(farm, path, abstain())
    check("A2 two consecutive abstains are counted", d.count_recent_abstains(farm["id"], 30) == 2)
    latest = make_report(farm, path, good("healthy", "high"))
    check("A3 a non-abstain report resets the count", d.count_recent_abstains(farm["id"], 30) == 0)
    check("A4 timeline is newest first", d.list_farm_reports(farm["id"])[0]["report_id"] == latest["id"])

    print("\n== Clusters, alerts, reminders ==")
    _, farm_b = make_farm(2, 13.15)
    _, farm_c = make_farm(3, 13.16)
    rb = make_report(farm_b, path, good(), "ai_assessed", "simulated")
    rc = make_report(farm_c, path, good(), "ai_assessed", "simulated")
    similar = {r["report_id"] for r in
               d.find_similar_recent_reports("tomato", "early_blight", 72, 13.14, 78.13, 10)}
    check("8  find_similar_recent_reports finds the 3 test reports",
          {report["id"], rb["id"], rc["id"]} <= similar)
    rows = d.find_similar_recent_reports("tomato", "early_blight", 72, 13.14, 78.13, 10)
    sources = {r["report_id"]: r.get("data_source") for r in rows}
    check("8a similar rows carry data_source (simulated stays simulated)",
          sources.get(rb["id"]) == "simulated" and sources.get(rc["id"]) == "simulated"
          and all(v in ("live", "cached", "simulated", "unverified") for v in sources.values()))
    nearby = d.find_nearby_farms("tomato", 13.14, 78.13, 10, farm["id"])
    nearby_ids = {f["farm_id"] for f in nearby}
    check("8b find_nearby_farms excludes the given farm",
          farm_b["id"] in nearby_ids and farm_c["id"] in nearby_ids and farm["id"] not in nearby_ids)
    check("8c nearby rows have the contract keys",
          all(set(f) == {"farm_id", "farmer_id", "telegram_chat_id", "language", "area_label", "lat", "lng"}
              for f in nearby))
    far = {f["farm_id"] for f in d.find_nearby_farms("tomato", 28.61, 77.20, 10)}
    check("8d a far-away search does not return the test farms",
          not ({farm["id"], farm_b["id"], farm_c["id"]} & far))

    ids = [report["id"], rb["id"], rc["id"]]
    cluster = d.create_cluster("tomato", "early_blight", AREA, 13.15, 78.13, "watch", ids, 72, "simulated")



    check("8e create cluster", cluster["id"].startswith("clu_") and cluster["label"] == "potential_cluster"
          and cluster["report_count"] == 3 and cluster["data_source"] == "simulated")
    check("8f public cluster has no farm or report ids",
          not ({"farm_id", "report_id", "report_ids", "farm_ids"} & set(cluster)))
    detail = d.get_cluster_detail(cluster["id"])
    check("8g list_clusters and get_cluster_detail",
          any(c["id"] == cluster["id"] for c in d.list_clusters()) and len(detail["reports"]) == 3
          and detail["alerts"] == [] and d.get_cluster_detail("clu_missing0") is None)
    upgraded = d.update_cluster(cluster["id"], "elevated", 5, ids)
    check("8h update_cluster upgrades the severity",
          upgraded["severity"] == "elevated" and upgraded["report_count"] == 5)

    alert = d.insert_alert(cluster["id"], farm_b["id"], "Crop health notice: test message.", True, "simulated")
    check("9  insert alert (delivered)", alert["id"].startswith("alt_") and alert["delivered"] is True
          and alert["sent_at"] is not None and alert["data_source"] == "simulated")
    check("9b duplicate alert for the same farm and cluster returns None",
          d.insert_alert(cluster["id"], farm_b["id"], "again", True, "simulated") is None)
    undelivered = d.insert_alert(cluster["id"], farm_c["id"], "Crop health notice: test message.",
                                 False, "simulated")
    check("9c undelivered alert has no sent_at", undelivered["delivered"] is False
          and undelivered["sent_at"] is None)
    check("9d alerts show up in the cluster detail", len(d.get_cluster_detail(cluster["id"])["alerts"]) == 2)

    reminder = d.insert_reminder(report["id"], "2026-01-01T00:00:00Z",
                                 "Have the spots spread? Please send a new photo.")
    check("10 schedule reminder", reminder["id"].startswith("rem_") and reminder["sent"] is False
          and reminder["due_at"] == "2026-01-01T00:00:00Z")
    mine = [r for r in d.due_reminders("2026-12-01T00:00:00Z") if r["id"] == reminder["id"]]
    check("11 due_reminders returns it with report_id and telegram_chat_id",
          len(mine) == 1 and mine[0]["report_id"] == report["id"] and mine[0]["telegram_chat_id"] == CHAT)
    check("11b it is not due before its time",
          not any(r["id"] == reminder["id"] for r in d.due_reminders("2025-01-01T00:00:00Z")))
    d.mark_reminder_sent(reminder["id"])
    check("12 mark_reminder_sent removes it from the due list",
          not any(r["id"] == reminder["id"] for r in d.due_reminders("2026-12-01T00:00:00Z")))
    return farmer, farm, report


def failure_cases(ctx, farmer, farm, report):
    print("\n== Missing records ==")
    check("M  get_farm / get_report for unknown ids return None",
          d.get_farm("farm_missing0") is None and d.get_report("rep_missing0") is None)
    expect_error("M2 insert_report for a missing farm", d.insert_report, "farm_missing0", "x/y.jpg", None,
                 None, good(), None, [], None, None, None, None, "ai_assessed")
    expect_error("M3 farm for a missing farmer", d.get_or_create_farm, "fmr_missing0", "tomato")
    expect_error("M4 event for a missing report", d.add_report_event, "rep_missing0", "submitted", "farmer")
    expect_error("M5 alert for a missing cluster", d.insert_alert, "clu_missing0", farm["id"], "m", True)
    expect_error("M6 reminder for a missing report", d.insert_reminder, "rep_missing0",
                 "2026-01-01T00:00:00Z", "m")
    expect_error("M7 mark a missing reminder sent", d.mark_reminder_sent, "rem_missing0")

    print("\n== Duplicate expert review ==")
    expect_error("D  second review for the same report", d.insert_expert_review, report["id"],
                 "Other Expert", "Second opinion", None)

    print("\n== Invalid data ==")
    expect_error("I  invalid language", d.get_or_create_farmer, None, PREFIX + "bad", "fr")
    expect_error("I2 invalid crop", d.get_or_create_farm, farmer["id"], "banana")
    expect_error("I3 invalid sowing date", d.get_or_create_farm, farmer["id"], "chilli", "not-a-date")
    expect_error("I4 latitude out of range", d.get_or_create_farm, farmer["id"], "chilli", None, AREA, 200, 78)
    expect_error("I5 invalid event status", d.add_report_event, report["id"], "done", "farmer")
    expect_error("I6 invalid decision", d.insert_report, farm["id"], "x/y.jpg", None, None,
                 {"decision": "nope", "confidence_band": "low", "image_quality": "poor"}, None, [], None,
                 None, None, None, "ai_assessed")
    expect_error("I7 empty image", d.upload_image, b"", farm["id"])
    expect_error("I8 image over 10 MB", d.upload_image, b"x" * (10 * 1024 * 1024 + 1), farm["id"])
    expect_error("I9 invalid cluster severity", d.create_cluster, "tomato", "early_blight", AREA, 13.15,
                 78.13, "huge", [report["id"]], 72)

    print("\n== Storage failure ==")
    if d._is_memory():
        print("  SKIP  (needs DB_MODE=supabase)")
    else:
        saved = os.environ.get("SUPABASE_STORAGE_BUCKET")
        os.environ["SUPABASE_STORAGE_BUCKET"] = "no-such-bucket-xyz"
        try:
            expect_error("S  upload to a bucket that does not exist", d.upload_image, b"x", farm["id"])
        finally:
            if saved is None:
                os.environ.pop("SUPABASE_STORAGE_BUCKET", None)
            else:
                os.environ["SUPABASE_STORAGE_BUCKET"] = saved

    print("\n== Supabase connection failure ==")
    if d._is_memory():
        print("  SKIP  (needs DB_MODE=supabase)")
    else:
        saved_url = os.environ.get("SUPABASE_URL")
        saved_client = d._SB_CLIENT
        os.environ["SUPABASE_URL"] = "https://khetloop-no-such-project.invalid"
        d._SB_CLIENT = None
        try:
            expect_error("C  list_farms with an unreachable Supabase URL", d.list_farms)
        finally:
            if saved_url is None:
                os.environ.pop("SUPABASE_URL", None)
            else:
                os.environ["SUPABASE_URL"] = saved_url
            d._SB_CLIENT = saved_client


def main():
    mode = "memory" if d._is_memory() else "supabase"
    print(f"KhetLoop database test (DB_MODE={mode})")
    ctx = {"paths": []}
    cleanup(ctx)
    try:
        farmer, farm, report = run(ctx)
        failure_cases(ctx, farmer, farm, report)
    finally:
        print("\n== Cleanup ==")
        cleanup(ctx)
        print("  test rows deleted")
    print(f"\nRESULT: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()