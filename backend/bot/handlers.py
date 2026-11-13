"""
Conversation logic for the Telegram bot (no network code here, so it is fully testable).
Imported by: backend/bot/bot.py

BotHandler(api, pipeline=None, db=None).handle_update(update)
    api       needs: send_text(chat_id, text, keyboard=None), send_voice(chat_id, path),
              send_chat_action(chat_id, action), download(file_id) -> bytes | None
    pipeline  callable(farm_id, image_bytes, filename, audio_path, voice_text, language) -> run_pipeline result
              (defaults to report_pipeline.run_pipeline with alert sending wired to this api)
    db        module with get_or_create_farmer / get_or_create_farm (defaults to database.db_client)

Flow: /start -> language -> crop -> area (location or button) -> ready.
Then photo + voice note / typed text (either order, or a photo caption, or /skip) -> pipeline -> reply.
Sessions live in memory: after a bot restart a farmer just sends /start again.
Nothing here logs names, chat ids or message text.
"""
import logging
import os
import time
from types import SimpleNamespace

from backend.config import Config

log = logging.getLogger("khetloop.bot")

LANG_BUTTONS = {"ಕನ್ನಡ": "kn", "हिन्दी": "hi", "English": "en"}
LANG_ALIASES = {"kannada": "kn", "hindi": "hi", "english": "en", "kn": "kn", "hi": "hi", "en": "en"}
CROP_LABELS = {
    "en": {"tomato": "Tomato", "potato": "Potato", "chilli": "Chilli", "other": "Other"},
    "hi": {"tomato": "टमाटर", "potato": "आलू", "chilli": "मिर्च", "other": "अन्य"},
    "kn": {"tomato": "ಟೊಮೇಟೊ", "potato": "ಆಲೂಗಡ್ಡೆ", "chilli": "ಮೆಣಸಿನಕಾಯಿ", "other": "ಇತರೆ"},
}
# Demo convenience: farmers who do not want to share a location can pick an area.
DEMO_AREAS = [("Kolar North", 13.14, 78.13), ("Kolar South", 13.10, 78.16), ("Chikkaballapur", 13.43, 77.73)]

MULTI_CHOOSE_LANGUAGE = ("Welcome to KhetLoop. Choose your language.\n"
                         "ಕೃಷಿಲೂಪ್‌ಗೆ ಸ್ವಾಗತ. ನಿಮ್ಮ ಭಾಷೆಯನ್ನು ಆರಿಸಿ.\n"
                         "खेतलूप में आपका स्वागत है। अपनी भाषा चुनें।")
MULTI_NEED_START = ("Please send /start first.\n"
                    "ದಯವಿಟ್ಟು ಮೊದಲು /start ಕಳುಹಿಸಿ.\n"
                    "कृपया पहले /start भेजें।")

