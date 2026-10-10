"""Pakiet F: nagłówki bezpieczeństwa, sesja, limit logowania, demo, izolacja kluczy API, ProxyFix."""
import inspect
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.models import AuditLog, Document, LoginAttempt, Supplier, User, utcnow
from app.services.apikeys import create_key
from tests.conftest import sample_bytes

ROOT = Path(__file__).resolve().parent.parent
KEY = {"X-API-Key": "xp_test_demo_key"}


def _login(client, email="admin@example.com", password="haslo123", **kw):
    return client.post("/login", data={"email": email, "password": password}, **kw)


# --- SEC-3: nagłówki ---------------------------------------------------------------------------------

def _assert_security_headers(r):
    csp = r.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    script_src = re.search(r"script-src ([^;]*)", csp).group(1)
    assert "'unsafe-inline'" not in script_src
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("Referrer-Policy") == "same-origin"


@pytest.mark.parametrize("url", ["/login", "/demo", "/api/docs", "/healthz", "/api/v1/documents"])
def test_security_headers_on_public_endpoints(seeded, client, url):
    _assert_security_headers(client.get(url))


INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.I)
INLINE_HANDLER = re.compile(r"<[^>]+\son[a-z]+\s*=", re.I)


def _main_pages(client):
    # dokument + szablon, żeby wyrenderować szczegóły i edytor
    client.post("/demo/wczytaj/alfa-1.xml")
    doc = Document.query.first()
    pages = ["/demo", "/pulpit", "/wgraj", "/kolejka", "/dokumenty", f"/dokumenty/{doc.id}",
             f"/szablony/dokument/{doc.id}/edytor", "/szablony", "/klucze-api", "/historia", "/api/docs",
             "/towary/import", "/towary/1/edycja", "/login"]
    from flask import current_app
    for rule in current_app.url_map.iter_rules():
        if rule.endpoint.startswith("catalog.list_") or rule.endpoint.startswith("catalog.new_"):
            pages.append(rule.rule)
    return pages


def test_all_main_pages_render_with_headers_and_no_inline_js(auth_client):
    for url in _main_pages(auth_client):
        r = auth_client.get(url)
        assert r.status_code == 200, url
        _assert_security_headers(r)
        html = r.get_data(as_text=True)
        assert not INLINE_SCRIPT.search(html), f"inline <script> na {url}"
        assert not INLINE_HANDLER.search(html), f"atrybut on*= na {url}"


def test_swagger_init_moved_to_static_file(seeded, client):
    html = client.get("/api/docs").get_data(as_text=True)
    assert "api_docs.js" in html and "openapi.yaml" in html
    js = client.get("/static/api_docs.js")
    assert js.status_code == 200 and b"SwaggerUIBundle" in js.data


# --- SEC-4 / OPS-9: sesja ------------------------------------------------------------------------------

def test_session_cookie_flags_and_lifetime(seeded, app, client):
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["REMEMBER_COOKIE_HTTPONLY"] is True
    assert app.config["REMEMBER_COOKIE_SAMESITE"] == "Lax"
    assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(hours=8)
    from app.extensions import login_manager
    assert login_manager.session_protection == "strong"
    r = _login(client)
    cookie = r.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Expires=" in cookie


def test_session_cookie_secure_from_env(monkeypatch):
    from app import config as cfg
    src = inspect.getsource(cfg)
    assert '_bool("SESSION_COOKIE_SECURE", "0")' in src


def test_logout_invalidates_copied_session_cookie(seeded, client):
    _login(client)
    stolen = client.get_cookie("session").value
    assert client.get("/pulpit").status_code == 200
    client.post("/logout")
    client.set_cookie("session", stolen)
    r = client.get("/pulpit")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_password_change_invalidates_sessions(seeded, client):
    _login(client)
    u = User.query.filter_by(email="admin@example.com").one()
    u.set_password("nowe-haslo-123")
    db.session.commit()
    from flask import g
    g.pop("_login_user", None)  # w testach kontekst aplikacji (a więc g) jest wspólny dla żądań
    r = client.get("/pulpit")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_old_style_session_id_rejected(seeded, client):
    u = User.query.filter_by(email="admin@example.com").one()
    with client.session_transaction() as s:
        s["_user_id"] = str(u.id)  # format sprzed zmiany (samo id) — nie może logować
        s["_fresh"] = True
    assert client.get("/pulpit").status_code == 302


