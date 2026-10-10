from flask import Flask, jsonify

from .config import PLACEHOLDER_SECRET_KEYS, Config
from .extensions import csrf, db, login_manager, migrate
from .version import __version__


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    app.config["MAX_CONTENT_LENGTH"] = app.config["MAX_DOCUMENT_BYTES"] + 64 * 1024

    if app.config.get("SECRET_KEY") in PLACEHOLDER_SECRET_KEYS and not (
        app.config.get("TESTING") or app.config.get("DEBUG")
    ):
        raise RuntimeError(
            "SECRET_KEY nie jest ustawiony (lub ma wartość domyślną). Wygeneruj klucz: "
            "python -c \"import secrets;print(secrets.token_hex(32))\" i wpisz go do .env."
        )

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    @app.context_processor
    def inject_globals():
        return {
            "APP_VERSION": __version__,
            "REPO_URL": app.config["REPO_URL"],
            "DEMO_MODE": app.config["DEMO_MODE"],
        }

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok", version=__version__)

    return app
