"""Generates data/seed/farmers.json, farms.json and reports.json.

Run from the repo root:   python tests/integrations/make_seed.py

Why a generator: every seeded report needs why, weather, risk and a reply in the
farmer's language. Writing that by hand in JSON invites mistakes, so it is
computed here from one small table and from data/approved_guidance.json.
Everything produced is simulated; the loader (P2) sets data_source='simulated'.
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "data" / "seed"
GUIDANCE_FILE = ROOT / "data" / "approved_guidance.json"

RADIUS_KM = 10          # RADAR_RADIUS_KM
WINDOW_H = 72           # RADAR_TIME_WINDOW_HOURS

# ---------------------------------------------------------------- people and farms
FARMERS = [
    {"id": "fmr_5eed0001", "name": "Ramesh", "language": "kn"},
    {"id": "fmr_5eed0002", "name": "Sunita", "language": "hi"},
    {"id": "fmr_5eed0003", "name": "Lakshmi", "language": "en"},
    {"id": "fmr_5eed0004", "name": "Manjula", "language": "kn"},
    {"id": "fmr_5eed0005", "name": "Venkatesh", "language": "kn"},
    {"id": "fmr_5eed0006", "name": "Imran", "language": "hi"},
    {"id": "fmr_5eed0007", "name": "Anil", "language": "en"},
    {"id": "fmr_5eed0008", "name": "Prakash", "language": "en"},
]
FARMS = [
    # Kolar North: the live demo farm will be at 13.14, 78.13. No early_blight here.
    {"id": "farm_5eed0001", "farmer_id": "fmr_5eed0001", "crop": "tomato", "sowing_date": "2026-10-05", "area_label": "Kolar North", "lat": 13.15, "lng": 78.14},
    {"id": "farm_5eed0002", "farmer_id": "fmr_5eed0002", "crop": "tomato", "sowing_date": "2026-10-08", "area_label": "Kolar North", "lat": 13.13, "lng": 78.12},
    # Chikkaballapur: chilli farm plus the three tomato farms of the potential cluster
    {"id": "farm_5eed0003", "farmer_id": "fmr_5eed0003", "crop": "chilli", "sowing_date": "2026-09-28", "area_label": "Chikkaballapur", "lat": 13.43, "lng": 77.73},
    {"id": "farm_5eed0004", "farmer_id": "fmr_5eed0004", "crop": "tomato", "sowing_date": "2026-10-02", "area_label": "Chikkaballapur", "lat": 13.44, "lng": 77.74},
    {"id": "farm_5eed0005", "farmer_id": "fmr_5eed0005", "crop": "tomato", "sowing_date": "2026-10-10", "area_label": "Chikkaballapur", "lat": 13.42, "lng": 77.72},
    {"id": "farm_5eed0006", "farmer_id": "fmr_5eed0006", "crop": "tomato", "sowing_date": "2026-10-12", "area_label": "Srinivaspur", "lat": 13.34, "lng": 78.21},
    {"id": "farm_5eed0007", "farmer_id": "fmr_5eed0007", "crop": "potato", "sowing_date": "2026-09-20", "area_label": "Hassan", "lat": 13.0, "lng": 76.1},
    {"id": "farm_5eed0008", "farmer_id": "fmr_5eed0008", "crop": "tomato", "sowing_date": "2026-10-06", "area_label": "Chikkaballapur", "lat": 13.41, "lng": 77.73},
]

# ---------------------------------------------------------------- weather (simulated)
WEATHER = {
    "Kolar North": {"rain_expected": True, "rain_mm_next_48h": 12.4, "humidity_pct_avg": 82, "temp_c_avg": 24.5},
    "Chikkaballapur": {"rain_expected": True, "rain_mm_next_48h": 9.6, "humidity_pct_avg": 78, "temp_c_avg": 25.1},
    "Srinivaspur": {"rain_expected": False, "rain_mm_next_48h": 0.8, "humidity_pct_avg": 66, "temp_c_avg": 27.3},
}

# ---------------------------------------------------------------- wording
CROP = {"en": "tomato", "hi": "टमाटर", "kn": "ಟೊಮೆಟೊ"}
ISSUE_LABEL = {
    "en": {"early_blight": "early blight", "late_blight": "late blight", "septoria_leaf_spot": "septoria leaf spot",
           "bacterial_spot": "bacterial spot", "leaf_curl": "leaf curl"},
    "hi": {"early_blight": "अगेती झुलसा", "late_blight": "पछेती झुलसा", "septoria_leaf_spot": "सेप्टोरिया पत्ती धब्बा",
           "bacterial_spot": "जीवाणु पत्ती धब्बा", "leaf_curl": "पत्ती मुड़ना (लीफ कर्ल)"},
    "kn": {"early_blight": "ಅರ್ಲಿ ಬ್ಲೈಟ್", "late_blight": "ಲೇಟ್ ಬ್ಲೈಟ್", "septoria_leaf_spot": "ಸೆಪ್ಟೋರಿಯಾ ಎಲೆ ಚುಕ್ಕೆ",
           "bacterial_spot": "ಬ್ಯಾಕ್ಟೀರಿಯಲ್ ಸ್ಪಾಟ್", "leaf_curl": "ಎಲೆ ಸುರುಳಿ (ಲೀಫ್ ಕರ್ಲ್)"},
}
SENT = {
    "en": {"issue": "Your {crop} leaf shows symptoms that resemble {issue}.",
           "healthy": "Your {crop} leaf looks healthy.",
           "prelim": "This is a preliminary assessment, not a confirmed diagnosis.",
           "abstain": "The photo is not clear enough. Please send a clearer photo of the leaf.",
           "escalate": "Your report has been sent to an agri expert for review."},
    "hi": {"issue": "आपके {crop} के पत्ते के लक्षण {issue} जैसे दिखते हैं।",
           "healthy": "आपके {crop} का पत्ता स्वस्थ दिख रहा है।",
           "prelim": "यह एक प्रारंभिक आकलन है, पुष्ट निदान नहीं।",
           "abstain": "फोटो पर्याप्त साफ़ नहीं है। कृपया पत्ते की एक साफ़ फोटो फिर से भेजें।",
           "escalate": "आपकी रिपोर्ट कृषि विशेषज्ञ को समीक्षा के लिए भेज दी गई है।"},
    "kn": {"issue": "ನಿಮ್ಮ {crop} ಎಲೆಯ ಲಕ್ಷಣಗಳು {issue} ರೋಗವನ್ನು ಹೋಲುತ್ತವೆ.",
           "healthy": "ನಿಮ್ಮ {crop} ಎಲೆ ಆರೋಗ್ಯವಾಗಿ ಕಾಣುತ್ತಿದೆ.",
           "prelim": "ಇದು ಪ್ರಾಥಮಿಕ ಮೌಲ್ಯಮಾಪನ, ದೃಢೀಕೃತ ರೋಗನಿರ್ಣಯವಲ್ಲ.",
           "abstain": "ಫೋಟೋ ಸ್ಪಷ್ಟವಾಗಿಲ್ಲ. ದಯವಿಟ್ಟು ಎಲೆಯ ಸ್ಪಷ್ಟ ಫೋಟೋವನ್ನು ಮತ್ತೆ ಕಳುಹಿಸಿ.",
           "escalate": "ನಿಮ್ಮ ವರದಿಯನ್ನು ಕೃಷಿ ತಜ್ಞರಿಗೆ ಕಳುಹಿಸಲಾಗಿದೆ. ಅವರು ಪರಿಶೀಲಿಸುತ್ತಾರೆ."},
}
BROWN = {"kn": "ನನ್ನ ಟೊಮೆಟೊ ಎಲೆಗಳ ಮೇಲೆ ಕಂದು ಕಲೆಗಳು ಬರುತ್ತಿವೆ.",
         "hi": "मेरे टमाटर के पत्तों पर भूरे धब्बे आ रहे हैं।",
         "en": "There are brown spots on my tomato leaves."}
SEVERE = {"kn": "ಕಲೆಗಳು ಇಡೀ ಹೊಲದಲ್ಲಿ ಹರಡುತ್ತಿವೆ.", "hi": "पत्तों पर धब्बे तेजी से फैल रहे हैं।"}

# ---------------------------------------------------------------- reports
# n, farm, image, hours_ago, issue, confidence, quality, decision, status, symptoms, transcript, reason
R = [
    # potential cluster: early blight, medium/high, 3 distinct farms, Chikkaballapur (>10 km from Kolar North)
    (1, 4, "clear_tomato_01.jpg", 22, "early_blight", "medium", "good", "preliminary_assessment", "ai_assessed", ["brown concentric spots"], "kn:BROWN", None),
    (2, 5, "clear_tomato_01.jpg", 15, "early_blight", "medium", "good", "preliminary_assessment", "ai_assessed", ["brown spots", "yellow rings around spots"], "kn:BROWN", None),
    (3, 8, "clear_tomato_01.jpg", 7, "early_blight", "high", "good", "preliminary_assessment", "ai_assessed", ["concentric brown rings", "yellowing around spots"], "en:BROWN", None),
    # lone early blight far from both areas (Srinivaspur): never part of a cluster
    (4, 6, "clear_tomato_01.jpg", 12, "early_blight", "medium", "good", "preliminary_assessment", "ai_assessed", ["brown spots"], None, None),
    # Kolar North: no early blight; at most one eligible report per issue
    (5, 1, "clear_tomato_03.jpg", 59, "healthy", "high", "good", "preliminary_assessment", "ai_assessed", [], None, None),
    (6, 1, "clear_tomato_05.jpg", 56, "leaf_curl", "medium", "good", "preliminary_assessment", "follow_up", ["curled upward leaf edges"], None, None),
    (7, 2, "clear_tomato_04.jpg", 18, "bacterial_spot", "medium", "good", "preliminary_assessment", "ai_assessed", ["small dark spots with yellow halo"], "hi:BROWN", None),
    (8, 2, "clear_tomato_02.jpg", 5, "late_blight", "medium", "good", "escalate_to_expert", "expert_review_pending", ["dark water-soaked patches"], None, "MEDIUM_CONFIDENCE_HIGH_RISK"),
    # blurry photo, then a blurry retry 30 minutes later -> escalated
    (9, 1, "blurry_tomato_01.jpg", 9, "unknown", "low", "poor", "abstain_request_better_image", "ai_assessed", [], None, None),
    (10, 1, "blurry_tomato_02.jpg", 8.5, "unknown", "low", "poor", "escalate_to_expert", "expert_review_pending", [], None, "UNCLEAR_AFTER_RETRY"),
    # severity word in the voice note (Srinivaspur)
    (11, 6, "clear_tomato_01.jpg", 3, "early_blight", "medium", "good", "escalate_to_expert", "expert_review_pending", ["brown spots", "leaf edges browning"], "hi:SEVERE", "SEVERITY_KEYWORD"),
    # clear photo but unclear cause
    (12, 5, "ambiguous_tomato_01.jpg", 40, "unknown", "low", "good", "abstain_request_better_image", "ai_assessed", ["small brown lesions, cause unclear"], None, None),
    # earlier healthy reports give two farms a short history
    (13, 4, "clear_tomato_03.jpg", 50, "healthy", "high", "good", "preliminary_assessment", "ai_assessed", [], None, None),
    (14, 8, "clear_tomato_03.jpg", 45, "healthy", "medium", "good", "preliminary_assessment", "ai_assessed", [], None, None),
]


def haversine_km(a, b):
    lat1, lng1, lat2, lng2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def build():
    with open(GUIDANCE_FILE, encoding="utf-8") as f:
        guidance = json.load(f)
    farm_by_id = {f["id"]: f for f in FARMS}
    lang_of = {f["id"]: f["language"] for f in FARMERS}
    farms_out = [dict(f) for f in FARMS]
    farmers_out = [{**f, "telegram_chat_id": None} for f in FARMERS]

    def transcript(spec, lang):
        if spec is None:
            return None
        key = spec.split(":")[1]
        return (BROWN if key == "BROWN" else SEVERE)[lang]

    rows = []
    for (n, fnum, image, hours, issue, conf, quality, decision, status, symptoms, tr, reason) in R:
        farm = farm_by_id[f"farm_5eed{fnum:04d}"]
        lang = lang_of[farm["farmer_id"]]
        if tr is not None:
            assert tr.split(":")[0] == lang, f"transcript language mismatch in report {n}"
        rows.append({"n": n, "farm": farm, "lang": lang, "image": image, "hours": hours, "issue": issue,
                     "conf": conf, "quality": quality, "decision": decision, "status": status,
                     "symptoms": symptoms, "tr": transcript(tr, lang), "reason": reason})

    def clusterable(r):
        return r["issue"] not in ("unknown", "healthy") and r["conf"] in ("medium", "high")

    reports = []
    for r in rows:
        farm, lang, issue = r["farm"], r["lang"], r["issue"]
        # earlier similar reports from OTHER farms nearby (what the pipeline would have counted)
        nearby = 0
        if clusterable(r):
            nearby = len({o["farm"]["id"] for o in rows
                          if o is not r and clusterable(o) and o["issue"] == issue
                          and o["farm"]["id"] != farm["id"] and o["farm"]["crop"] == farm["crop"]
                          and o["hours"] > r["hours"] and o["hours"] - r["hours"] <= WINDOW_H
                          and haversine_km(farm, o["farm"]) <= RADIUS_KM})
        earlier = sum(1 for o in rows if o["farm"]["id"] == farm["id"] and o["hours"] > r["hours"])
        weather = dict(WEATHER[farm["area_label"]], data_source="simulated")
        # why
        why = []
        if r["quality"] == "poor":
            why.append({"code": "IMAGE_QUALITY", "text": "The photo was too blurry or unclear to assess reliably."})
        elif issue == "healthy":
            why.append({"code": "IMAGE_SYMPTOMS", "text": "The photo shows no clear disease symptoms."})
        elif issue != "unknown":
            why.append({"code": "IMAGE_SYMPTOMS",
                        "text": f"The photo shows visible symptoms resembling {ISSUE_LABEL['en'][issue]}."})
        if r["conf"] == "low":
            why.append({"code": "LOW_CONFIDENCE", "text": "The assessment confidence is low, so no specific issue is suggested."})
        if nearby:
            why.append({"code": "NEARBY_REPORTS",
                        "text": f"{nearby} similar report{'s were' if nearby > 1 else ' was'} submitted nearby in the last 72 hours."})
        rain = weather["rain_expected"]
        why.append({"code": "WEATHER_CONTEXT",
                    "text": ("Rain is forecast in the next 48 hours (simulated forecast)." if rain
                             else "No significant rain is forecast in the next 48 hours (simulated forecast).")})
        if earlier:
            why.append({"code": "FARM_HISTORY",
                        "text": f"This farm has {earlier} earlier report{'s' if earlier > 1 else ''} on its timeline."})
        why.append({"code": "NOT_CONFIRMED", "text": "This is a preliminary assessment, not a confirmed diagnosis."})
        # risk (illustrative)
        reasons = []
        if nearby:
            reasons.append("Similar reports nearby")
        if rain and issue not in ("healthy", "unknown"):
            reasons.append("Rain forecast")
        risk = {"level": "elevated" if reasons else "normal", "reasons": reasons}
        # reply text, in the farmer's language, from approved guidance only
        s = SENT[lang]
        if r["decision"] == "abstain_request_better_image":
            reply = s["abstain"]
        elif r["decision"] == "escalate_to_expert":
            reply = f"{s['escalate']} {s['prelim']}"
        elif issue == "healthy":
            reply = f"{s['healthy']} {s['prelim']}"
        else:
            entry = guidance.get(issue) or guidance["default"]
            tips = " ".join(entry["guidance"][lang][:3])
            reply = f"{s['issue'].format(crop=CROP[lang], issue=ISSUE_LABEL[lang][issue])} {s['prelim']} {tips}"
        reports.append({
            "id": f"rep_5eed{r['n']:04d}", "farm_id": farm["id"], "image_file": r["image"], "hours_ago": r["hours"],
            "suspected_issue": issue, "confidence_band": r["conf"], "image_quality": r["quality"],
            "decision": r["decision"], "status": r["status"], "visible_symptoms": r["symptoms"],
            "voice_transcript": r["tr"], "escalation_reason": r["reason"],
            "why": why, "weather": weather, "risk": risk, "reply_language": lang, "reply_text": reply,
        })
    return farmers_out, farms_out, reports


def main():
    farmers, farms, reports = build()
    SEED.mkdir(parents=True, exist_ok=True)
    for name, data in (("farmers.json", farmers), ("farms.json", farms), ("reports.json", reports)):
        with open(SEED / name, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
    print(f"wrote {len(farmers)} farmers, {len(farms)} farms, {len(reports)} reports "
          f"= {len(farmers) + len(farms) + len(reports)} rows")


if __name__ == "__main__":
    main()