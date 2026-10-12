import hmac

import click
from flask import Flask, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import PLACEHOLDER_SECRET_KEYS, Config
from .extensions import csrf, db, login_manager, migrate
from .ids import BoundedIntConverter, parse_id
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
    # `<int:…>` w adresach ograniczony do zakresu kolumny id (przed rejestracją tras) — większe id to 404,
    # a nie OverflowError/500 na SQLite
    app.url_map.converters["int"] = BoundedIntConverter
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

    from .services.storage import check_storage_dir, get_storage
    check_storage_dir(app.config["STORAGE_DIR"])  # BE-9: brak zapisu = błąd przy starcie, nie 500 przy uploadzie

    proxies = int(app.config.get("TRUSTED_PROXY_COUNT") or 0)
    if proxies > 0:  # OPS-8: X-Forwarded-* tylko od zaufanych proxy
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxies, x_proto=proxies, x_host=proxies, x_port=proxies)
        if not app.config.get("SESSION_COOKIE_SECURE"):
            app.logger.warning("TRUSTED_PROXY_COUNT=%s (aplikacja za reverse proxy, zwykle z TLS), a "
                               "SESSION_COOKIE_SECURE=0 — ciasteczko sesji może wyjść zwykłym HTTP. Ustaw "
                               "SESSION_COOKIE_SECURE=1 i PREFERRED_URL_SCHEME=https.", proxies)
    else:
        forwarded_warned = False

        @app.before_request
        def warn_forwarded_without_trusted_proxy():
            # proxy jest, a ProxyFix wyłączony: wszystkie żądania mają adres proxy, więc limit logowań per IP
            # działa jak globalny, a adresy zewnętrzne mają schemat http — ostrzegamy raz na proces
            nonlocal forwarded_warned
            if not forwarded_warned and "X-Forwarded-For" in request.headers:
                forwarded_warned = True
                app.logger.warning("Żądanie z nagłówkiem X-Forwarded-For od %s przy TRUSTED_PROXY_COUNT=0 — "
                                   "nagłówki proxy są ignorowane (limit logowań per IP działa jak globalny). "
                                   "Ustaw TRUSTED_PROXY_COUNT na liczbę proxy przed aplikacją.",
                                   request.remote_addr)

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
        raw_uid, _, token = (user_id or "").partition(":")
        uid = parse_id(raw_uid)
        if uid is None or not token:
            return None  # ciasteczko w starym formacie albo uszkodzone
        user = db.session.get(models.User, uid)
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

    @app.cli.command("check-storage")
    def check_storage_cmd():
        """Czy każdy dokument ma plik raw/<sha256> w magazynie (po przeniesieniu danych); brak = kod 1."""
        storage = get_storage()
        rows = db.session.query(models.Document.id, models.Document.sha256).order_by(models.Document.id).all()
        missing = [(doc_id, sha) for doc_id, sha in rows if not (storage.base / sha).is_file()]
        click.echo(f"Magazyn {storage.base}: dokumentów: {len(rows)}, brakujących plików: {len(missing)}")
        for doc_id, sha in missing[:200]:
            click.echo(f"  brak: dokument #{doc_id} → raw/{sha}")
        if len(missing) > 200:
            click.echo(f"  … i {len(missing) - 200} więcej")
        if missing:
            raise SystemExit(1)

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
