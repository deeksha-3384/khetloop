"""
Farmer-facing messages. Replies are built from fixed templates plus APPROVED guidance only
(data/approved_guidance.json, written by P4). Imported by: report_pipeline.py, routes/expert.py,
routes/demo.py, bot/handlers.py, integrations reminders (message text).

Public functions
    write_reply(report_ctx, language) -> str
        report_ctx keys: decision (str, or the dict from decide()), assessment (dict | None),
                         escalation_reason (optional), crop (optional)
    write_alert(crop, area_label, language) -> str          cautious community notice
    write_followup(language) -> str                         reminder text
    write_expert_message(guidance, language) -> str         wraps a HUMAN expert's guidance (not filtered)
    is_safe(text) -> bool                                   the safety filter

Safety: AI-style text is never allowed to contain dosages, chemical or product names, or the word
for 'spray', in English, Kannada or Hindi. Anything unsafe is replaced by the fixed template reply.
All Kannada and Hindi strings must be reviewed by a native speaker before the demo.
"""
import json
import logging
import re
import unicodedata
from pathlib import Path

import requests

from backend.config import Config
from shared.constants import ALERT_TEMPLATE

log = logging.getLogger("khetloop.reply")

# Set True to let Groq reword the template in a friendlier way. Every output is still checked
# by the safety filter and falls back to the template if anything looks wrong.
USE_LLM_WORDING = False

GUIDANCE_PATH = Path(__file__).resolve().parents[2] / "data" / "approved_guidance.json"
DEFAULT_GROQ_MODEL = "qwen/qwen3.8-27b"
MAX_GUIDANCE_SENTENCES = 3
LANGS = ("kn", "hi", "en")

# ----------------------------------------------------------------------------- safety filter
_LATIN_UNITS = r"(?:ml|l|ltr|litres?|liters?|g|gms?|grams?|kg|mg|ppm|%|tsp|tbsp|cc)"
_INDIC_UNITS = r"(?:मिली|मि\.ली|ग्राम|लीटर|किलो|ಮಿ\.ಲೀ|ಮಿಲಿ|ಗ್ರಾಂ|ಲೀಟರ್|ಕೆ\.ಜಿ|ಕಿಲೋ)"
DOSAGE_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:" + _LATIN_UNITS + r"(?![a-zA-Z])|" + _INDIC_UNITS + r")", re.IGNORECASE)
LATIN_BLOCKED_RE = re.compile(
    r"\b(?:spray(?:ed|ing|s)?|dos(?:e|es|age|ing)|fungicides?|pesticides?|insecticides?|bactericides?|"
    r"herbicides?|chemicals?|per\s+(?:litre|liter|acre|hectare|tank)|mancozeb|chlorothalonil|"
    r"copper\s+(?:oxychloride|sulphate|sulfate)|bordeaux|carbendazim|metalaxyl|azoxystrobin|"
    r"propiconazole|hexaconazole|difenoconazole|tebuconazole|thiophanate|imidacloprid|"
    r"streptomycin|kasugamycin|neem\s+oil|antibiotics?|outbreak)\b", re.IGNORECASE)
INDIC_BLOCKED = (
    "छिड़काव", "छिडकाव", "स्प्रे", "कीटनाशक", "फफूंदनाशक", "फफूंदनाशी", "रसायन", "खुराक", "दवाई", "दवा",
    "मैन्कोज़ेब", "मैंकोजेब", "कार्बेन्डाजिम",
    "ಸಿಂಪಡ", "ಕೀಟನಾಶಕ", "ಶಿಲೀಂಧ್ರನಾಶಕ", "ರಾಸಾಯನಿಕ", "ಔಷಧ", "ಡೋಸ್", "ಪ್ರಮಾಣ",
    "ಮ್ಯಾಂಕೋಜೆಬ್", "ಕಾರ್ಬೆಂಡಾಜಿಮ್",
)


def _nfc(text) -> str:
    return unicodedata.normalize("NFC", text or "")


