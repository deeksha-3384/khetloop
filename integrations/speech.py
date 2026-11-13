"""Speech integration (P4): speech-to-text (Groq Whisper) and text-to-speech (gTTS).

Contract (signatures never change, providers can):
    stt(audio_path, lang)          -> envelope, data = {"text", "language"}
    tts(text, lang, out_path=None) -> envelope, data = {"audio_path"}
Both functions are synchronous and never raise.

SPEECH_PROVIDER: "groq_gtts" (recommended) or "gemini_gtts" (legacy default in
.env.example). Both currently use Groq Whisper for STT because Groq won our
Kannada/Hindi test; Gemini audio is not implemented. TTS is always gTTS.
"""
import logging
import os
import re
import subprocess
import uuid
from collections import Counter
from pathlib import Path

import requests
from dotenv import load_dotenv

from integrations.common import fail, ok
from shared.constants import LANGUAGES

load_dotenv(override=True)  # contract C20

log = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
PRIMARY_MODEL = "whisper-large-v3"            # more accurate; change here if Groq retires it
FALLBACK_MODEL = "whisper-large-v3-turbo"     # used if the primary call fails or gives junk
TIMEOUT_S = 8                                 # contract: 8 seconds per external call
FFMPEG_TIMEOUT_S = 20
MAX_WAV_BYTES = 24 * 1024 * 1024              # Groq free tier limit is 25 MB
ALLOWED_EXT = {".oga", ".ogg", ".opus", ".mp3", ".wav", ".m4a", ".webm"}

# --- Junk-transcript guards. Tuned on 12 clips (real speech vs silence/noise):
# real speech had avg_logprob >= -0.21 and no_speech_prob <= 0.05; every junk output
# had avg_logprob <= -0.47 or repeated words. Revisit if real notes get rejected.
SILENCE_MAX_DB = -50.0        # quieter than this = no speech (digital silence is -91 dB)
MIN_AVG_LOGPROB = -0.40
MAX_NO_SPEECH_PROB = 0.5

# A neutral vocabulary hint fixed Hindi/Kannada spelling errors in our tests.
# It must NEVER contain severity words (spreading, dying, whole field...): in a test the
# model echoed hint words into the transcript, which could trigger wrong escalation.
# NOTE: the hint makes junk look MORE confident, so the guards above matter.
USE_STT_HINT = True
STT_HINTS = {
    "kn": "ಟೊಮೆಟೊ ಎಲೆ, ಕಂದು ಕಲೆಗಳು, ಹೊಲ",
    "hi": "टमाटर के पत्ते, भूरे धब्बे, खेत",
    "en": "tomato leaves, brown spots, field",
}


def _tmp_dir() -> Path:
    path = Path(os.getenv("TMP_DIR", "./tmp"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _has_repeated_words(text: str) -> bool:
    """True if one word (compared by its first 4 characters) makes up most of the text."""
    words = [re.sub(r"[^\w]+", "", w) for w in text.split()]
    words = [w for w in words if w]
    if len(words) < 3:
        return False
    _, count = Counter(w[:4] for w in words).most_common(1)[0]
    return count >= 3 and count / len(words) >= 0.5


def _is_junk(text: str, segments) -> bool:
    """Decide whether a transcript is probably invented by the model."""
    if _has_repeated_words(text):
        return True
    segs = [s for s in (segments or []) if isinstance(s, dict)]
    if segs:
        logprobs = [s["avg_logprob"] for s in segs if isinstance(s.get("avg_logprob"), (int, float))]
        no_speech = [s["no_speech_prob"] for s in segs if isinstance(s.get("no_speech_prob"), (int, float))]
        if logprobs and sum(logprobs) / len(logprobs) < MIN_AVG_LOGPROB:
            return True
        if no_speech and sum(no_speech) / len(no_speech) > MAX_NO_SPEECH_PROB:
            return True
    return False


def _convert_to_wav(src: Path, dst: Path):
    """Convert any supported audio to 16 kHz mono wav. Returns the loudest level in dB
    (float, -inf for digital silence) or None if it could not be measured."""
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1",
         "-af", "volumedetect", str(dst)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=FFMPEG_TIMEOUT_S,
    )
    if proc.returncode != 0 or not dst.is_file():
        raise RuntimeError("ffmpeg conversion failed")
    match = re.search(r"max_volume:\s*(-inf|-?\d+(?:\.\d+)?)\s*dB", proc.stderr)
    return float(match.group(1)) if match else None


def _call_groq(wav: Path, lang: str, key: str, model: str, hint):
    """One Groq call. Returns (text, segments)."""
    data = {"model": model, "language": lang, "response_format": "verbose_json",
            "temperature": "0"}
    if hint:
        data["prompt"] = hint
    with open(wav, "rb") as f:
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (wav.name, f, "audio/wav")},
            data=data,
            timeout=TIMEOUT_S,
        )
    resp.raise_for_status()
    body = resp.json()
    return (body.get("text") or "").strip(), body.get("segments") or []


