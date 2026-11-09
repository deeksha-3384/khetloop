"""
Flask application factory.
Run with:  python -m backend.app
"""
import logging

from flask import Flask
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from backend.config import Config
from backend.routes.health import bp as health_bp
from backend.utils.responses import err

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("khetloop")


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB upload limit

    # Lets the frontend (served on another port) call this API.
    CORS(app)

    # Each route file adds its blueprint here as we build it.
    app.register_blueprint(health_bp)

    @app.errorhandler(HTTPException)
    def handle_http_error(e: HTTPException):
        code = {400: "INVALID_REQUEST", 401: "UNAUTHORIZED", 404: "NOT_FOUND", 409: "CONFLICT"}.get(
            e.code, "INTERNAL_ERROR"
        )
        return err(code, e.description or e.name, e.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(e: Exception):
        # Log the real error on the server, return a clean envelope to the client.
        log.exception("Unhandled error")
        return err("INTERNAL_ERROR", "Something went wrong on the server", 500)

    return app


app = create_app()

if __name__ == "__main__":
    log.info("Config: %s", Config.summary())
    app.run(host="0.0.0.0", port=Config.APP_PORT, debug=True)