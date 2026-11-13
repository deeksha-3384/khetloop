import pytest
import requests

from integrations import speech


def seg(lp=-0.1, nsp=0.0):
    return {"avg_logprob": lp, "no_speech_prob": nsp, "compression_ratio": 1.3}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TMP_DIR", str(tmp_path / "tmp"))
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    def fake_convert(src, dst):
        dst.write_bytes(b"RIFFfakewav")
        return -20.0

    monkeypatch.setattr(speech, "_convert_to_wav", fake_convert)


@pytest.fixture
def audio(tmp_path):
    p = tmp_path / "voice.oga"
    p.write_bytes(b"fake-opus-bytes")
    return str(p)


def groq_returns(monkeypatch, *results):
    """Each item is (text, segments) or an Exception to raise. Records calls."""
    calls = []
    queue = list(results)

    def fake(wav, lang, key, model, hint):
        calls.append({"model": model, "hint": hint, "lang": lang})
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(speech, "_call_groq", fake)
    return calls


# ---------- STT success ----------
def test_stt_success(monkeypatch, audio):
    groq_returns(monkeypatch, ("ಕಲೆಗಳು ಹರಡುತ್ತಿವೆ", [seg()]))
    r = speech.stt(audio, "kn")
    assert r == {"ok": True, "data": {"text": "ಕಲೆಗಳು ಹರಡುತ್ತಿವೆ", "language": "kn"},
                 "data_source": "live", "error": None}


def test_primary_model_gets_hint_fallback_does_not(monkeypatch, audio):
    calls = groq_returns(monkeypatch, requests.exceptions.Timeout("slow"),
                         ("मेरे पत्ते पर धब्बे हैं", [seg()]))
    r = speech.stt(audio, "hi")
    assert r["ok"] is True
    assert calls[0]["model"] == speech.PRIMARY_MODEL and calls[0]["hint"] == speech.STT_HINTS["hi"]
    assert calls[1]["model"] == speech.FALLBACK_MODEL and calls[1]["hint"] is None


def test_all_calls_fail(monkeypatch, audio):
    groq_returns(monkeypatch, requests.exceptions.ConnectionError("x"),
                 requests.exceptions.ConnectionError("x"))
    r = speech.stt(audio, "kn")
    assert r["ok"] is False and r["error"]["code"] == "STT_FAILED"
    assert r["data"] is None and r["data_source"] is None


# ---------- junk guards ----------
def test_low_confidence_junk_rejected(monkeypatch, audio):
    groq_returns(monkeypatch, ("ಸಂಖಗಳ ಸಾಗಳ ಗೇರು", [seg(lp=-1.3)]), ("ಠಠ ಠ", [seg(lp=-1.0)]))
    r = speech.stt(audio, "kn")
    assert r["ok"] is False and r["error"]["message"] == "No speech detected"


def test_repetition_junk_rejected(monkeypatch, audio):
    groq_returns(monkeypatch, ("प्रश्न प्रश्न प्रश्न", [seg(lp=-0.5)]),
                 ("प्रश्न प्रश्न प्रश्न", [seg(lp=-0.5)]))
    assert speech.stt(audio, "hi")["ok"] is False


def test_primary_junk_but_fallback_good(monkeypatch, audio):
    groq_returns(monkeypatch, ("ಶಾಗವರತದದ ಶಾಗವರತದ ಶಾಗವರತದ", [seg(lp=-0.6)]),
                 ("ಕಲೆಗಳು ಹರಡುತ್ತಿವೆ", [seg()]))
    r = speech.stt(audio, "kn")
    assert r["ok"] is True and r["data"]["text"] == "ಕಲೆಗಳು ಹರಡುತ್ತಿವೆ"


def test_empty_text_is_failure(monkeypatch, audio):
    groq_returns(monkeypatch, ("", []), ("", []))
    assert speech.stt(audio, "en")["error"]["message"] == "No speech detected"


@pytest.mark.parametrize("text,lp,nsp", [
    ("ಸಂಖಗಳ ಸಾಗಳ ಗೇರು ನಾಗಳಗಳು ಴ನ್ನಯು..", -1.314, 0.001),
    ("प्रश्नान पर प्रश्नान पर प्रश्नान", -0.472, 0.002),
    ("ಸಿಮಿಲಿದಿದಾಗಡಿಂದರಿಒಗಾಂಚೇ ಸಡಾರುವಾದಿದರುದರಾಗಲೋಗೆ", -1.185, 0.480),
    ("ಶಾಗವರತದದ ಶಾಗವರತದ ಶಾಗವರತದ", -0.600, 0.055),
    ("प्रश्न प्रश्न प्रश्न", -0.555, 0.137),
])
def test_known_junk_is_detected(text, lp, nsp):
    assert speech._is_junk(text, [seg(lp, nsp)]) is True


@pytest.mark.parametrize("text,lp,nsp", [
    ("ನಮಸ್ಕರಾ, ಹೇಗಿದಿರಾ", -0.162, 0.040),
    ("ನನ್ನ ಟಮೇಟೋ ಎಲೆಗಳ ಮೇಲೆ ಕಂದು ಕಲೆಗಳು ಬರುತ್ತಿದೆ", -0.054, 0.0),
    ("ಕಲೆಗಳು ಇಡಿ ಹೊಲದಲ್ಲಿ ಹರಡುತ್ತಿವೆ", -0.055, 0.0),
    ("ಕಲೆಗಳು ಇಡಿ ಹೋಲದಲ್ಲಿ ಹರಡುತ್ತಿವೆ", -0.072, 0.0),
    ("मेरे टमाटर के पत्तों पर भूरे धब्बे आ रहे हैं", -0.040, 0.001),
    ("धब्बे पूरे खेत में तेजी से फैल रहे हैं", -0.062, 0.002),
    ("Brown spots are spreading on my tomato leaves.", -0.209, 0.044),
])
def test_real_speech_is_kept(text, lp, nsp):
    assert speech._is_junk(text, [seg(lp, nsp)]) is False


