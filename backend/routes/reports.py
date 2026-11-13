"""Endpoints 1 and 2: submit a report (runs the full pipeline), get a report."""
import logging
import os
import time

from flask import Blueprint, request

from backend.config import Config
from backend.services import report_pipeline
from backend.utils import deps
from backend.utils.responses import err, ok
from shared.constants import LANGUAGES

log = logging.getLogger("khetloop.routes")
bp = Blueprint("reports", __name__)
AUDIO_EXTENSIONS = (".oga", ".ogg", ".mp3", ".wav", ".m4a")


def _remove(path):
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


@bp.post("/api/reports")
def create_report():
    farm_id = (request.form.get("farm_id") or "").strip()
    image = request.files.get("image")
    if not farm_id:
        return err("INVALID_REQUEST", "farm_id is required", 400)
    if image is None or not image.filename:
        return err("INVALID_REQUEST", "image is required", 400)
    language = (request.form.get("language") or "").strip() or None
    if language is not None and language not in LANGUAGES:
        return err("INVALID_REQUEST", "language must be one of kn, hi, en", 400)
    image_bytes = image.read()
    if not image_bytes:
        return err("INVALID_REQUEST", "image is empty", 400)
    voice_text = (request.form.get("voice_text") or "").strip() or None

    audio_path = None
    audio = request.files.get("audio")
    if audio is not None and audio.filename:
        ext = os.path.splitext(audio.filename)[1].lower()
        ext = ext if ext in AUDIO_EXTENSIONS else ".oga"
        os.makedirs(Config.TMP_DIR, exist_ok=True)
        audio_path = os.path.join(Config.TMP_DIR, "upload_%d%s" % (time.time_ns(), ext))
        audio.save(audio_path)

    result = None
    try:
        result = report_pipeline.run_pipeline(
            farm_id, image_bytes, image.filename, audio_path, voice_text, language, deps=deps.pipeline_deps())
    except LookupError:
        return err("NOT_FOUND", "Farm not found", 404)
    except ValueError:
        return err("INVALID_REQUEST", "The uploaded file is not a valid image", 400)
    finally:
        _remove(audio_path)
    _remove(result.get("audio_path") if result else None)  # the API does not serve spoken replies
    return ok(result["report"], 201)


@bp.get("/api/reports/<report_id>")
def get_report(report_id):
    report = deps.get_db().get_report(report_id)
    if report is None:
        return err("NOT_FOUND", "Report not found", 404)
    return ok(report)