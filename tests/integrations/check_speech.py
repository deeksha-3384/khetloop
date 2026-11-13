"""Manual check of the REAL speech module (P4). NOT a pytest test; run by hand.

Usage (from repo root, venv active, internet on):
    python -m tests.integrations.check_speech

Runs stt() on your recorded clips and tts() on three sentences. Writes a UTF-8
report to tmp/speech_check.txt and saves mp3 files in tmp/tts_check/ to listen to.
"""
from pathlib import Path

from integrations import speech

SAMPLES = Path("tmp") / "stt_samples"
REPORT = Path("tmp") / "speech_check.txt"
TTS_DIR = Path("tmp") / "tts_check"

STT_CLIPS = [
    ("kn_1.ogg", "kn"), ("kn_2.ogg", "kn"), ("kn_noisy.ogg", "kn"), ("kn_hello.ogg", "kn"),
    ("hi_1.ogg", "hi"), ("hi_2.ogg", "hi"), ("en_1.ogg", "en"),
    ("noise_only.ogg", "kn"), ("noise_only.ogg", "hi"),
    ("silence.wav", "kn"),
]

TTS_LINES = [
    ("kn", "ನಿಮ್ಮ ಟೊಮೆಟೊ ಎಲೆಗಳ ಫೋಟೋ ಸಿಕ್ಕಿದೆ. ಇದು ಪ್ರಾಥಮಿಕ ಅಂದಾಜು ಮಾತ್ರ, ಖಚಿತ ರೋಗನಿರ್ಣಯ ಅಲ್ಲ."),
    ("hi", "आपके टमाटर के पत्तों की फोटो मिल गई है। यह केवल प्रारंभिक अनुमान है, पक्का निदान नहीं।"),
    ("en", "We received your tomato leaf photo. This is a preliminary assessment, not a confirmed diagnosis."),
]


def main() -> None:
    lines = ["=== STT ==="]
    for name, lang in STT_CLIPS:
        path = SAMPLES / name
        if not path.exists():
            lines.append(f"[{name} | {lang}] SKIPPED (file not found)")
            continue
        r = speech.stt(str(path), lang)
        if r["ok"]:
            lines.append(f"[{name} | {lang}] OK: {r['data']['text']}")
        else:
            lines.append(f"[{name} | {lang}] FAILED: {r['error']['code']} - {r['error']['message']}")

    lines.append("")
    lines.append("=== TTS ===")
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    for lang, text in TTS_LINES:
        r = speech.tts(text, lang, out_path=str(TTS_DIR / f"tts_{lang}.mp3"))
        if r["ok"]:
            lines.append(f"[{lang}] OK: {r['data']['audio_path']}")
        else:
            lines.append(f"[{lang}] FAILED: {r['error']['code']} - {r['error']['message']}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report written to {REPORT}")


if __name__ == "__main__":
    main()