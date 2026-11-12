"""
Community 'potential cluster' detection, rule-based (Master Contract section 9.2).
Imported by: backend/services/report_pipeline.py and backend/routes/demo.py
The cluster label is always 'potential_cluster' (CLUSTER_LABEL).

check_cluster(report, db=None) -> dict | None

report keys used: report_id, farm_id, crop, suspected_issue, confidence_band, lat, lng,
                  area_label, data_source.   (The report may or may not be stored yet.)
db: the module that provides find_similar_recent_reports, list_clusters, create_cluster
    (and optionally update_cluster). Defaults to database.db_client (P2). Tests pass a fake.

Returns None when there is no cluster, otherwise:
    {"cluster": <public Cluster dict>, "created": bool, "report_ids": [str]}
    created is False when a matching nearby cluster already existed (no duplicate is made).

One report is counted per farm (the newest), so one farm sending many photos cannot create a cluster.
Severity: 'watch' for 3-4 farms, 'elevated' for 5 or more.
"""
import math
from datetime import datetime, timedelta, timezone

from shared.constants import (COORD_DECIMALS, RADAR_MIN_REPORTS, RADAR_RADIUS_KM,
                              RADAR_TIME_WINDOW_HOURS)

NOT_CLUSTERABLE_ISSUES = ("unknown", "healthy")
CLUSTERABLE_BANDS = ("medium", "high")
ELEVATED_FROM = 5


def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _parse_iso(value):
    """Parse '2026-11-12T09:15:00Z' style strings. Returns None if it cannot be parsed."""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _default_db():
    from database import db_client  # P2's module; imported lazily so tests do not need it
    return db_client


def check_cluster(report: dict, db=None):
    issue = report.get("suspected_issue")
    crop = report.get("crop")
    lat, lng = report.get("lat"), report.get("lng")
    if (issue in NOT_CLUSTERABLE_ISSUES or issue is None
            or report.get("confidence_band") not in CLUSTERABLE_BANDS
            or not crop or lat is None or lng is None):
        return None

    db = db or _default_db()

    rows = list(db.find_similar_recent_reports(
        crop, issue, RADAR_TIME_WINDOW_HOURS, lat, lng, RADAR_RADIUS_KM))

    # Make sure the triggering report itself is counted, even if it is not stored yet.
    if report.get("report_id") not in {r.get("report_id") for r in rows}:
        rows.append({
            "report_id": report.get("report_id"), "farm_id": report.get("farm_id"),
            "confidence_band": report.get("confidence_band"), "created_at": None,
            "lat": lat, "lng": lng, "area_label": report.get("area_label"),
            "suspected_issue": issue, "data_source": report.get("data_source"),
        })

    # One report per farm: keep the newest. Re-check the rules defensively.
    per_farm = {}
    for r in rows:
        if r.get("suspected_issue", issue) != issue or r.get("confidence_band") not in CLUSTERABLE_BANDS:
            continue
        farm_id = r.get("farm_id")
        if farm_id is None or r.get("report_id") is None:
            continue
        best = per_farm.get(farm_id)
        if best is None or (r.get("created_at") or "9999") >= (best.get("created_at") or "9999"):
            per_farm[farm_id] = r

    members = list(per_farm.values())
    if len(members) < RADAR_MIN_REPORTS:
        return None

    severity = "elevated" if len(members) >= ELEVATED_FROM else "watch"
    coords = [(m["lat"], m["lng"]) for m in members if m.get("lat") is not None and m.get("lng") is not None]
    if not coords:
        coords = [(lat, lng)]
    centroid_lat = round(sum(c[0] for c in coords) / len(coords), COORD_DECIMALS)
    centroid_lng = round(sum(c[1] for c in coords) / len(coords), COORD_DECIMALS)
    report_ids = [m["report_id"] for m in members]
    area_label = report.get("area_label") or next(
        (m["area_label"] for m in members if m.get("area_label")), "your area")
    # Honest labelling: any simulated member makes the whole cluster 'simulated'.
    data_source = "simulated" if any(m.get("data_source") == "simulated" for m in members) else "live"

    # Reuse an existing nearby cluster (same crop and issue, inside the time window).
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RADAR_TIME_WINDOW_HOURS)
    for c in db.list_clusters():
        if c.get("crop") != crop or c.get("suspected_issue") != issue:
            continue
        if c.get("centroid_lat") is None or c.get("centroid_lng") is None:
            continue
        created = _parse_iso(c.get("created_at"))
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created is not None and created < cutoff:
            continue
        if _haversine_km(centroid_lat, centroid_lng, c["centroid_lat"], c["centroid_lng"]) <= RADAR_RADIUS_KM:
            updater = getattr(db, "update_cluster", None)  # optional function (contract C11)
            if updater is not None and (severity == "elevated" and c.get("severity") != "elevated"
                                        or len(members) > c.get("report_count", 0)):
                c = updater(c["id"], severity, len(members), report_ids)
            return {"cluster": c, "created": False, "report_ids": report_ids}

    cluster = db.create_cluster(crop, issue, area_label, centroid_lat, centroid_lng,
                                severity, report_ids, RADAR_TIME_WINDOW_HOURS, data_source)
    return {"cluster": cluster, "created": True, "report_ids": report_ids}