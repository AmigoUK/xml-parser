import click
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
            "nav_blueprints": set(app.blueprints),
        }

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok", version=__version__)

    from . import models  # noqa: F401  (rejestracja modeli dla Alembic)
    from .services.seed import reset_demo, seed_base, seed_demo

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(models.User, int(user_id))

    @app.cli.command("seed")
    def seed_cmd():
        """Jednostki, konto admin, klucz demo (+ kartoteka demo w DEMO_MODE)."""
        seed_base()
        if app.config["DEMO_MODE"]:
            seed_demo()
        click.echo("Seed OK")

    @app.cli.command("reset-demo")
    def reset_demo_cmd():
        """Czyści dane i przywraca stan demo."""
        try:
            reset_demo()
        except RuntimeError as e:
            click.echo(str(e), err=True)
            raise SystemExit(1)
        click.echo("Demo zresetowane")

    from flask import render_template
    from .api import bp as api_bp
    csrf.exempt(api_bp)
    app.register_blueprint(api_bp)

    @app.get("/api/docs")
    def api_docs():
        return render_template("api_docs.html")

    from .web import register_web
    register_web(app)

    return app