# --- SEC-2: limit prób logowania -------------------------------------------------------------------

def test_login_lockout_after_five_failures(seeded, client):
    for _ in range(5):
        r = _login(client, password="zle-haslo")
        assert "Nieprawidłowy e-mail lub hasło" in r.get_data(as_text=True)
    r = _login(client)  # poprawne hasło, ale konto zablokowane
    body = r.get_data(as_text=True)
    assert r.status_code == 429 and "Zbyt wiele nieudanych prób" in body
    assert client.get("/pulpit").status_code == 302
    assert AuditLog.query.filter_by(action="login_failed").count() == 5
    assert AuditLog.query.filter_by(action="login_blocked").count() == 1


def test_login_lockout_expires_after_window(seeded, client):
    for _ in range(5):
        _login(client, password="zle-haslo")
    for a in LoginAttempt.query.all():
        a.created_at = utcnow() - timedelta(minutes=16)
    db.session.commit()
    r = _login(client)
    assert r.status_code == 302 and client.get("/pulpit").status_code == 200


def test_login_lockout_per_ip_across_emails(seeded, client):
    # rozpylanie haseł po wielu kontach z jednego IP — próg per IP (20)
    for i in range(19):
        assert _login(client, email=f"nieznany{i}@example.com", password="x").status_code == 200
    assert _login(client, email="nieznany99@example.com", password="x").status_code == 200
    assert _login(client).status_code == 429


def test_attacker_cannot_lock_out_admin_from_other_ip(seeded, client):
    for _ in range(8):
        _login(client, password="zle", environ_base={"REMOTE_ADDR": "203.0.113.5"})
    assert _login(client, password="zle", environ_base={"REMOTE_ADDR": "203.0.113.5"}).status_code == 429
    # admin z innego adresu loguje się normalnie (próg per sam e-mail jest dużo wyższy)
    r = _login(client, environ_base={"REMOTE_ADDR": "198.51.100.1"})
    assert r.status_code == 302


def test_blocked_attempts_do_not_extend_lockout_or_count_globally(seeded, client):
    ip = {"REMOTE_ADDR": "203.0.113.6"}
    for _ in range(5):
        _login(client, password="zle", environ_base=ip)
    for _ in range(60):  # zablokowane — nie są zapisywane, więc nie wliczają się do progu per e-mail
        assert _login(client, password="zle", environ_base=ip).status_code == 429
    assert LoginAttempt.query.count() == 5
    assert _login(client, environ_base={"REMOTE_ADDR": "198.51.100.2"}).status_code == 302


def test_global_email_threshold_across_many_ips(seeded, app, client):
    for i in range(50):
        _login(client, password="zle", environ_base={"REMOTE_ADDR": f"10.1.{i // 4}.{i % 4 + 1}"})
    r = _login(client, environ_base={"REMOTE_ADDR": "198.51.100.3"})
    assert r.status_code == 429
    for a in LoginAttempt.query.all():  # okno per e-mail jest krótsze (5 min)
        a.created_at = utcnow() - timedelta(minutes=6)
    db.session.commit()
    assert _login(client, environ_base={"REMOTE_ADDR": "198.51.100.3"}).status_code == 302


