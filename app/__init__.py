import hmac
import sys

import click
from flask import Flask, jsonify, redirect, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import PLACEHOLDER_SECRET_KEYS, Config
from .extensions import csrf, db, login_manager, migrate
from .ids import BoundedIntConverter, parse_id
from .version import __version__

# Skrypty tylko z własnego hosta: inline <script> i atrybuty on* są niedozwolone, a Alpine.js działa w buildzie CSP
# (@alpinejs/csp — wyrażenia z atrybutów parsuje sam, bez konstruktora Function), więc 'unsafe-eval' nie jest
# potrzebne. Style inline (atrybuty style, :style Alpine, Swagger UI) wymagają 'unsafe-inline' w style-src.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
# HSTS tylko dla żądań po HTTPS (za proxy: X-Forwarded-Proto przez ProxyFix) — po zwykłym HTTP przeglądarka go
# ignoruje, a host deweloperski nie powinien go dostać
HSTS = "max-age=31536000; includeSubDomains"


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
        }

    @app.after_request
    def security_headers(response):
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", HSTS)
        return response

    @app.get("/favicon.ico")
    def favicon():
        # starsze klienty i narzędzia proszą o /favicon.ico mimo <link rel="icon"> — bez 404 w logu
        return redirect(url_for("static", filename="favicon.svg"), code=301)

    @app.get("/healthz")
    def healthz():
        try:
            db.session.execute(db.text("SELECT 1"))
        except Exception:  # noqa: BLE001 - nie ujawniamy szczegółów błędu w odpowiedzi
            app.logger.exception("healthz: brak połączenia z bazą")
            return jsonify(status="error", version=__version__, db="error"), 503
        return jsonify(status="ok", version=__version__, db="ok")

    from . import models  # noqa: F401  (rejestracja modeli dla Alembic)
    from .services.accounts import password_problem, set_admin_password
    from .services.audit import prune_audit
    from .services.seed import reset_demo, seed_base, seed_demo
    from .services.webhooks import deliver_pending, prune_deliveries, run_worker

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

    @app.cli.command("set-admin-password")
    @click.option("--email", default=None, help="Konto (domyślnie ADMIN_EMAIL).")
    @click.option("--password-stdin", is_flag=True,
                  help="Hasło z pierwszej linii stdin (skrypty, `docker compose exec -T`).")
    @click.option("--from-env", is_flag=True, help="Hasło z ADMIN_PASSWORD (po zmianie w .env).")
    def set_admin_password_cmd(email, password_stdin, from_env):
        """Ustawia hasło administratora (tworzy konto, gdy go nie ma); unieważnia wszystkie sesje tego konta."""
        email = (email or app.config.get("ADMIN_EMAIL") or "").strip().lower()
        if not email:
            click.echo("Brak adresu e-mail konta — podaj --email albo ustaw ADMIN_EMAIL.", err=True)
            raise SystemExit(2)
        if from_env:
            password = app.config.get("ADMIN_PASSWORD") or ""
        elif password_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
        else:
            password = click.prompt("Nowe hasło", hide_input=True, confirmation_prompt=True)
        problem = password_problem(password)
        if problem:
            click.echo(problem, err=True)
            raise SystemExit(1)
        user, created = set_admin_password(email, password, actor="cli")
        db.session.commit()
        click.echo(f"{'Utworzono konto' if created else 'Zmieniono hasło konta'} {user.email}; wszystkie sesje tego "
                   "konta zostały unieważnione.")

    @app.cli.command("prune-audit")
    @click.option("--days", type=int, default=None, help="Starsze niż N dni (domyślnie AUDIT_RETENTION_DAYS).")
    @click.option("--all-actions", is_flag=True, help="Wszystkie wpisy, nie tylko login_failed/login_blocked.")
    def prune_audit_cmd(days, all_actions):
        """Retencja dziennika: usuwa stare wpisy nieudanych i zablokowanych logowań (z --all-actions: wszystkie)."""
        days = app.config["AUDIT_RETENTION_DAYS"] if days is None else days
        if days < 1:
            click.echo("--days musi być liczbą dni ≥ 1.", err=True)
            raise SystemExit(2)
        removed = prune_audit(days, all_actions)
        db.session.commit()
        scope = "wszystkie akcje" if all_actions else "login_failed, login_blocked"
        click.echo(f"Usunięto {removed} wpisów dziennika starszych niż {days} dni ({scope}).")

    @app.cli.command("webhooks-worker")
    @click.option("--once", is_flag=True, help="Jedna runda wysyłki i koniec (awaryjnie z crona).")
    @click.option("--interval", type=click.FloatRange(min=0.1), default=5.0, show_default=True,
                  help="Odstęp między rundami w sekundach.")
    def webhooks_worker_cmd(once, interval):
        """Worker webhooków: wysyła zaległe dostawy z ponowieniami; SIGTERM/SIGINT kończy pętlę."""
        from .models import utcnow
        if once:
            sent = deliver_pending(utcnow())
            click.echo(f"Wysłano {sent} dostaw webhooków (jedna runda).")
            return
        import logging
        import signal
        import threading
        if app.logger.level == logging.NOTSET:
            app.logger.setLevel(logging.INFO)  # start/stop i liczba wysłanych widoczne w `docker compose logs`
        stop = threading.Event()
        previous = {}
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                previous[sig] = signal.signal(sig, lambda *_: stop.set())
            except ValueError:  # nie w głównym wątku (np. osadzenie w testach) — zatrzymanie tylko przez `stop`
                pass
        try:
            run_worker(app, interval=interval, stop=stop, heartbeat=app.config.get("WEBHOOK_HEARTBEAT_FILE") or None)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)

    @app.cli.command("prune-webhooks")
    @click.option("--days", type=int, default=None, help="Starsze niż N dni (domyślnie WEBHOOK_RETENTION_DAYS).")
    def prune_webhooks_cmd(days):
        """Retencja dostaw webhooków: usuwa wysłane i porzucone starsze niż N dni (oczekujące zostają)."""
        days = app.config["WEBHOOK_RETENTION_DAYS"] if days is None else days
        if days < 1:
            click.echo("--days musi być liczbą dni ≥ 1.", err=True)
            raise SystemExit(2)
        removed = prune_deliveries(days)
        db.session.commit()
        click.echo(f"Usunięto {removed} dostaw webhooków (wysłanych i porzuconych) starszych niż {days} dni.")

    @app.cli.command("reset-demo")
    def reset_demo_cmd():
        """Czyści dane i przywraca stan demo."""
        try:
            reset_demo()
        except RuntimeError as e:
            click.echo(str(e), err=True)
            raise SystemExit(1) from None
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

    from .web.filters import register_filters
    register_filters(app)

    return app