def _transcribe(wav: Path, lang: str, key: str) -> str:
    """Try the accurate model (with hint), then the fast model (no hint).
    Returns "" if nothing usable came back. Raises only if every call failed."""
    hint = STT_HINTS.get(lang) if USE_STT_HINT else None
    attempts = [(PRIMARY_MODEL, hint), (FALLBACK_MODEL, None)]
    any_call_worked = False
    for model, model_hint in attempts:
        try:
            text, segments = _call_groq(wav, lang, key, model, model_hint)
        except Exception as exc:
            log.warning("STT call failed (%s): %s", model, type(exc).__name__)
            continue
        any_call_worked = True
        if text and not _is_junk(text, segments):
            return text
    if not any_call_worked:
        raise RuntimeError("all STT calls failed")
    return ""


def stt(audio_path, lang) -> dict:
    wav = None
    try:
        if lang not in LANGUAGES:
            return fail("STT_FAILED", "Unsupported language")
        if not audio_path:
            return fail("STT_FAILED", "Audio file missing or empty")
        src = Path(str(audio_path))
        if not src.is_file() or src.stat().st_size == 0:
            return fail("STT_FAILED", "Audio file missing or empty")
        if src.suffix.lower() not in ALLOWED_EXT:
            return fail("STT_FAILED", "Unsupported audio format")
        key = os.getenv("GROQ_API_KEY")
        if not key:
            return fail("STT_FAILED", "Speech service not configured")

        wav = _tmp_dir() / f"stt_{uuid.uuid4().hex[:8]}.wav"
        try:
            max_db = _convert_to_wav(src, wav)
        except FileNotFoundError:
            return fail("STT_FAILED", "ffmpeg is not installed")
        if max_db is not None and max_db <= SILENCE_MAX_DB:
            return fail("STT_FAILED", "No speech detected")
        if wav.stat().st_size > MAX_WAV_BYTES:
            return fail("STT_FAILED", "Audio too long")

        text = _transcribe(wav, lang, key)
        if not text:
            return fail("STT_FAILED", "No speech detected")
        return ok({"text": text, "language": lang}, "live")
    except Exception as exc:
        log.warning("STT failed: %s", type(exc).__name__)
        return fail("STT_FAILED", "Speech recognition failed")
    finally:
        try:
            if wav is not None and wav.exists():
                wav.unlink()
        except Exception:
            pass


def tts(text, lang, out_path=None) -> dict:
    try:
        from gtts import gTTS  # imported here so a missing package never breaks import

        if lang not in LANGUAGES:
            return fail("INTERNAL_ERROR", "Unsupported language")
        if not isinstance(text, str) or not text.strip():
            return fail("INTERNAL_ERROR", "No text to speak")
        if out_path:
            target = Path(str(out_path))
            target.parent.mkdir(parents=True, exist_ok=True)
        else:
            target = _tmp_dir() / f"tts_{uuid.uuid4().hex[:8]}.mp3"
        gTTS(text=text.strip(), lang=lang, timeout=TIMEOUT_S).save(str(target))
        if not target.is_file() or target.stat().st_size == 0:
            return fail("INTERNAL_ERROR", "Speech synthesis produced no audio")
        return ok({"audio_path": str(target)}, "live")
    except Exception as exc:
        log.warning("TTS failed: %s", type(exc).__name__)
        return fail("INTERNAL_ERROR", "Speech synthesis unavailable")