T = {
    "en": {
        "ask_crop": "Which crop do you want to report on?",
        "ask_area": "Where is your farm? Share your location, or pick your area.",
        "share_location": "📍 Share my location",
        "skip_location": "Skip",
        "ready": "All set! Send a photo of the affected leaf. You can also send a voice note describing what you see.",
        "ask_voice": "Photo received. Now send a voice note describing the problem, or type it. Send /skip if you don't want to.",
        "ask_photo": "Got it. Now please send a photo of the affected leaf.",
        "need_photo_first": "Please send a photo of the leaf first.",
        "processing": "Checking your report, please wait a moment...",
        "why_header": "Why am I seeing this?",
        "err_not_photo": "That doesn't look like a photo I can read. Please send a clear photo of the leaf.",
        "err_general": "Sorry, something went wrong. Please try again in a moment.",
        "pick_button": "Please pick one of the buttons.",
    },
    "hi": {
        "ask_crop": "आप किस फसल की रिपोर्ट करना चाहते हैं?",
        "ask_area": "आपका खेत कहाँ है? अपनी लोकेशन भेजें, या अपना क्षेत्र चुनें।",
        "share_location": "📍 मेरी लोकेशन भेजें",
        "skip_location": "छोड़ें",
        "ready": "सब तैयार है! प्रभावित पत्ते की एक फोटो भेजें। आप जो देख रहे हैं उसे बताते हुए एक वॉइस नोट भी भेज सकते हैं।",
        "ask_voice": "फोटो मिल गई। अब समस्या बताते हुए एक वॉइस नोट भेजें, या लिखकर बताएं। न भेजना हो तो /skip भेजें।",
        "ask_photo": "समझ गया। अब कृपया प्रभावित पत्ते की फोटो भेजें।",
        "need_photo_first": "पहले कृपया पत्ते की फोटो भेजें।",
        "processing": "आपकी रिपोर्ट जांची जा रही है, कृपया थोड़ा इंतज़ार करें...",
        "why_header": "मुझे यह क्यों दिख रहा है?",
        "err_not_photo": "यह ऐसी फोटो नहीं लग रही जिसे मैं पढ़ सकूँ। कृपया पत्ते की साफ़ फोटो भेजें।",
        "err_general": "क्षमा करें, कुछ गड़बड़ हो गई। कृपया थोड़ी देर में फिर कोशिश करें।",
        "pick_button": "कृपया बटनों में से एक चुनें।",
    },
    "kn": {
        "ask_crop": "ನೀವು ಯಾವ ಬೆಳೆಯ ಬಗ್ಗೆ ವರದಿ ಮಾಡಲು ಬಯಸುತ್ತೀರಿ?",
        "ask_area": "ನಿಮ್ಮ ಹೊಲ ಎಲ್ಲಿದೆ? ನಿಮ್ಮ ಸ್ಥಳವನ್ನು ಕಳುಹಿಸಿ, ಅಥವಾ ನಿಮ್ಮ ಪ್ರದೇಶವನ್ನು ಆರಿಸಿ.",
        "share_location": "📍 ನನ್ನ ಸ್ಥಳ ಕಳುಹಿಸಿ",
        "skip_location": "ಬಿಟ್ಟುಬಿಡಿ",
        "ready": "ಎಲ್ಲವೂ ಸಿದ್ಧ! ಬಾಧಿತ ಎಲೆಯ ಫೋಟೋ ಕಳುಹಿಸಿ. ನೀವು ಏನು ನೋಡುತ್ತಿದ್ದೀರಿ ಎಂದು ಹೇಳುವ ಧ್ವನಿ ಸಂದೇಶವನ್ನೂ ಕಳುಹಿಸಬಹುದು.",
        "ask_voice": "ಫೋಟೋ ಸಿಕ್ಕಿತು. ಈಗ ಸಮಸ್ಯೆಯನ್ನು ವಿವರಿಸುವ ಧ್ವನಿ ಸಂದೇಶ ಕಳುಹಿಸಿ, ಅಥವಾ ಬರೆದು ತಿಳಿಸಿ. ಬೇಡವಾದರೆ /skip ಕಳುಹಿಸಿ.",
        "ask_photo": "ಸರಿ. ಈಗ ದಯವಿಟ್ಟು ಬಾಧಿತ ಎಲೆಯ ಫೋಟೋ ಕಳುಹಿಸಿ.",
        "need_photo_first": "ಮೊದಲು ದಯವಿಟ್ಟು ಎಲೆಯ ಫೋಟೋ ಕಳುಹಿಸಿ.",
        "processing": "ನಿಮ್ಮ ವರದಿಯನ್ನು ಪರಿಶೀಲಿಸಲಾಗುತ್ತಿದೆ, ದಯವಿಟ್ಟು ಸ್ವಲ್ಪ ಕಾಯಿರಿ...",
        "why_header": "ನನಗೆ ಇದು ಏಕೆ ಕಾಣಿಸುತ್ತಿದೆ?",
        "err_not_photo": "ಇದು ನಾನು ಓದಬಹುದಾದ ಫೋಟೋ ಅಲ್ಲ ಎಂದು ತೋರುತ್ತದೆ. ದಯವಿಟ್ಟು ಎಲೆಯ ಸ್ಪಷ್ಟ ಫೋಟೋ ಕಳುಹಿಸಿ.",
        "err_general": "ಕ್ಷಮಿಸಿ, ಏನೋ ತೊಂದರೆಯಾಯಿತು. ದಯವಿಟ್ಟು ಸ್ವಲ್ಪ ಸಮಯದ ನಂತರ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.",
        "pick_button": "ದಯವಿಟ್ಟು ಬಟನ್‌ಗಳಲ್ಲಿ ಒಂದನ್ನು ಆರಿಸಿ.",
    },
}

