"""Manual STT probe (P4). NOT a pytest test; run by hand.

Usage (from repo root, venv active):
    python -m tests.integrations.probe_stt tmp/stt_samples/kn_1.ogg kn
    python -m tests.integrations.probe_stt tmp/stt_samples/kn_1.ogg kn prompt

Writes text AND per-segment quality numbers (no_speech_prob, avg_logprob,
compression_ratio) to tmp/stt_probe_results.txt so we can choose safe thresholds.
"""
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "whisper-large-v3"
RESULTS = Path("tmp") / "stt_probe_results.txt"

PROMPTS = {
    "kn": "ಟೊಮೆಟೊ ಎಲೆ, ಕಂದು ಕಲೆಗಳು, ಹೊಲ",
    "hi": "टमाटर के पत्ते, भूरे धब्बे, खेत",
    "en": "tomato leaves, brown spots, field",
}


def to_wav(src: str):
    """Convert to 16 kHz mono wav; also return the loudest level in dB."""
    out = Path(tempfile.gettempdir()) / (Path(src).stem + "_probe.wav")
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1",
         "-af", "volumedetect", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    m = re.search(r"max_volume:\s*(-inf|-?\d+(?:\.\d+)?)\s*dB", proc.stderr)
    return out, (m.group(1) if m else "unknown")


def main() -> None:
    if len(sys.argv) not in (3, 4):
        print("Usage: python -m tests.integrations.probe_stt <audio_file> <kn|hi|en> [prompt]")
        return
    src, lang = sys.argv[1], sys.argv[2]
    use_prompt = len(sys.argv) == 4 and sys.argv[3] == "prompt"
    key = os.getenv("GROQ_API_KEY")
    if not key:
        print("GROQ_API_KEY is not set in .env")
        return
    if lang not in PROMPTS:
        print("Language must be kn, hi or en")
        return
    if not Path(src).exists():
        print(f"File not found: {src}")
        return
    try:
        wav, max_db = to_wav(src)
    except Exception as exc:
        print(f"ffmpeg conversion failed: {type(exc).__name__}")
        return

    form = {"model": MODEL, "language": lang,
            "response_format": "verbose_json", "temperature": "0"}
    if use_prompt:
        form["prompt"] = PROMPTS[lang]

    started = time.time()
    try:
        with open(wav, "rb") as f:
            resp = requests.post(
                URL, headers={"Authorization": f"Bearer {key}"},
                files={"file": (wav.name, f, "audio/wav")}, data=form, timeout=30,
            )
        took = time.time() - started
        if resp.ok:
            body = resp.json()
            text = (body.get("text") or "").strip()
            segs = body.get("segments") or []
        else:
            text, segs = f"HTTP {resp.status_code}: {resp.text[:200]}", []
    except Exception as exc:
        took = time.time() - started
        text, segs = f"REQUEST FAILED: {type(exc).__name__}", []

    tag = "PROMPT" if use_prompt else "no-prompt"
    out = [f"[{Path(src).name} | {lang} | {MODEL} | {tag} | max_volume={max_db} dB | {took:.1f}s]",
           text]
    for s in segs:
        out.append("   seg: no_speech_prob={:.3f} avg_logprob={:.3f} compression_ratio={:.2f}".format(
            s.get("no_speech_prob", -1), s.get("avg_logprob", -9), s.get("compression_ratio", -1)))
    if not segs:
        out.append("   (no segment data)")

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS, "a", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n\n")
    print(f"Done: {Path(src).name} ({tag}). Results appended to {RESULTS}")


if __name__ == "__main__":
    main()