def is_safe(text) -> bool:
    """True if the text has no dosage, chemical or product name, spray word, or the forbidden word."""
    t = _nfc(text)
    if not t.strip():
        return False
    if DOSAGE_RE.search(t) or LATIN_BLOCKED_RE.search(t):
        return False
    return not any(_nfc(w) in t for w in INDIC_BLOCKED)


# ----------------------------------------------------------------------------- texts
ISSUE_NAMES = {
    "en": {"early_blight": "early blight", "late_blight": "late blight",
           "septoria_leaf_spot": "septoria leaf spot", "bacterial_spot": "bacterial spot",
           "leaf_curl": "leaf curl"},
    "hi": {"early_blight": "अर्ली ब्लाइट", "late_blight": "लेट ब्लाइट",
           "septoria_leaf_spot": "सेप्टोरिया पत्ती धब्बा", "bacterial_spot": "बैक्टीरियल स्पॉट",
           "leaf_curl": "पत्ता मुड़ना (लीफ कर्ल)"},
    "kn": {"early_blight": "ಅರ್ಲಿ ಬ್ಲೈಟ್", "late_blight": "ಲೇಟ್ ಬ್ಲೈಟ್",
           "septoria_leaf_spot": "ಸೆಪ್ಟೋರಿಯಾ ಎಲೆ ಚುಕ್ಕೆ", "bacterial_spot": "ಬ್ಯಾಕ್ಟೀರಿಯಲ್ ಸ್ಪಾಟ್",
           "leaf_curl": "ಎಲೆ ಸುರುಳಿ (ಲೀಫ್ ಕರ್ಲ್)"},
}

CROP_NAMES = {
    "en": {"tomato": "tomato", "potato": "potato", "chilli": "chilli", "other": "crop"},
    "hi": {"tomato": "टमाटर", "potato": "आलू", "chilli": "मिर्च", "other": "फसल"},
    "kn": {"tomato": "ಟೊಮೇಟೊ", "potato": "ಆಲೂಗಡ್ಡೆ", "chilli": "ಮೆಣಸಿನಕಾಯಿ", "other": "ಬೆಳೆ"},
}

AREA_FALLBACK = {"en": "your area", "hi": "आपके क्षेत्र", "kn": "ನಿಮ್ಮ ಪ್ರದೇಶ"}