def test_parallel_burst_cannot_bypass_limit(tmp_path, monkeypatch):
    """Równoległe próby (wątki, wspólna baza SQLite w pliku): hasło sprawdzone najwyżej LOGIN_MAX_ATTEMPTS razy."""
    import threading

    app = create_app({
        "TESTING": True, "SECRET_KEY": "test", "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'race.db'}",
        "SQLALCHEMY_ENGINE_OPTIONS": {"connect_args": {"timeout": 30}},
        "STORAGE_DIR": str(tmp_path / "s"), "ADMIN_EMAIL": "admin@example.com", "ADMIN_PASSWORD": "haslo123",
        "DEMO_MODE": False,
    })
    with app.app_context():
        db.create_all()
        from app.services.seed import seed_base
        seed_base()
    checks = []
    original = User.check_password

    def slow_check(self, pw):
        checks.append(pw)
        import time
        time.sleep(0.05)  # okno wyścigu między odczytem licznika a zapisem
        return original(self, pw)

    monkeypatch.setattr(User, "check_password", slow_check)
    barrier = threading.Barrier(12)
    codes = []

    def worker():
        c = app.test_client()
        barrier.wait()
        codes.append(c.post("/login", data={"email": "admin@example.com", "password": "zle"}).status_code)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(codes) == 12
    assert len(checks) <= 5 and codes.count(429) >= 7


def test_login_lockout_is_per_ip_not_global(seeded, client):
    for _ in range(5):
        _login(client, email="kto@example.com", password="x", environ_base={"REMOTE_ADDR": "10.0.0.9"})
    # inny adres i inne konto — bez blokady
    r = _login(client, environ_base={"REMOTE_ADDR": "10.0.0.10"})
    assert r.status_code == 302


def test_successful_login_clears_email_failures(seeded, client):
    for _ in range(3):
        _login(client, password="zle")
    assert _login(client).status_code == 302
    assert LoginAttempt.query.filter_by(email="admin@example.com").count() == 0


# --- DEMO_MODE (K-1, BE-15, OPS-11) ------------------------------------------------------------------

def test_demo_mode_defaults_to_off():
    from app import config as cfg
    assert '_bool("DEMO_MODE", "0")' in inspect.getsource(cfg)
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^DEMO_MODE=0$", env_example, re.M)


def test_demo_page_never_shows_admin_password(seeded, client):
    html = client.get("/demo").get_data(as_text=True)
    assert "haslo123" not in html
    assert "ADMIN_PASSWORD" in html
    assert "xp_test_demo_key" not in html  # klucz tylko dla zalogowanych


def test_demo_key_visible_when_logged_in(auth_client):
    html = auth_client.get("/demo").get_data(as_text=True)
    assert "xp_test_demo_key" in html and "haslo123" not in html


def test_demo_reset_admin_only(seeded, client):
    u = User(email="operator@example.com", role="operator")
    u.set_password("operator-haslo-1")
    db.session.add(u)
    db.session.commit()
    _login(client, "operator@example.com", "operator-haslo-1")
    assert client.post("/demo/reset").status_code == 403


# --- wyciek duplikatu (K-2) i SEC-5 -----------------------------------------------------------------

def _second_key():
    _, plain = create_key("Drugi system")
    db.session.commit()
    return {"X-API-Key": plain}


def test_duplicate_from_other_key_does_not_leak_id(seeded, client):
    first = client.post("/api/v1/documents", headers=KEY, data=sample_bytes("epsilon.json")).get_json()
    other = client.post("/api/v1/documents", headers=_second_key(), data=sample_bytes("epsilon.json")).get_json()
    # od pakietu E zakresem duplikatów jest klucz API — dokument innego klucza nie jest duplikatem
    # i niczego o nim nie ujawniamy
    assert other["status"] != "duplicate"
    assert not [i for i in other["issues"] if i["code"] == "duplicate"]
    assert f"#{first['id']}" not in json.dumps(other)


