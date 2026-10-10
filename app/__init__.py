import hmac

import click
from flask import Flask, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import PLACEHOLDER_SECRET_KEYS, Config
from .extensions import csrf, db, login_manager, migrate
from .version import __version__

# Alpine.js (standardowy build) wylicza wyrażenia z atrybutów przez konstruktor Function, stąd 'unsafe-eval'
# w script-src; inline <script> i atrybuty on* są niedozwolone. Style inline (atrybuty style, :style Alpine,
# Swagger UI) wymagają 'unsafe-inline' w style-src.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}


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

    from .services.storage import check_storage_dir
    check_storage_dir(app.config["STORAGE_DIR"])  # BE-9: brak zapisu = błąd przy starcie, nie 500 przy uploadzie

    proxies = int(app.config.get("TRUSTED_PROXY_COUNT") or 0)
    if proxies > 0:  # OPS-8: X-Forwarded-* tylko od zaufanych proxy
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxies, x_proto=proxies, x_host=proxies, x_port=proxies)

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

    @app.after_request
    def security_headers(response):
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.get("/healthz")
    def healthz():
        try:
            db.session.execute(db.text("SELECT 1"))
        except Exception:  # noqa: BLE001 - nie ujawniamy szczegółów błędu w odpowiedzi
            app.logger.exception("healthz: brak połączenia z bazą")
            return jsonify(status="error", version=__version__, db="error"), 503
        return jsonify(status="ok", version=__version__, db="ok")

    from . import models  # noqa: F401  (rejestracja modeli dla Alembic)
    from .services.seed import reset_demo, seed_base, seed_demo

    @login_manager.user_loader
    def load_user(user_id):
        uid, _, token = (user_id or "").partition(":")
        if not uid.isdigit() or not token:
            return None  # ciasteczko w starym formacie albo uszkodzone
        user = db.session.get(models.User, int(uid))
        if user is None or not user.session_token or not hmac.compare_digest(user.session_token, token):
            return None
        return user

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