# 'Why am I seeing this?' lines for Kannada and Hindi (English uses the report's own sentences).
WHY_LOCAL = {
    "hi": {"IMAGE_SYMPTOMS": "फोटो में दिखे लक्षणों को देखा गया", "IMAGE_QUALITY": "फोटो साफ़ नहीं है",
           "LOW_CONFIDENCE": "नतीजे पर भरोसा कम है", "NEARBY_REPORTS": "आस-पास के खेतों से ऐसी ही रिपोर्ट आई हैं",
           "WEATHER_CONTEXT": "मौसम के पूर्वानुमान को ध्यान में रखा गया",
           "FARM_HISTORY": "आपके खेत की पिछली रिपोर्ट देखी गईं", "NOT_CONFIRMED": "यह पुष्टि किया हुआ निदान नहीं है"},
    "kn": {"IMAGE_SYMPTOMS": "ಫೋಟೋದಲ್ಲಿ ಕಾಣುವ ಲಕ್ಷಣಗಳನ್ನು ಪರಿಗಣಿಸಲಾಗಿದೆ", "IMAGE_QUALITY": "ಫೋಟೋ ಸ್ಪಷ್ಟವಾಗಿಲ್ಲ",
           "LOW_CONFIDENCE": "ಫಲಿತಾಂಶದ ಬಗ್ಗೆ ವಿಶ್ವಾಸ ಕಡಿಮೆ ಇದೆ",
           "NEARBY_REPORTS": "ಹತ್ತಿರದ ಹೊಲಗಳಿಂದ ಇದೇ ರೀತಿಯ ವರದಿಗಳು ಬಂದಿವೆ",
           "WEATHER_CONTEXT": "ಹವಾಮಾನ ಮುನ್ಸೂಚನೆಯನ್ನು ಪರಿಗಣಿಸಲಾಗಿದೆ",
           "FARM_HISTORY": "ನಿಮ್ಮ ಹೊಲದ ಹಿಂದಿನ ವರದಿಗಳನ್ನು ಪರಿಗಣಿಸಲಾಗಿದೆ", "NOT_CONFIRMED": "ಇದು ದೃಢೀಕೃತ ರೋಗನಿರ್ಣಯವಲ್ಲ"},
}


def _norm(text) -> str:
    return " ".join((text or "").split()).casefold()


def keyboard(rows):
    return {"keyboard": rows, "resize_keyboard": True, "one_time_keyboard": True}


def _remove_file(path):
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


