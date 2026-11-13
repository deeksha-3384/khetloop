"""Seed demo data for KhetLoop (Person 2).

Tells the whole loop story with SIMULATED data:
  report -> memory -> cluster -> expert -> follow-up

Run from the project root:
    $env:DB_MODE = "supabase"
    python -m database.seed_demo

Safe to re-run: if the demo farms already have reports it stops without adding more.
All reports, the cluster and the alerts are labelled data_source="simulated".
"""
import io
import sys
from datetime import datetime, timedelta, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from database import db_client as d

SRC = "simulated"
AREA = "Kolar, Karnataka (demo)"

# chat_id, name, language, crop, lat, lng, sowing_date
DEMO_FARMS = {
    "A": (9000000001, "Demo Farmer Ravi",   "en", "tomato", 13.15, 78.13, "2026-09-20"),
    "B": (9000000002, "Demo Farmer Lakshmi", "en", "tomato", 13.16, 78.14, "2026-09-22"),
    "C": (9000000003, "Demo Farmer Suresh", "en", "tomato", 13.14, 78.12, "2026-09-18"),
    "D": (9000000004, "Demo Farmer Anita",  "en", "tomato", 13.17, 78.15, "2026-09-25"),
    "E": (9000000005, "Demo Farmer Mohan",  "en", "tomato", 13.13, 78.14, "2026-09-21"),
}

WEATHER = {"temp_c": 27, "humidity_pct": 82, "rain_mm_24h": 6, "source": "simulated"}
RISK = {"level": "elevated", "reason": "High humidity and recent rain favour leaf spot diseases"}


def make_image(n: int) -> bytes:
    """A small labelled JPEG. Uses Pillow if installed, else a minimal placeholder."""
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (480, 320), (70, 120, 60))
        ImageDraw.Draw(img).text((20, 20), f"DEMO leaf photo {n} (simulated)", fill=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()
    except Exception:
        return b"\xff\xd8\xff\xd9"


def assessment(decision, issue, band, quality, symptoms):
    return {"decision": decision, "suspected_issue": issue, "confidence_band": band,
            "image_quality": quality, "visible_symptoms": symptoms}


def make_report(farm, n, assess, reason, why, reply, status):
    path = d.upload_image(make_image(n), farm["id"])
    return d.insert_report(farm["id"], path, None, None, assess, reason, why,
                           WEATHER, RISK, "en", reply, status, SRC)


def main():
    mode = "memory" if d._is_memory() else "supabase"
    print(f"KhetLoop demo seed (DB_MODE={mode})")
    if mode == "memory":
        print("  NOTE: memory mode forgets everything when the script ends. "
              "Set $env:DB_MODE = 'supabase' to seed the real database.")

    # 1. Farmers and farms (same chat id / same farmer+crop returns the existing row)
    farms = {}
    for key, (chat, name, lang, crop, lat, lng, sow) in DEMO_FARMS.items():
        farmer = d.get_or_create_farmer(chat, name, lang)
        farms[key] = d.get_or_create_farm(farmer["id"], crop, sow, AREA, lat, lng)
    print(f"  farms ready: {len(farms)}")

    # 2. Stop if already seeded
    if any(d.list_farm_reports(f["id"]) for f in farms.values()):
        print("  Demo farms already have reports - nothing added (already seeded).")
        return 0

    # 3. Three similar reports nearby -> the cluster
    r1 = make_report(
        farms["A"], 1,
        assessment("preliminary_assessment", "early_blight", "medium", "good",
                   ["brown spots with rings on lower leaves", "yellowing around the spots"]),
        None,
        ["Ringed brown spots match early blight", "Humid weather raises the risk"],
        "Preliminary assessment: this looks like early blight. Remove badly affected lower "
        "leaves and send a new photo in 2 days.",
        "ai_assessed")
    d.add_report_event(r1["id"], "submitted", "farmer", "Photo received")
    d.add_report_event(r1["id"], "ai_assessed", "ai", "Preliminary assessment: early blight (medium)")

    r2 = make_report(
        farms["B"], 2,
        assessment("escalate_to_expert", "early_blight", "medium", "good",
                   ["spots on many leaves", "spots spreading upward"]),
        "Symptoms are spreading across many leaves and confidence is not high enough",
        ["Spread across many leaves", "Rules require expert review when spread is wide"],
        "An expert will review your photo. You will get guidance here.",
        "expert_review_pending")
    d.add_report_event(r2["id"], "submitted", "farmer", "Photo received")
    d.add_report_event(r2["id"], "ai_assessed", "ai", "Possible early blight (medium)")
    d.add_report_event(r2["id"], "expert_review_pending", "rules", "Escalated: wide spread")

    r3 = make_report(
        farms["C"], 3,
        assessment("preliminary_assessment", "early_blight", "high", "good",
                   ["concentric ring spots", "lower leaves yellowing"]),
        None,
        ["Clear concentric rings", "Matches reports from nearby farms"],
        "Preliminary assessment: this looks like early blight. Please remove affected "
        "lower leaves and keep leaves dry.",
        "ai_assessed")
    d.add_report_event(r3["id"], "submitted", "farmer", "Photo received")
    d.add_report_event(r3["id"], "ai_assessed", "ai", "Preliminary assessment: early blight (high)")

    # 4. One unclear photo -> abstain
    r4 = make_report(
        farms["D"], 4,
        assessment("abstain_request_better_image", "unknown", "low", "poor", []),
        None,
        ["Image is blurry and too dark to judge"],
        "I cannot tell from this photo. Please send a clear, close photo of one leaf in daylight.",
        "ai_assessed")
    d.add_report_event(r4["id"], "submitted", "farmer", "Photo received")
    d.add_report_event(r4["id"], "ai_assessed", "ai", "Abstained: poor image quality")

    # 5. Expert reviews report 2 (the loop story)
    d.insert_expert_review(
        r2["id"], "Dr. Demo Expert",
        "Confirmed early blight. Remove affected leaves, avoid overhead watering, and "
        "ask your local agriculture office about a suitable fungicide.",
        "early_blight")
    rep = d.get_report(r2["id"])
    has_event = any(e.get("status") == "expert_reviewed" for e in (rep.get("events") or []))
    if rep.get("status") != "expert_reviewed":
        d.update_report_status(r2["id"], "expert_reviewed")
    if not has_event:
        d.add_report_event(r2["id"], "expert_reviewed", "expert", "Expert confirmed early blight")

    # 6. Follow-up + reminder (due in 2 days, so it will not fire during the demo setup)
    d.update_report_status(r2["id"], "follow_up")
    d.add_report_event(r2["id"], "follow_up", "system", "Follow-up reminder scheduled")
    due = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    d.insert_reminder(r2["id"], due, "Have the spots spread? Please send a new photo.")

    # 7. Cluster from the three similar reports
    cluster = d.create_cluster("tomato", "early_blight", AREA, 13.15, 78.13,
                               "watch", [r1["id"], r2["id"], r3["id"]], 72, SRC)
    print(f"  cluster created: {cluster['id']} ({cluster['report_count']} reports)")

    # 8. Alerts to nearby farms that have not reported
    msg = ("Crop health notice: several nearby tomato farms have reported similar leaf spots. "
           "Please check your plants and send a photo if you see spots. "
           "This is a precaution, not a confirmed diagnosis.")
    for key in ("D", "E"):
        d.insert_alert(cluster["id"], farms[key]["id"], msg, True, SRC)

    print("  reports: 4 | expert review: 1 | reminder: 1 | cluster: 1 | alerts: 2")
    print("  DONE. All labelled 'simulated'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