def test_legacy_cross_key_duplicate_is_sanitized(seeded, client):
    # dokumenty sprzed izolacji zakresów mogą wskazywać dokument innego klucza — API nadal to maskuje
    first = client.post("/api/v1/documents", headers=KEY, data=sample_bytes("epsilon.json")).get_json()
    hdr = _second_key()
    other = client.post("/api/v1/documents", headers=hdr, data=sample_bytes("epsilon.json")).get_json()
    doc = db.session.get(Document, other["id"])
    doc.status = "duplicate"
    doc.issues = [{"code": "duplicate", "severity": "blocking", "source_value": str(first["id"]),
                   "message": f"Ta faktura była już przetworzona (dokument #{first['id']})."}] + list(doc.issues)
    db.session.commit()
    js = client.get(f"/api/v1/documents/{other['id']}", headers=hdr).get_json()
    dup = [i for i in js["issues"] if i["code"] == "duplicate"][0]
    assert f"#{first['id']}" not in dup["message"] and not dup.get("source_value")
    assert "duplikat istniejącego dokumentu" in dup["message"]


def test_duplicate_from_same_key_keeps_id(seeded, client):
    first = client.post("/api/v1/documents", headers=KEY, data=sample_bytes("epsilon.json")).get_json()
    again = client.post("/api/v1/documents", headers=KEY, data=sample_bytes("epsilon.json")).get_json()
    dup = [i for i in again["issues"] if i["code"] == "duplicate"][0]
    assert f"#{first['id']}" in dup["message"]


def test_api_suppliers_limited_to_own_documents(seeded, client):
    mine = Supplier(name="Dostawca klucza", tax_id="1111111111")
    foreign = Supplier(name="Cudzy dostawca", tax_id="2222222222")
    db.session.add_all([mine, foreign])
    db.session.flush()
    from app.models import ApiKey
    demo_key = ApiKey.query.filter_by(name="Klucz demo").one()
    db.session.add(Document(sha256="0" * 64, status="approved", supplier_id=mine.id, api_key_id=demo_key.id))
    db.session.commit()
    items = client.get("/api/v1/suppliers", headers=KEY).get_json()["items"]
    assert [s["name"] for s in items] == ["Dostawca klucza"]


SAFE_KINDS = {"path", "line_path", "default", "unit", "conversion", "create_supplier", "create_product"}


def test_api_document_hides_catalog_suggestions(seeded, client):
    db.session.add(Supplier(name="Hurtownia Alfa", tax_id="5250000000"))
    db.session.commit()
    body = client.post("/api/v1/documents", headers=KEY, data=sample_bytes("alfa-1.xml")).get_json()
    stored = db.session.get(Document, body["id"])
    stored_kinds = {s.get("kind") for i in stored.issues for s in (i.get("suggestions") or [])}
    assert stored_kinds & {"product", "use_supplier"}  # w panelu podpowiedzi zostają
    api_kinds = {s.get("kind") for i in body["issues"] for s in (i.get("suggestions") or [])}
    assert api_kinds <= SAFE_KINDS
    again = client.get(f"/api/v1/documents/{body['id']}", headers=KEY).get_json()
    assert {s.get("kind") for i in again["issues"] for s in (i.get("suggestions") or [])} <= SAFE_KINDS


# --- OPS-8: ProxyFix --------------------------------------------------------------------------------

def _make_app(tmp_path, **extra):
    cfg = {"TESTING": True, "SECRET_KEY": "test", "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
           "STORAGE_DIR": str(tmp_path / "s"), "WTF_CSRF_ENABLED": False}
    cfg.update(extra)
    return create_app(cfg)


def test_proxyfix_disabled_by_default(tmp_path):
    from werkzeug.middleware.proxy_fix import ProxyFix
    assert not isinstance(_make_app(tmp_path).wsgi_app, ProxyFix)


def test_proxyfix_enabled_with_trusted_proxy_count(tmp_path):
    from werkzeug.middleware.proxy_fix import ProxyFix
    app = _make_app(tmp_path, TRUSTED_PROXY_COUNT=1)
    assert isinstance(app.wsgi_app, ProxyFix) and app.wsgi_app.x_for == 1

    @app.get("/_ip")
    def _ip():
        from flask import request
        return request.remote_addr

    r = app.test_client().get("/_ip", headers={"X-Forwarded-For": "192.0.2.7"})
    assert r.get_data(as_text=True) == "192.0.2.7"
