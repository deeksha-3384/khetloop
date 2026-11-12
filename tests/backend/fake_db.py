"""A tiny in-memory stand-in for database/db_client.py, used only by the pipeline tests.
It implements just the functions the pipeline calls, with the contract's signatures."""
import itertools

_ids = itertools.count(1)


class FakeDB:
    def __init__(self):
        self.farms = {}      # farm_id -> farm dict
        self.farmers = {}    # farm_id -> farmer dict
        self.reports = {}    # report_id -> dict
        self.events = {}     # report_id -> list
        self.images = []
        self.clusters = []
        self.alerts = []     # alert dicts
        self.abstains = 0    # what count_recent_abstains returns

    # ---- test helpers
    def add_farm(self, farm_id="farm_main", crop="tomato", lat=13.14, lng=78.13, language="kn",
                 chat_id=111, data_source="live", area_label="Kolar North"):
        self.farms[farm_id] = {"id": farm_id, "farmer_id": "fmr_" + farm_id, "crop": crop, "lat": lat, "lng": lng,
                               "area_label": area_label, "sowing_date": None, "data_source": data_source}
        self.farmers[farm_id] = {"id": "fmr_" + farm_id, "name": "X", "language": language,
                                 "telegram_chat_id": chat_id}
        return farm_id

    def add_similar_report(self, farm_id, issue="early_blight", band="medium", crop="tomato", n=None):
        n = n or next(_ids)
        rid = "rep_seed%d" % n
        self.reports[rid] = {"id": rid, "farm_id": farm_id, "crop": crop, "suspected_issue": issue,
                             "confidence_band": band, "decision": "preliminary_assessment",
                             "created_at": "2026-11-12T0%d:00:00Z" % (n % 9), "data_source": "live"}
        self.events[rid] = []
        return rid

    # ---- functions the pipeline calls
    def get_farm(self, farm_id):
        return self.farms.get(farm_id)

    def get_farmer_for_farm(self, farm_id):
        return self.farmers.get(farm_id)

    def upload_image(self, image_bytes, farm_id, content_type="image/jpeg"):
        self.images.append((farm_id, content_type, len(image_bytes)))
        return "%s/img%d.jpg" % (farm_id, len(self.images))

    def list_farm_reports(self, farm_id):
        return [r for r in self.reports.values() if r["farm_id"] == farm_id]

    def count_recent_abstains(self, farm_id, minutes):
        return self.abstains

    def find_similar_recent_reports(self, crop, suspected_issue, since_hours, lat, lng, radius_km):
        rows = []
        for r in self.reports.values():
            f = self.farms.get(r["farm_id"], {})
            if r.get("crop") == crop and r.get("suspected_issue") == suspected_issue \
                    and r.get("confidence_band") in ("medium", "high"):
                rows.append({"report_id": r["id"], "farm_id": r["farm_id"], "confidence_band": r["confidence_band"],
                             "created_at": r.get("created_at"), "lat": f.get("lat"), "lng": f.get("lng"),
                             "area_label": f.get("area_label"), "suspected_issue": suspected_issue,
                             "data_source": r.get("data_source", "live")})
        return rows

    def insert_report(self, farm_id, image_path, voice_transcript, voice_language, assessment,
                      escalation_reason, why, weather, risk, reply_language, reply_text, status,
                      data_source="live"):
        rid = "rep_%08d" % next(_ids)
        self.reports[rid] = {
            "id": rid, "farm_id": farm_id, "crop": self.farms[farm_id]["crop"], "image_path": image_path,
            "voice_transcript": voice_transcript, "voice_language": voice_language,
            "assessment": assessment, "suspected_issue": assessment["suspected_issue"],
            "confidence_band": assessment["confidence_band"], "decision": assessment["decision"],
            "escalation_reason": escalation_reason, "why": why, "weather": weather, "risk": risk,
            "farmer_reply": {"language": reply_language, "text": reply_text, "audio_url": None},
            "status": status, "data_source": data_source, "created_at": "2026-11-12T09:15:00Z"}
        self.events[rid] = []
        return {"id": rid}

    def add_report_event(self, report_id, status, actor, note=None):
        self.events[report_id].append({"status": status, "actor": actor, "note": note})
        return self.events[report_id][-1]

    def get_report(self, report_id):
        r = dict(self.reports[report_id])
        r["events"] = list(self.events[report_id])
        return r

    def list_clusters(self):
        return list(self.clusters)

    def create_cluster(self, crop, suspected_issue, area_label, centroid_lat, centroid_lng, severity,
                       report_ids, window_hours, data_source="live"):
        c = {"id": "clu_%04d" % (len(self.clusters) + 1), "crop": crop, "suspected_issue": suspected_issue,
             "area_label": area_label, "centroid_lat": centroid_lat, "centroid_lng": centroid_lng,
             "severity": severity, "report_count": len(report_ids), "window_hours": window_hours,
             "label": "potential_cluster", "data_source": data_source,
             "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
             .strftime("%Y-%m-%dT%H:%M:%SZ")}
        self.clusters.append(c)
        return c

    def get_cluster_detail(self, cluster_id):
        return {"cluster": next(c for c in self.clusters if c["id"] == cluster_id), "reports": [],
                "alerts": [a for a in self.alerts if a["cluster_id"] == cluster_id]}

    def find_nearby_farms(self, crop, lat, lng, radius_km, exclude_farm_id=None):
        return [{"farm_id": fid, "farmer_id": self.farmers[fid]["id"],
                 "telegram_chat_id": self.farmers[fid]["telegram_chat_id"],
                 "language": self.farmers[fid]["language"], "area_label": f["area_label"],
                 "lat": f["lat"], "lng": f["lng"]}
                for fid, f in self.farms.items() if f["crop"] == crop and fid != exclude_farm_id]

    def insert_alert(self, cluster_id, farm_id, message, delivered, data_source="live"):
        if any(a["cluster_id"] == cluster_id and a["farm_id"] == farm_id for a in self.alerts):
            return None
        a = {"id": "alt_%04d" % (len(self.alerts) + 1), "cluster_id": cluster_id, "farm_id": farm_id,
             "message": message, "delivered": delivered, "data_source": data_source}
        self.alerts.append(a)
        return a