TEXT = {
    "en": {
        "preliminary": "This is a preliminary assessment only, not a confirmed diagnosis. The photo shows "
                       "symptoms resembling {issue}. {guidance} If it gets worse or spreads, please send a new photo.",
        "healthy": "The photo shows no clear disease symptoms. This is a preliminary assessment only, not a "
                   "confirmed diagnosis. Keep watching your plants and send a new photo if you see any change.",
        "abstain": "The photo is not clear enough. Please send another photo of the leaf, taken close up in good light.",
        "escalate": "This is a preliminary assessment only, not a confirmed diagnosis. Your report has been sent to "
                    "an agriculture expert, who will review it and advise you.",
        "ai_unavailable": "The automatic photo analysis is not available right now. Your report has been sent to "
                          "an agriculture expert.",
        "followup": "Have the spots spread? Please send a new photo.",
        "expert": "Expert advice for your report: {guidance}",
    },
    "hi": {
        "preliminary": "यह केवल एक प्रारंभिक आकलन है, पुष्टि किया हुआ निदान नहीं। फोटो में {issue} जैसे लक्षण दिख "
                       "रहे हैं। {guidance} अगर लक्षण बढ़ें या फैलें, तो कृपया नई फोटो भेजें।",
        "healthy": "फोटो में बीमारी के साफ़ लक्षण नहीं दिख रहे हैं। यह केवल प्रारंभिक आकलन है, पुष्टि किया हुआ निदान "
                   "नहीं। अपने पौधों पर नज़र रखें और कोई बदलाव दिखे तो नई फोटो भेजें।",
        "abstain": "फोटो साफ़ नहीं है। कृपया पत्ते की पास से, अच्छी रोशनी में ली गई एक और फोटो भेजें।",
        "escalate": "यह केवल प्रारंभिक आकलन है, पुष्टि किया हुआ निदान नहीं। आपकी रिपोर्ट कृषि विशेषज्ञ को भेज दी गई "
                    "है। वे देखकर आपको सलाह देंगे।",
        "ai_unavailable": "फोटो का स्वचालित विश्लेषण अभी उपलब्ध नहीं है। आपकी रिपोर्ट कृषि विशेषज्ञ को भेज दी गई है।",
        "followup": "क्या धब्बे फैले हैं? कृपया एक नई फोटो भेजें।",
        "expert": "आपकी रिपोर्ट पर विशेषज्ञ की सलाह: {guidance}",
    },
    "kn": {
        "preliminary": "ಇದು ಕೇವಲ ಪ್ರಾಥಮಿಕ ಮೌಲ್ಯಮಾಪನ, ದೃಢೀಕೃತ ರೋಗನಿರ್ಣಯವಲ್ಲ. ಫೋಟೋದಲ್ಲಿ {issue} ತರಹದ ಲಕ್ಷಣಗಳು "
                       "ಕಾಣಿಸುತ್ತಿವೆ. {guidance} ಲಕ್ಷಣಗಳು ಹೆಚ್ಚಾದರೆ ಅಥವಾ ಹರಡಿದರೆ ದಯವಿಟ್ಟು ಹೊಸ ಫೋಟೋ ಕಳುಹಿಸಿ.",
        "healthy": "ಫೋಟೋದಲ್ಲಿ ರೋಗದ ಸ್ಪಷ್ಟ ಲಕ್ಷಣಗಳು ಕಾಣಿಸುತ್ತಿಲ್ಲ. ಇದು ಕೇವಲ ಪ್ರಾಥಮಿಕ ಮೌಲ್ಯಮಾಪನ, ದೃಢೀಕೃತ "
                   "ರೋಗನಿರ್ಣಯವಲ್ಲ. ಗಿಡಗಳನ್ನು ಗಮನಿಸುತ್ತಿರಿ, ಬದಲಾವಣೆ ಕಂಡರೆ ಹೊಸ ಫೋಟೋ ಕಳುಹಿಸಿ.",
        "abstain": "ಫೋಟೋ ಸ್ಪಷ್ಟವಾಗಿಲ್ಲ. ದಯವಿಟ್ಟು ಎಲೆಯ ಹತ್ತಿರದ, ಬೆಳಕಿನಲ್ಲಿ ತೆಗೆದ ಇನ್ನೊಂದು ಫೋಟೋ ಕಳುಹಿಸಿ.",
        "escalate": "ಇದು ಕೇವಲ ಪ್ರಾಥಮಿಕ ಮೌಲ್ಯಮಾಪನ, ದೃಢೀಕೃತ ರೋಗನಿರ್ಣಯವಲ್ಲ. ನಿಮ್ಮ ವರದಿಯನ್ನು ಕೃಷಿ ತಜ್ಞರಿಗೆ ಕಳುಹಿಸಲಾಗಿದೆ. "
                    "ಅವರು ಪರಿಶೀಲಿಸಿ ಸಲಹೆ ನೀಡುತ್ತಾರೆ.",
        "ai_unavailable": "ಫೋಟೋದ ಸ್ವಯಂಚಾಲಿತ ವಿಶ್ಲೇಷಣೆ ಈಗ ಲಭ್ಯವಿಲ್ಲ. ನಿಮ್ಮ ವರದಿಯನ್ನು ಕೃಷಿ ತಜ್ಞರಿಗೆ ಕಳುಹಿಸಲಾಗಿದೆ.",
        "followup": "ಕಲೆಗಳು ಹರಡಿವೆಯೇ? ದಯವಿಟ್ಟು ಹೊಸ ಫೋಟೋ ಕಳುಹಿಸಿ.",
        "expert": "ನಿಮ್ಮ ವರದಿಗೆ ತಜ್ಞರ ಸಲಹೆ: {guidance}",
    },
}