def test_missing_segment_data_does_not_crash():
    assert speech._is_junk("brown spots", None) is False
    assert speech._is_junk("brown spots", []) is False
    assert speech._is_junk("brown spots", ["bad", 3]) is False


# ---------- silence / input problems ----------
@pytest.mark.parametrize("level", [-91.0, float("-inf"), -50.0])
def test_silent_audio_never_reaches_groq(monkeypatch, audio, level):
    monkeypatch.setattr(speech, "_convert_to_wav",
                        lambda s, d: (d.write_bytes(b"x"), level)[1])
    calls = groq_returns(monkeypatch)
    r = speech.stt(audio, "kn")
    assert r["ok"] is False and r["error"]["message"] == "No speech detected"
    assert calls == []


def test_missing_and_empty_file(tmp_path):
    assert speech.stt(str(tmp_path / "nope.oga"), "kn")["ok"] is False
    empty = tmp_path / "e.oga"
    empty.write_bytes(b"")
    assert speech.stt(str(empty), "kn")["ok"] is False
    assert speech.stt(None, "kn")["ok"] is False


def test_unsupported_format(tmp_path):
    p = tmp_path / "doc.txt"
    p.write_bytes(b"hello")
    r = speech.stt(str(p), "kn")
    assert r["error"]["message"] == "Unsupported audio format"


def test_unsupported_language(audio):
    assert speech.stt(audio, "fr")["error"]["message"] == "Unsupported language"


def test_no_api_key(monkeypatch, audio):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert speech.stt(audio, "kn")["error"]["message"] == "Speech service not configured"


def test_ffmpeg_not_installed(monkeypatch, audio):
    def boom(src, dst):
        raise FileNotFoundError("ffmpeg")
    monkeypatch.setattr(speech, "_convert_to_wav", boom)
    assert speech.stt(audio, "kn")["error"]["message"] == "ffmpeg is not installed"


def test_ffmpeg_conversion_error(monkeypatch, audio):
    def boom(src, dst):
        raise RuntimeError("ffmpeg conversion failed")
    monkeypatch.setattr(speech, "_convert_to_wav", boom)
    r = speech.stt(audio, "kn")
    assert r["ok"] is False and r["error"]["code"] == "STT_FAILED"


def test_temp_wav_is_deleted(monkeypatch, audio, tmp_path):
    groq_returns(monkeypatch, ("brown spots", [seg()]))
    speech.stt(audio, "en")
    leftovers = list((tmp_path / "tmp").glob("stt_*.wav"))
    assert leftovers == []


def test_hints_contain_no_severity_words():
    banned = ["ಹರಡ", "ಸಾಯ", "ಇಡೀ", "फैल", "मर रहे", "मरने", "पूरे", "पूरा",
              "spread", "dying", "whole", "all plants", "many plants"]
    for lang, hint in speech.STT_HINTS.items():
        for word in banned:
            assert word not in hint.lower(), f"{lang} hint contains severity word {word}"


def test_never_raises_on_weird_input():
    for args in [(None, None), (123, "kn"), ([], "hi"), ("", "en"), (object(), "kn")]:
        r = speech.stt(*args)
        assert r["ok"] is False


# ---------- TTS ----------
class FakeGTTS:
    saved = []

    def __init__(self, text, lang, timeout=None):
        self.text, self.lang = text, lang
        FakeGTTS.saved.append((text, lang, timeout))

    def save(self, path):
        with open(path, "wb") as f:
            f.write(b"ID3fake-mp3")


def test_tts_success_default_path(monkeypatch, tmp_path):
    monkeypatch.setattr("gtts.gTTS", FakeGTTS)
    r = speech.tts("ನಮಸ್ಕಾರ", "kn")
    assert r["ok"] is True and r["data_source"] == "live" and r["error"] is None
    path = r["data"]["audio_path"]
    assert path.endswith(".mp3") and str(tmp_path / "tmp") in path
    assert FakeGTTS.saved[-1][1] == "kn" and FakeGTTS.saved[-1][2] == speech.TIMEOUT_S


def test_tts_respects_out_path(monkeypatch, tmp_path):
    monkeypatch.setattr("gtts.gTTS", FakeGTTS)
    target = tmp_path / "sub" / "reply.mp3"
    r = speech.tts("नमस्ते", "hi", out_path=str(target))
    assert r["ok"] is True and r["data"]["audio_path"] == str(target) and target.exists()


def test_tts_failure_is_graceful(monkeypatch):
    class Boom(FakeGTTS):
        def save(self, path):
            raise requests.exceptions.ConnectionError("offline")
    monkeypatch.setattr("gtts.gTTS", Boom)
    r = speech.tts("hello", "en")
    assert r["ok"] is False and r["data"] is None and r["error"]["code"] == "INTERNAL_ERROR"


@pytest.mark.parametrize("text,lang", [("", "kn"), ("   ", "hi"), (None, "en"), ("hi", "fr"), (5, "en")])
def test_tts_bad_input(text, lang):
    assert speech.tts(text, lang)["ok"] is False