"""
Flask application factory.
Run with:  python -m backend.app
"""
import logging

from flask import Flask
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from backend.config import Config
from backend.routes.demo import bp as demo_bp
from backend.routes.expert import bp as expert_bp
from backend.routes.farms import bp as farms_bp
from backend.routes.health import bp as health_bp
from backend.routes.radar import bp as radar_bp
from backend.routes.reminders import bp as reminders_bp
from backend.routes.reports import bp as reports_bp
from backend.utils.responses import err

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("khetloop")


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB upload limit

    CORS(app)  # lets the frontend (served on another port) call this API

    for bp in (health_bp, reports_bp, farms_bp, expert_bp, radar_bp, reminders_bp, demo_bp):
        app.register_blueprint(bp)

    @app.errorhandler(HTTPException)
    def handle_http_error(e: HTTPException):
        code = {400: "INVALID_REQUEST", 401: "UNAUTHORIZED", 404: "NOT_FOUND", 405: "INVALID_REQUEST",
                409: "CONFLICT", 413: "INVALID_REQUEST"}.get(e.code, "INTERNAL_ERROR")
        return err(code, e.description or e.name, e.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(e: Exception):
        if type(e).__name__ == "DBError":  # P2's database error class, detected by name
            log.warning("database error: %s", getattr(e, "code", "DB_ERROR"))
            return err("DB_ERROR", "A database error occurred", 500)
        log.exception("Unhandled error")
        return err("INTERNAL_ERROR", "Something went wrong on the server", 500)

    return app


app = create_app()

if __name__ == "__main__":
    log.info("Config: %s", Config.summary())
    app.run(host="0.0.0.0", port=Config.APP_PORT, debug=True)