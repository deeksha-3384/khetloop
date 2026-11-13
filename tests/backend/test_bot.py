import logging
import os
from types import SimpleNamespace

import pytest

from backend.bot import bot as botmod
from backend.bot import handlers as H
from backend.services import reply_writer

CHAT = 42


class FakeAPI:
    def __init__(self):
        self.sent, self.voices, self.actions, self.files = [], [], [], {}

    def send_text(self, chat_id, text, keyboard=None):
        self.sent.append((chat_id, text, keyboard))
        return True

    def send_voice(self, chat_id, path):
        self.voices.append((chat_id, path))
        return True

    def send_chat_action(self, chat_id, action="typing"):
        self.actions.append(action)

    def download(self, file_id):
        return self.files.get(file_id)

    def texts(self):
        return [t for _, t, _ in self.sent]

    def last_text(self):
        return self.sent[-1][1]


class FakeDB:
    def __init__(self):
        self.farmers, self.farms = [], []

    def get_or_create_farmer(self, telegram_chat_id, name, language):
        self.farmers.append((telegram_chat_id, name, language))
        return {"id": "fmr_1"}

    def get_or_create_farm(self, farmer_id, crop, sowing_date=None, area_label=None, lat=None, lng=None):
        self.farms.append({"farmer_id": farmer_id, "crop": crop, "area_label": area_label, "lat": lat, "lng": lng})
        return {"id": "farm_%d" % len(self.farms)}


class FakePipeline:
    def __init__(self, tmp_path=None):
        self.calls, self.error, self.tmp_path, self.audio = [], None, tmp_path, None

    def __call__(self, farm_id, image, filename, audio_path, voice_text, language):
        self.calls.append({"farm_id": farm_id, "image": image, "audio_path": audio_path,
                           "audio_existed": bool(audio_path and os.path.exists(audio_path)),
                           "voice_text": voice_text, "language": language})
        if self.error:
            raise self.error
        audio = None
        if self.tmp_path is not None:
            audio = str(self.tmp_path / "reply.mp3")
            open(audio, "wb").write(b"mp3")
        return {"report": {"farmer_reply": {"text": "REPLY TEXT"},
                           "why": [{"code": "IMAGE_SYMPTOMS", "text": "Symptoms seen."},
                                   {"code": "NOT_CONFIRMED", "text": "Not a confirmed diagnosis."}]},
                "audio_path": audio}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(H.Config, "TMP_DIR", str(tmp_path), raising=False)
    api, db, pipe = FakeAPI(), FakeDB(), FakePipeline(tmp_path)
    handler = H.BotHandler(api, pipeline=pipe, db=db)
    return SimpleNamespace(api=api, db=db, pipe=pipe, h=handler, tmp=tmp_path)


def msg(text=None, photo=None, voice=None, audio=None, caption=None, location=None, chat=CHAT, ctype="private"):
    m = {"chat": {"id": chat, "type": ctype}, "from": {"first_name": "Ramesh"}}
    if text is not None:
        m["text"] = text
    if photo:
        m["photo"] = [{"file_id": "small"}, {"file_id": photo}]
    if voice:
        m["voice"] = {"file_id": voice}
    if audio:
        m["audio"] = {"file_id": audio, "file_name": "note.mp3"}
    if caption:
        m["caption"] = caption
    if location:
        m["location"] = {"latitude": location[0], "longitude": location[1]}
    return {"update_id": 1, "message": m}


def register(env, lang="en", crop=None, area="Kolar North"):
    crop = crop or H.CROP_LABELS[lang]["tomato"]
    env.h.handle_update(msg("/start"))
    env.h.handle_update(msg({"en": "English", "hi": "हिन्दी", "kn": "ಕನ್ನಡ"}[lang]))
    env.h.handle_update(msg(crop))
    env.h.handle_update(msg(area))
    env.api.files.update({"ph": b"IMG", "vo": b"OGG", "ph2": b"IMG2"})


# ------------------------------------------------------------------ registration
def test_start_shows_a_language_keyboard(env):
    env.h.handle_update(msg("/start"))
    chat, text, kb = env.api.sent[-1]
    assert "KhetLoop" in text and [b["text"] for b in kb["keyboard"][0]] == ["ಕನ್ನಡ", "हिन्दी", "English"]


def test_full_registration_creates_farmer_and_farm_with_coordinates(env):
    register(env, "kn", area="Kolar North")
    assert env.db.farmers == [(CHAT, "Ramesh", "kn")]
    assert env.db.farms == [{"farmer_id": "fmr_1", "crop": "tomato", "area_label": "Kolar North", "lat": 13.14, "lng": 78.13}]
    assert env.api.last_text() == H.T["kn"]["ready"]


def test_shared_location_is_stored(env):
    env.h.handle_update(msg("/start"))
    env.h.handle_update(msg("English"))
    env.h.handle_update(msg("Tomato"))
    env.h.handle_update(msg(location=(13.2, 78.2)))
    assert env.db.farms[0]["lat"] == 13.2 and env.db.farms[0]["lng"] == 78.2