ALERT_TEXT = {
    "hi": "फसल स्वास्थ्य सूचना: {area_label} के पास हाल ही में {crop} के पत्तों में एक जैसे लक्षणों की कई रिपोर्ट मिली "
          "हैं। यह पुष्टि किया हुआ निदान नहीं है। कृपया अपने पौधों की जांच करें और ऐसे लक्षण दिखें तो फोटो भेजें।",
    "kn": "ಬೆಳೆ ಆರೋಗ್ಯ ಸೂಚನೆ: {area_label} ಹತ್ತಿರ ಇತ್ತೀಚೆಗೆ {crop} ಎಲೆಗಳಲ್ಲಿ ಒಂದೇ ರೀತಿಯ ಲಕ್ಷಣಗಳ ಹಲವು ವರದಿಗಳು "
          "ಬಂದಿವೆ. ಇದು ದೃಢೀಕೃತ ರೋಗನಿರ್ಣಯವಲ್ಲ. ದಯವಿಟ್ಟು ನಿಮ್ಮ ಗಿಡಗಳನ್ನು ಪರೀಕ್ಷಿಸಿ ಮತ್ತು ಇಂತಹ ಲಕ್ಷಣಗಳು ಕಂಡರೆ "
          "ಫೋಟೋ ಕಳುಹಿಸಿ.",
}

# Used when data/approved_guidance.json is missing or incomplete. Deliberately generic and safe.
BUILTIN_GUIDANCE = {
    "en": "Remove badly affected leaves and keep the plants dry with good airflow. "
          "Please confirm any treatment with your agri officer.",
    "hi": "ज़्यादा खराब पत्तों को हटा दें और पौधों को सूखा तथा हवादार रखें। कोई भी उपचार करने से पहले अपने कृषि "
          "अधिकारी से पूछें।",
    "kn": "ಹೆಚ್ಚು ಬಾಧಿತ ಎಲೆಗಳನ್ನು ತೆಗೆದುಹಾಕಿ, ಗಿಡಗಳನ್ನು ಒಣಗಿಡಿ ಮತ್ತು ಗಾಳಿ ಸರಿಯಾಗಿ ಹರಿಯುವಂತೆ ನೋಡಿಕೊಳ್ಳಿ. "
          "ಯಾವುದೇ ಚಿಕಿತ್ಸೆಗೆ ಮೊದಲು ನಿಮ್ಮ ಕೃಷಿ ಅಧಿಕಾರಿಯನ್ನು ಸಂಪರ್ಕಿಸಿ.",
}