class BotHandler:
    def __init__(self, api, pipeline=None, db=None):
        self.api = api
        self._pipeline = pipeline
        self._db = db
        self.sessions = {}

    # ------------------------------------------------------------------ dependencies
    def _run_pipeline(self, *args):
        if self._pipeline:
            return self._pipeline(*args)
        from backend.services import report_pipeline
        deps = SimpleNamespace(send_message=lambda chat_id, text: self.api.send_text(chat_id, text))
        return report_pipeline.run_pipeline(*args, deps=deps)

    def _database(self):
        if self._db:
            return self._db
        from database import db_client
        return db_client

    # ------------------------------------------------------------------ entry point
    def handle_update(self, update: dict):
        msg = update.get("message")
        if not msg or (msg.get("chat") or {}).get("type") != "private":
            return
        chat_id = msg["chat"]["id"]
        s = self.sessions.setdefault(chat_id, {"state": "new"})
        text = (msg.get("text") or "").strip()

        if text.startswith("/"):
            return self._command(chat_id, s, text)
        state = s["state"]
        if state == "language":
            return self._choose_language(chat_id, s, text)
        if state == "crop":
            return self._choose_crop(chat_id, s, text)
        if state == "area":
            return self._choose_area(chat_id, s, msg, text)
        if state != "ready":
            return self.api.send_text(chat_id, MULTI_NEED_START)

        if msg.get("photo"):
            return self._on_photo(chat_id, s, msg)
        if msg.get("voice") or msg.get("audio"):
            return self._on_voice(chat_id, s, msg)
        if text:
            return self._on_text(chat_id, s, text)
        return self.api.send_text(chat_id, T[s["language"]]["ready"])

    # ------------------------------------------------------------------ commands
    def _command(self, chat_id, s, text):
        cmd = text.split()[0].split("@")[0].lower()
        if cmd == "/start":
            self._clear_pending(s)
            s.clear()
            s["state"] = "language"
            return self.api.send_text(chat_id, MULTI_CHOOSE_LANGUAGE, keyboard([[{"text": t} for t in LANG_BUTTONS]]))
        if s.get("state") != "ready":
            return self.api.send_text(chat_id, MULTI_NEED_START)
        if cmd == "/skip":
            if s.get("pending_photo"):
                return self._process(chat_id, s)
            return self.api.send_text(chat_id, T[s["language"]]["need_photo_first"])
        return self.api.send_text(chat_id, T[s["language"]]["ready"])

    # ------------------------------------------------------------------ registration
    def _choose_language(self, chat_id, s, text):
        lang = LANG_BUTTONS.get(text) or LANG_ALIASES.get(_norm(text))
        if not lang:
            return self.api.send_text(chat_id, MULTI_CHOOSE_LANGUAGE, keyboard([[{"text": t} for t in LANG_BUTTONS]]))
        s["language"] = lang
        s["state"] = "crop"
        labels = CROP_LABELS[lang]
        rows = [[{"text": labels["tomato"]}, {"text": labels["potato"]}],
                [{"text": labels["chilli"]}, {"text": labels["other"]}]]
        return self.api.send_text(chat_id, T[lang]["ask_crop"], keyboard(rows))

    def _choose_crop(self, chat_id, s, text):
        lang = s["language"]
        wanted = _norm(text)
        crop = None
        for labels in CROP_LABELS.values():
            for key, label in labels.items():
                if _norm(label) == wanted or key == wanted:
                    crop = key
        if not crop:
            return self.api.send_text(chat_id, T[lang]["pick_button"])
        s["crop"] = crop
        s["state"] = "area"
        rows = [[{"text": T[lang]["share_location"], "request_location": True}],
                [{"text": name} for name, _, _ in DEMO_AREAS],
                [{"text": T[lang]["skip_location"]}]]
        return self.api.send_text(chat_id, T[lang]["ask_area"], keyboard(rows))

    def _choose_area(self, chat_id, s, msg, text):
        lang = s["language"]
        area_label = lat = lng = None
        if msg.get("location"):
            lat, lng = msg["location"].get("latitude"), msg["location"].get("longitude")
            area_label = "Shared location"
        else:
            preset = next(((n, la, lo) for n, la, lo in DEMO_AREAS if _norm(n) == _norm(text)), None)
            if preset:
                area_label, lat, lng = preset
            elif _norm(text) != _norm(T[lang]["skip_location"]):
                return self.api.send_text(chat_id, T[lang]["pick_button"])
        first_name = ((msg.get("from") or {}).get("first_name") or "Farmer")[:60]
        try:
            db = self._database()
            farmer = db.get_or_create_farmer(chat_id, first_name, lang)
            farm = db.get_or_create_farm(farmer["id"], s["crop"], None, area_label, lat, lng)
        except Exception as e:
            log.warning("registration failed: %s", type(e).__name__)
            return self.api.send_text(chat_id, T[lang]["err_general"])
        s["farm_id"] = farm["id"]
        s["state"] = "ready"
        return self.api.send_text(chat_id, T[lang]["ready"], {"remove_keyboard": True})

    # ------------------------------------------------------------------ photo and voice pairing
    def _clear_pending(self, s):
        _remove_file(s.pop("pending_audio", None))
        s.pop("pending_photo", None)
        s.pop("pending_text", None)

    def _on_photo(self, chat_id, s, msg):
        lang = s["language"]
        data = self.api.download(msg["photo"][-1]["file_id"])  # the largest size is last
        if not data:
            return self.api.send_text(chat_id, T[lang]["err_general"])
        s["pending_photo"] = (data, "photo.jpg")
        caption = (msg.get("caption") or "").strip()
        if caption:
            s["pending_text"] = caption
        if s.get("pending_audio") or s.get("pending_text"):
            return self._process(chat_id, s)
        return self.api.send_text(chat_id, T[lang]["ask_voice"])

    def _on_voice(self, chat_id, s, msg):
        lang = s["language"]
        obj = msg.get("voice") or msg.get("audio")
        data = self.api.download(obj["file_id"])
        if not data:
            return self.api.send_text(chat_id, T[lang]["err_general"])
        ext = ".oga" if msg.get("voice") else (os.path.splitext(obj.get("file_name") or "")[1] or ".mp3")
        os.makedirs(Config.TMP_DIR, exist_ok=True)
        path = os.path.join(Config.TMP_DIR, "voice_%d_%d%s" % (abs(chat_id), int(time.time() * 1000), ext))
        with open(path, "wb") as f:
            f.write(data)
        _remove_file(s.get("pending_audio"))
        s["pending_audio"] = path
        if s.get("pending_photo"):
            return self._process(chat_id, s)
        return self.api.send_text(chat_id, T[lang]["ask_photo"])

    def _on_text(self, chat_id, s, text):
        s["pending_text"] = text
        if s.get("pending_photo"):
            return self._process(chat_id, s)
        return self.api.send_text(chat_id, T[s["language"]]["ask_photo"])

    # ------------------------------------------------------------------ run the pipeline and reply
    def _process(self, chat_id, s):
        lang = s["language"]
        photo, filename = s["pending_photo"]
        audio, text = s.get("pending_audio"), s.get("pending_text")
        self.api.send_chat_action(chat_id, "typing")
        self.api.send_text(chat_id, T[lang]["processing"])
        result = None
        try:
            result = self._run_pipeline(s["farm_id"], photo, filename, audio, text, lang)
        except LookupError:
            self.api.send_text(chat_id, MULTI_NEED_START)
        except ValueError:
            self.api.send_text(chat_id, T[lang]["err_not_photo"])
        except Exception as e:
            log.warning("pipeline failed: %s", type(e).__name__)
            self.api.send_text(chat_id, T[lang]["err_general"])
        finally:
            self._clear_pending(s)
        if result is not None:
            self._send_result(chat_id, lang, result)

    def _send_result(self, chat_id, lang, result):
        audio_path = result.get("audio_path")
        try:
            report = result["report"]
            lines = [report["farmer_reply"]["text"], "", T[lang]["why_header"]]
            for item in report.get("why", []):
                line = item.get("text") if lang == "en" else WHY_LOCAL[lang].get(item.get("code"))
                if line:
                    lines.append("• " + line)
            self.api.send_text(chat_id, "\n".join(lines))
            if audio_path:
                self.api.send_voice(chat_id, audio_path)
        except Exception as e:
            log.warning("sending result failed: %s", type(e).__name__)
            self.api.send_text(chat_id, T[lang]["err_general"])
        finally:
            _remove_file(audio_path)