def test_skipping_location_creates_a_farm_without_coordinates(env):
    register(env, "en", area="Skip")
    assert env.db.farms[0]["lat"] is None and env.db.farms[0]["lng"] is None


def test_invalid_choices_reprompt_without_advancing(env):
    env.h.handle_update(msg("/start"))
    env.h.handle_update(msg("klingon"))
    assert env.h.sessions[CHAT]["state"] == "language"
    env.h.handle_update(msg("Kannada"))
    env.h.handle_update(msg("banana"))
    assert env.h.sessions[CHAT]["state"] == "crop" and env.api.last_text() == H.T["kn"]["pick_button"]
    env.h.handle_update(msg("ಟೊಮೇಟೊ"))
    env.h.handle_update(msg("Narnia"))
    assert env.h.sessions[CHAT]["state"] == "area" and env.db.farms == []


def test_registration_failure_is_reported_and_state_kept(env):
    class BrokenDB(FakeDB):
        def get_or_create_farmer(self, *a, **k):
            raise RuntimeError("db down")

    h = H.BotHandler(env.api, pipeline=env.pipe, db=BrokenDB())
    for t in ("/start", "English", "Tomato", "Skip"):
        h.handle_update(msg(t))
    assert env.api.last_text() == H.T["en"]["err_general"] and h.sessions[CHAT]["state"] == "area"


def test_unregistered_user_is_told_to_start(env):
    env.h.handle_update(msg(photo="ph"))
    assert env.api.last_text() == H.MULTI_NEED_START and env.pipe.calls == []
    env.h.handle_update(msg("/skip"))
    assert env.api.last_text() == H.MULTI_NEED_START


# ------------------------------------------------------------------ photo and voice pairing
def test_photo_then_voice_runs_the_pipeline_with_both(env):
    register(env)
    env.h.handle_update(msg(photo="ph"))
    assert env.api.last_text() == H.T["en"]["ask_voice"] and env.pipe.calls == []
    env.h.handle_update(msg(voice="vo"))
    call = env.pipe.calls[0]
    assert call["image"] == b"IMG" and call["audio_path"].endswith(".oga") and call["audio_existed"]
    assert call["voice_text"] is None and call["language"] == "en" and call["farm_id"] == "farm_1"


def test_voice_then_photo_also_works(env):
    register(env)
    env.h.handle_update(msg(voice="vo"))
    assert env.api.last_text() == H.T["en"]["ask_photo"] and env.pipe.calls == []
    env.h.handle_update(msg(photo="ph"))
    assert env.pipe.calls[0]["image"] == b"IMG" and env.pipe.calls[0]["audio_path"].endswith(".oga")


def test_photo_then_skip_runs_without_voice(env):
    register(env)
    env.h.handle_update(msg(photo="ph"))
    env.h.handle_update(msg("/skip"))
    c = env.pipe.calls[0]
    assert c["audio_path"] is None and c["voice_text"] is None


def test_photo_then_typed_text_is_the_fallback(env):
    register(env)
    env.h.handle_update(msg(photo="ph"))
    env.h.handle_update(msg("spots on my leaves"))
    assert env.pipe.calls[0]["voice_text"] == "spots on my leaves" and env.pipe.calls[0]["audio_path"] is None


def test_text_then_photo_pairs_too(env):
    register(env)
    env.h.handle_update(msg("it is spreading"))
    env.h.handle_update(msg(photo="ph"))
    assert env.pipe.calls[0]["voice_text"] == "it is spreading"


def test_photo_caption_is_used_immediately(env):
    register(env)
    env.h.handle_update(msg(photo="ph", caption="brown spots"))
    assert env.pipe.calls[0]["voice_text"] == "brown spots"


def test_audio_file_message_is_accepted(env):
    register(env)
    env.h.handle_update(msg(photo="ph"))
    env.h.handle_update(msg(audio="vo"))
    assert env.pipe.calls[0]["audio_path"].endswith(".mp3")


def test_skip_without_a_photo_asks_for_one(env):
    register(env, "hi")
    env.h.handle_update(msg("/skip"))
    assert env.api.last_text() == H.T["hi"]["need_photo_first"] and env.pipe.calls == []


def test_a_new_photo_replaces_the_pending_one(env):
    register(env)
    env.h.handle_update(msg(photo="ph"))
    env.h.handle_update(msg(photo="ph2"))
    env.h.handle_update(msg("/skip"))
    assert env.pipe.calls[0]["image"] == b"IMG2"


def test_download_failure_is_reported(env):
    register(env)
    env.h.handle_update(msg(photo="missing"))
    assert env.api.last_text() == H.T["en"]["err_general"] and "pending_photo" not in env.h.sessions[CHAT]