# ----------------------------------------------------------------------------- guidance lookup
def _load_guidance_file() -> dict:
    try:
        with open(GUIDANCE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _guidance_text(issue: str, lang: str, use_file: bool = True) -> str:
    """Approved guidance for this issue and language: up to 3 SAFE sentences, else the built-in text."""
    if use_file:
        data = _load_guidance_file()
        for key in (issue, "default"):
            entry = data.get(key)
            sentences = ((entry or {}).get("guidance") or {}).get(lang) if isinstance(entry, dict) else None
            if isinstance(sentences, list):
                safe = [str(s).strip() for s in sentences if str(s).strip() and is_safe(str(s))]
                if safe:
                    return " ".join(safe[:MAX_GUIDANCE_SENTENCES])
    return BUILTIN_GUIDANCE[lang]


# ----------------------------------------------------------------------------- reply building
def _decision_and_reason(ctx: dict):
    decision = ctx.get("decision")
    reason = ctx.get("escalation_reason")
    if isinstance(decision, dict):
        reason = decision.get("escalation_reason", reason)
        decision = decision.get("decision")
    return decision, reason


def _template_reply(ctx: dict, lang: str, use_file: bool = True) -> str:
    decision, reason = _decision_and_reason(ctx)
    assessment = ctx.get("assessment")
    t = TEXT[lang]
    if decision == "abstain_request_better_image":
        return t["abstain"]
    if decision == "escalate_to_expert":
        return t["ai_unavailable"] if (reason == "AI_UNAVAILABLE" or not assessment) else t["escalate"]
    issue = (assessment or {}).get("suspected_issue", "unknown")
    if issue == "healthy":
        return t["healthy"]
    if issue == "unknown":
        return t["escalate"]  # should not happen for a preliminary result; stay safe
    name = ISSUE_NAMES[lang].get(issue, issue.replace("_", " "))
    return t["preliminary"].format(issue=name, guidance=_guidance_text(issue, lang, use_file))


# ----------------------------------------------------------------------------- optional LLM wording
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_SCRIPTS = {"kn": (0x0C80, 0x0CFF), "hi": (0x0900, 0x097F)}
_LANG_NAMES = {"kn": "Kannada", "hi": "Hindi", "en": "English"}


def _digit_values(text: str) -> set:
    values = set()
    for ch in text:
        if ch.isdecimal():
            values.add(unicodedata.decimal(ch))
        elif ch.isdigit():
            values.add(-1)
    return values


def _has_script(text: str, lang: str) -> bool:
    rng = _SCRIPTS.get(lang)
    return True if rng is None else any(rng[0] <= ord(ch) <= rng[1] for ch in text)


def _accept_llm(candidate: str, template: str, lang: str) -> bool:
    """Reject anything that is unsafe, too long, in the wrong script, or adds numbers."""
    return bool(
        candidate and is_safe(candidate)
        and len(candidate) <= len(template) * 2 + 200
        and _has_script(candidate, lang)
        and _digit_values(candidate) <= _digit_values(template)
    )


def _llm_reword(template: str, lang: str):
    prompt = (
        "Rewrite the message below for a small farmer in simple, warm, spoken %s. Keep the meaning exactly. "
        "Keep the statement that this is a preliminary assessment and not a confirmed diagnosis. "
        "Do NOT add any new advice, numbers, product names, chemicals or dosages. "
        "Output only the rewritten message.\n\nMessage:\n%s" % (_LANG_NAMES[lang], template))
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": "Bearer " + Config.GROQ_API_KEY, "Content-Type": "application/json"},
        json={"model": Config.GROQ_MODEL or DEFAULT_GROQ_MODEL, "temperature": 0.3,
              "max_completion_tokens": 1500, "messages": [{"role": "user", "content": prompt}]},
        timeout=20)
    if r.status_code != 200:
        log.warning("groq reply wording HTTP %s", r.status_code)
        return None
    content = r.json()["choices"][0]["message"].get("content") or ""
    return _THINK_RE.sub("", content).strip()


# ----------------------------------------------------------------------------- public API
def write_reply(report_ctx: dict, language: str) -> str:
    lang = language if language in LANGS else "en"
    template = _template_reply(report_ctx, lang)
    text = template
    if USE_LLM_WORDING and Config.GROQ_API_KEY:
        try:
            candidate = _llm_reword(template, lang)
            if candidate and _accept_llm(candidate, template, lang):
                text = candidate
        except Exception as e:  # never fail a report because of wording
            log.warning("reply wording failed: %s", type(e).__name__)
    if is_safe(text):
        return text
    fallback = _template_reply(report_ctx, lang, use_file=False)
    return fallback if is_safe(fallback) else TEXT[lang]["escalate"]


def write_alert(crop: str, area_label, language: str) -> str:
    lang = language if language in LANGS else "en"
    area = (area_label or "").strip() or AREA_FALLBACK[lang]
    crop_name = CROP_NAMES[lang].get(crop, CROP_NAMES[lang]["other"])
    if lang == "en":
        return ALERT_TEMPLATE.format(crop=crop_name, area_label=area)
    return ALERT_TEXT[lang].format(crop=crop_name, area_label=area)


def write_followup(language: str) -> str:
    return TEXT[language if language in LANGS else "en"]["followup"]


def write_expert_message(guidance: str, language: str) -> str:
    """Wraps verified guidance written by a human expert. Not filtered: the expert is accountable for it."""
    lang = language if language in LANGS else "en"
    return TEXT[lang]["expert"].format(guidance=(guidance or "").strip())