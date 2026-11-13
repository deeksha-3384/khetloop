"""Live smoke test of P4's modules.  Needs internet, GROQ_API_KEY and ffmpeg on PATH.
  python -m tests.backend.try_integrations
  python -m tests.backend.try_integrations path\\to\\voice_note.oga kn      (also tests speech-to-text)"""
import json
import os
import sys

from backend.config import Config  # noqa: F401  (loads .env)
from integrations import speech, weather

print("weather:", json.dumps(weather.get_forecast(13.14, 78.13), ensure_ascii=False)[:500])
res = speech.tts("Hello farmer, this is a test of the spoken reply.", "en")
print("tts    :", res)
if res.get("ok"):
    print("tts file exists:", os.path.exists(res["data"]["audio_path"]))
if len(sys.argv) > 1:
    lang = sys.argv[2] if len(sys.argv) > 2 else "kn"
    print("stt    :", json.dumps(speech.stt(sys.argv[1], lang), ensure_ascii=False))