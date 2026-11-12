"""
Leaf photo assessment. File name and analyse_leaf() signature follow the contract.
Tries Groq first, then Gemini. Never raises. The result is NEVER a confirmed diagnosis.
Imported by: backend/services/report_pipeline.py

Success: {"ok": True, "provider": "groq", "assessment": {suspected_issue, confidence_band,
          image_quality, visible_symptoms, confirmed: False}}   (decision is added by decide())
Failure: {"ok": False, "error": {"code": "...", "message": "..."}}
"""
import base64
import io
import json
import logging
import re

import requests

from backend.config import Config
from shared.constants import CONFIDENCE_BANDS, IMAGE_QUALITIES, ISSUES

log = logging.getLogger("khetloop.vision")

PROVIDER_ORDER = ["groq", "gemini"]  # flip the order here if you prefer Gemini first
DEFAULT_GROQ_MODEL = "qwen/qwen3.8-27b"
TIMEOUT_S = 25
MAX_SIDE_PX = 1280
MAX_RAW_BYTES = 3 * 1024 * 1024


def _fail(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


def _sniff_mime(b: bytes):
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def _prepare_image(image_bytes: bytes):
    """Validate, fix rotation, shrink and re-encode as JPEG. Raises ValueError if unusable."""
    if not image_bytes:
        raise ValueError("Empty image")
    sniffed = _sniff_mime(image_bytes)
    try:
        from PIL import Image, ImageOps
    except ImportError:
        if sniffed is None:
            raise ValueError("Not a supported image (use JPEG, PNG, WebP or GIF)")
        if len(image_bytes) > MAX_RAW_BYTES:
            raise ValueError("Image too large (install Pillow to resize)")
        return image_bytes, sniffed
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue(), "image/jpeg"
    except Exception as e:
        raise ValueError("Not a supported image (use JPEG, PNG, WebP or GIF)") from e


def _build_prompt(crop: str, transcript) -> str:
    said = (transcript or "").strip()[:500] or "(nothing)"
    return (
        "You are a plant-health image analyst helping a small farmer. Look at the leaf photo.\n"
        "Crop the farmer says this is: %s\n"
        "What the farmer said (context only, may be in Kannada or Hindi): %s\n\n"
        "Reply with ONE JSON object and nothing else, exactly these keys:\n"
        '{"suspected_issue": one of [%s],\n'
        ' "confidence_band": one of ["high","medium","low"],\n'
        ' "image_quality": one of ["good","poor"],\n'
        ' "visible_symptoms": [up to 4 short phrases describing ONLY what is visible in the photo]}\n\n'
        "Rules:\n"
        "- image_quality is \"poor\" if the photo is blurry, dark, too far away, or no leaf is clearly visible.\n"
        "- Use \"unknown\" if you cannot tell. Use \"healthy\" only if the leaf clearly shows no symptoms.\n"
        "- Be conservative: use \"low\" confidence when unsure. You are NOT giving a confirmed diagnosis.\n"
        "- Do NOT give treatment advice, chemical names or dosages. Describe symptoms only."
    ) % (crop, said, ", ".join('"%s"' % i for i in ISSUES))


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _parse_model_json(text: str) -> dict:
    """Find the JSON object in a model reply. Ignores <think> blocks, code fences and extra text."""
    text = _THINK_RE.sub("", text or "").strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    best = None
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
        except ValueError:
            continue
        if isinstance(obj, dict) and "suspected_issue" in obj:
            best = obj  # keep the last matching object
    if best is None:
        raise ValueError("model reply contained no usable JSON")
    return best


def _normalise(raw: dict) -> dict:
    """Force every field into the contract values. Unknown values become the safe default."""
    issue = raw.get("suspected_issue")
    band = raw.get("confidence_band")
    quality = raw.get("image_quality")
    symptoms = raw.get("visible_symptoms")
    if not isinstance(symptoms, list):
        symptoms = []
    clean = [str(s).strip()[:80] for s in symptoms if str(s).strip()][:5]
    return {
        "suspected_issue": issue if issue in ISSUES else "unknown",
        "confidence_band": band if band in CONFIDENCE_BANDS else "low",
        "image_quality": quality if quality in IMAGE_QUALITIES else "poor",
        "visible_symptoms": clean,
        "confirmed": False,  # AI output is never a confirmed diagnosis
    }


def _call_groq(b64: str, mime: str, prompt: str) -> str:
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": "Bearer " + Config.GROQ_API_KEY, "Content-Type": "application/json"},
        json={
            "model": Config.GROQ_MODEL or DEFAULT_GROQ_MODEL,
            "temperature": 0.2,
            "max_completion_tokens": 1500,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (mime, b64)}},
            ]}],
        },
        timeout=TIMEOUT_S,
    )
    if r.status_code != 200:
        log.warning("groq HTTP %s: %s", r.status_code, r.text[:200])
        raise RuntimeError("groq returned HTTP %s" % r.status_code)
    return r.json()["choices"][0]["message"].get("content") or ""


def _call_gemini(b64: str, mime: str, prompt: str) -> str:
    r = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % Config.GEMINI_MODEL,
        headers={"x-goog-api-key": Config.GEMINI_API_KEY, "Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": mime, "data": b64}}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        },
        timeout=TIMEOUT_S,
    )
    if r.status_code != 200:
        log.warning("gemini HTTP %s: %s", r.status_code, r.text[:200])
        raise RuntimeError("gemini returned HTTP %s" % r.status_code)
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def analyse_leaf(image_bytes: bytes, crop: str, transcript) -> dict:
    try:
        data, mime = _prepare_image(image_bytes)
    except ValueError as e:
        return _fail("INVALID_REQUEST", str(e))

    callers = {"groq": _call_groq, "gemini": _call_gemini}
    keys = {"groq": Config.GROQ_API_KEY, "gemini": Config.GEMINI_API_KEY}
    providers = [name for name in PROVIDER_ORDER if keys.get(name)]
    if not providers:
        return _fail("AI_UNAVAILABLE", "No vision API key is configured")

    b64 = base64.b64encode(data).decode("ascii")
    prompt = _build_prompt(crop, transcript)
    errors = []
    for name in providers:
        try:
            text = callers[name](b64, mime, prompt)
            return {"ok": True, "provider": name, "assessment": _normalise(_parse_model_json(text))}
        except Exception as e:  # never raise out of this function
            log.warning("vision provider %s failed: %s", name, type(e).__name__)
            errors.append("%s: %s" % (name, type(e).__name__))
    return _fail("AI_UNAVAILABLE", "All vision providers failed (" + "; ".join(errors) + ")")