# ------------------------------------------------------------------ the reply
def test_reply_contains_text_why_list_and_audio_then_cleans_up(env):
    register(env)
    env.h.handle_update(msg(photo="ph"))
    env.h.handle_update(msg("/skip"))
    assert env.api.actions == ["typing"] and H.T["en"]["processing"] in env.api.texts()
    reply = env.api.last_text()
    assert "REPLY TEXT" in reply and H.T["en"]["why_header"] in reply and "• Symptoms seen." in reply
    assert len(env.api.voices) == 1 and not os.path.exists(env.api.voices[0][1])
    s = env.h.sessions[CHAT]
    assert "pending_photo" not in s and "pending_audio" not in s and "pending_text" not in s


def test_kannada_farmer_gets_localised_why_lines(env):
    register(env, "kn")
    env.h.handle_update(msg(photo="ph"))
    env.h.handle_update(msg("/skip"))
    reply = env.api.last_text()
    assert H.WHY_LOCAL["kn"]["IMAGE_SYMPTOMS"] in reply and "Symptoms seen." not in reply
    assert env.pipe.calls[0]["language"] == "kn"


def test_temp_voice_file_is_deleted_after_processing(env):
    register(env)
    env.h.handle_update(msg(photo="ph"))
    env.h.handle_update(msg(voice="vo"))
    assert not os.path.exists(env.pipe.calls[0]["audio_path"])


def test_pipeline_errors_become_friendly_messages_and_clear_state(env):
    register(env)
    for error, expected in ((ValueError("x"), H.T["en"]["err_not_photo"]),
                            (LookupError("x"), H.MULTI_NEED_START),
                            (RuntimeError("secret internals"), H.T["en"]["err_general"])):
        env.pipe.error = error
        env.h.handle_update(msg(photo="ph"))
        env.h.handle_update(msg("/skip"))
        assert env.api.last_text() == expected and "secret internals" not in env.api.last_text()
        assert "pending_photo" not in env.h.sessions[CHAT]


def test_restart_command_resets_everything(env):
    register(env)
    env.h.handle_update(msg(photo="ph"))
    env.h.handle_update(msg("/start"))
    assert env.h.sessions[CHAT] == {"state": "language"}


# ------------------------------------------------------------------ robustness
def test_group_chats_and_non_message_updates_are_ignored(env):
    env.h.handle_update(msg("/start", ctype="group"))
    env.h.handle_update({"update_id": 2, "edited_message": {}})
    env.h.handle_update({"update_id": 3})
    assert env.api.sent == [] and env.h.sessions == {}


def test_two_farmers_do_not_mix_sessions(env):
    register(env, "en")
    env.h.handle_update(msg("/start", chat=7))
    env.h.handle_update(msg("ಕನ್ನಡ", chat=7))
    assert env.h.sessions[CHAT]["language"] == "en" and env.h.sessions[7]["language"] == "kn"


def test_every_bot_string_is_clean_and_localised():
    keys = set(H.T["en"])
    assert set(H.T["hi"]) == keys and set(H.T["kn"]) == keys
    for lang, table in H.T.items():
        for key, text in table.items():
            assert "{" not in text and "outbreak" not in text.lower(), (lang, key)
            if key not in ("share_location", "skip_location"):
                assert reply_writer.is_safe(text), (lang, key)
    for lang in ("hi", "kn"):
        assert all(reply_writer.is_safe(t) for t in H.WHY_LOCAL[lang].values())


def test_all_why_codes_have_local_text():
    from shared.constants import WHY_CODES
    for lang in ("hi", "kn"):
        assert set(H.WHY_LOCAL[lang]) == set(WHY_CODES)


# ------------------------------------------------------------------ bot.py helpers
def test_next_offset():
    assert botmod.next_offset([{"update_id": 5}, {"update_id": 9}, {"update_id": 7}], None) == 10
    assert botmod.next_offset([], 12) == 12


def test_telegram_errors_never_leak_the_token(monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("failed for https://api.telegram.org/botSECRET-TOKEN/getMe")

    monkeypatch.setattr(botmod.requests, "post", boom)
    api = botmod.TelegramAPI("SECRET-TOKEN")
    with caplog.at_level(logging.DEBUG):
        assert api.send_text(1, "hi") is False
    assert "SECRET-TOKEN" not in caplog.text


def test_polling_loop_handles_updates_and_survives_errors(monkeypatch):
    seen, polls = [], []

    class API:
        def get_updates(self, offset):
            polls.append(offset)
            if len(polls) == 1:
                return [{"update_id": 1}, {"update_id": 2}]
            if len(polls) == 2:
                return None  # network problem
            return []

    class Handler:
        def handle_update(self, u):
            seen.append(u["update_id"])
            if u["update_id"] == 1:
                raise RuntimeError("bad update")

    botmod.run_polling(API(), Handler(), should_stop=lambda: len(polls) >= 4, retry_delay=0)
    assert seen == [1, 2] and polls[1] == 3


def test_send_text_without_a_token_returns_false(monkeypatch):
    monkeypatch.setattr(botmod.Config, "TELEGRAM_BOT_TOKEN", "")
    assert botmod.send_text(1, "hello") is False