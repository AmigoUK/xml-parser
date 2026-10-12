"""Luki w testach bezpieczeństwa wskazane w audycie 2026-10-11: CSRF na formularzach panelu, API bez sesji
ciasteczkowej, XXE/entity expansion jawnie, odmowa startu przy placeholderze SECRET_KEY, nagłówki na stronach błędów
i API 500 bez szczegółów, walidacja Storage._path, blokada „wszyscy z jednego IP” za proxy, seed nie nadpisuje hasła."""
import io
import re
import time

import pytest

from app import create_app
from app.extensions import db
from app.ingest import ReaderError, read_document
from app.models import User
from app.services.storage import Storage

KEY = {"X-API-Key": "xp_test_demo_key"}
CSRF_META = re.compile(r'name="csrf-token" content="([^"]+)"')


def _app(tmp_path, **cfg):
    base = {"TESTING": True, "SECRET_KEY": "test", "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "STORAGE_DIR": str(tmp_path / "s"), "WTF_CSRF_ENABLED": False, "DEMO_MODE": True,
            "ADMIN_EMAIL": "admin@example.com", "ADMIN_PASSWORD": "haslo123", "DEMO_API_KEY": "xp_test_demo_key"}
    return create_app({**base, **cfg})


@pytest.fixture
def csrf_app(tmp_path):
    app = _app(tmp_path, WTF_CSRF_ENABLED=True)
    with app.app_context():
        db.create_all()
        from app.services.seed import seed_base, seed_demo
        seed_base()
        seed_demo()
        yield app
        db.session.remove()
        db.drop_all()


def _token(client, path="/login"):
    return CSRF_META.search(client.get(path).get_data(as_text=True)).group(1)


# --- CSRF na formularzach panelu ----------------------------------------------------------------------------------

def test_csrf_required_on_login_and_logout(csrf_app):
    client = csrf_app.test_client()
    assert client.post("/login", data={"email": "admin@example.com", "password": "haslo123"}).status_code == 400
    token = _token(client)
    r = client.post("/login", data={"email": "admin@example.com", "password": "haslo123", "csrf_token": token})
    assert r.status_code == 302 and client.get("/pulpit").status_code == 200
    assert client.post("/logout").status_code == 400
    assert client.get("/pulpit").status_code == 200  # nadal zalogowany
    assert client.post("/logout", data={"csrf_token": _token(client, "/pulpit")}).status_code == 302


def test_csrf_required_on_panel_actions(csrf_app):
    client = csrf_app.test_client()
    client.post("/login", data={"email": "admin@example.com", "password": "haslo123", "csrf_token": _token(client)})
    client.post("/demo/wczytaj/alfa-1.xml", data={"csrf_token": _token(client, "/pulpit")})
    from app.models import ApiKey, Document, Product
    doc = Document.query.first()
    assert client.post(f"/dokumenty/{doc.id}/rozwiaz", data={"action": "reject"}).status_code == 400
    assert client.post("/klucze-api/nowy", data={"name": "x"}).status_code == 400
    assert ApiKey.query.filter_by(name="x").count() == 0
    product = Product.query.first()
    assert client.post(f"/towary/{product.id}/usun").status_code == 400
    assert db.session.get(Product, product.id) is not None
    assert client.post("/konto/haslo", data={"current_password": "haslo123", "new_password": "nowe-haslo-123",
                                             "new_password2": "nowe-haslo-123"}).status_code == 400
    token = _token(client, "/pulpit")
    assert client.post("/klucze-api/nowy", data={"name": "x", "csrf_token": token}).status_code == 200
    assert ApiKey.query.filter_by(name="x").count() == 1


# --- API: wyłącznie X-API-Key -------------------------------------------------------------------------------------

def test_api_never_accepts_browser_session_or_other_credential_carriers(auth_client):
    assert auth_client.get("/api/v1/documents").status_code == 401
    assert auth_client.post("/api/v1/documents", data=b"<a/>", content_type="application/xml").status_code == 401
    assert auth_client.get("/api/v1/documents", query_string={"api_key": "xp_test_demo_key"}).status_code == 401
    assert auth_client.get("/api/v1/documents", headers={"Authorization": "Bearer xp_test_demo_key"}).status_code == 401
    assert auth_client.get("/api/v1/suppliers").status_code == 401
    assert auth_client.get("/api/v1/documents", headers=KEY).status_code == 200


# --- XML: XXE, rozszerzanie encji, DOCTYPE po białych znakach, zewnętrzne DTD -------------------------------------

def test_xxe_payload_never_reads_local_files(seeded, client, tmp_path):
    secret = tmp_path / "tajne.txt"
    secret.write_text("SEKRET-XXE-7731", encoding="utf-8")
    payload = (f'<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file://{secret}">]>'
               '<Faktura><Numer>&xxe;</Numer></Faktura>').encode()
    with pytest.raises(ReaderError):
        read_document(payload, "x.xml")
    r = client.post("/api/v1/documents", headers=KEY, data={"file": (io.BytesIO(payload), "x.xml")})
    body = r.get_data(as_text=True)
    assert "SEKRET-XXE-7731" not in body and r.status_code in (201, 400)


def test_billion_laughs_rejected_quickly():
    entities = '<!ENTITY lol "lol">' + "".join(
        f'<!ENTITY lol{i} "' + "&lol{};".format(i - 1 if i > 1 else "") * 10 + '">' for i in range(1, 10))
    payload = f'<?xml version="1.0"?><!DOCTYPE lolz [{entities}]><lolz>&lol9;</lolz>'.encode()
    t0 = time.perf_counter()
    with pytest.raises(ReaderError):
        read_document(payload, "lol.xml")
    assert time.perf_counter() - t0 < 1.0


def test_doctype_after_whitespace_padding_rejected():
    payload = b" " * 5000 + b'<!DOCTYPE a [<!ENTITY e "x">]><a>&e;</a>'
    with pytest.raises(ReaderError):
        read_document(payload, "p.xml")
    newline_pad = b"\n" * 5000 + b"<!DOCTYPE a SYSTEM \"http://example.invalid/a.dtd\"><a>x</a>"
    with pytest.raises(ReaderError):
        read_document(newline_pad, "p.xml")


def test_external_dtd_without_entities_rejected():
    with pytest.raises(ReaderError):
        read_document(b'<!DOCTYPE a SYSTEM "http://example.invalid/a.dtd"><a>x</a>', "d.xml")


# --- start aplikacji: placeholder SECRET_KEY -----------------------------------------------------------------------

@pytest.mark.parametrize("secret", ["zmien-mnie", "dev-only-change-me", ""])
def test_app_refuses_placeholder_secret_key_outside_testing(tmp_path, secret):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app({"TESTING": False, "DEBUG": False, "SECRET_KEY": secret,
                    "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "STORAGE_DIR": str(tmp_path / "s")})
    assert create_app({"TESTING": True, "SECRET_KEY": secret, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                       "STORAGE_DIR": str(tmp_path / "s")})


# --- nagłówki bezpieczeństwa na stronach błędów, API 500 bez szczegółów -------------------------------------------

def _assert_headers(r):
    assert "default-src 'self'" in r.headers.get("Content-Security-Policy", "")
    assert r.headers.get("X-Frame-Options") == "DENY" and r.headers.get("X-Content-Type-Options") == "nosniff"


def test_security_headers_on_error_responses(seeded, client, auth_client):
    r = client.get("/nie-ma-takiej-strony")
    assert r.status_code == 404
    _assert_headers(r)
    r = client.put("/login")
    assert r.status_code == 405
    _assert_headers(r)
    r = client.get("/api/v1/documents/999999", headers=KEY)
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"
    _assert_headers(r)
    r = auth_client.get("/dokumenty/999999")
    assert r.status_code == 404
    _assert_headers(r)


def test_api_internal_error_is_json_without_details(seeded, app, client, monkeypatch):
    import app.api.routes as routes
    from tests.conftest import sample_bytes
    created = client.post("/api/v1/documents", headers=KEY,
                          data={"file": (io.BytesIO(sample_bytes("alfa-1.xml")), "alfa-1.xml")}).get_json()

    def boom(*_a, **_k):
        raise RuntimeError("tajny szczegół implementacji /opt/app/secret.py")

    monkeypatch.setattr(routes, "doc_to_json", boom)
    app.config["PROPAGATE_EXCEPTIONS"] = False  # jak w produkcji: wyjątek trafia do handlera 500
    r = client.get(f"/api/v1/documents/{created['id']}", headers=KEY)
    assert r.status_code == 500 and r.is_json
    assert r.get_json()["error"]["code"] == "internal_error"
    assert "tajny" not in r.get_data(as_text=True) and "secret.py" not in r.get_data(as_text=True)
    _assert_headers(r)


# --- Storage._path -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["", "../etc/passwd", "a/b", "abc.txt", ".", "x" * 10 + "\x00"])
def test_storage_rejects_non_alphanumeric_identifiers(tmp_path, bad):
    storage = Storage(tmp_path)
    with pytest.raises(ValueError):
        storage._path(bad)
    with pytest.raises(ValueError):
        storage.load(bad)
    with pytest.raises(ValueError):
        storage.delete(bad)
    assert not (tmp_path / "etc").exists()


def test_storage_accepts_sha256_identifier(tmp_path):
    storage = Storage(tmp_path)
    sha = storage.save(b"abc")
    assert storage._path(sha) == tmp_path / "raw" / sha and storage.load(sha) == b"abc"


# --- blokada logowań „wszyscy z jednego IP” -----------------------------------------------------------------------

def _seed(app):
    with app.app_context():
        db.create_all()
        from app.services.seed import seed_base
        seed_base()


def test_without_trusted_proxy_all_clients_share_one_ip_lockout(tmp_path):
    """TRUSTED_PROXY_COUNT=0 za proxy: X-Forwarded-For jest ignorowany — 20 cudzych nieudanych prób blokuje
    admina z poprawnym hasłem (dlatego za proxy TRUSTED_PROXY_COUNT jest obowiązkowy)."""
    app = _app(tmp_path, TRUSTED_PROXY_COUNT=0)
    _seed(app)
    with app.app_context():
        c = app.test_client()
        for i in range(20):
            c.post("/login", data={"email": f"obcy{i}@example.com", "password": "zle"},
                   headers={"X-Forwarded-For": f"203.0.113.{i + 1}"})
        r = c.post("/login", data={"email": "admin@example.com", "password": "haslo123"},
                   headers={"X-Forwarded-For": "198.51.100.7"})
        assert r.status_code == 429
        db.session.remove()
        db.drop_all()


def test_with_trusted_proxy_lockout_is_per_client_ip(tmp_path):
    app = _app(tmp_path, TRUSTED_PROXY_COUNT=1)
    _seed(app)
    with app.app_context():
        c = app.test_client()
        for i in range(20):
            c.post("/login", data={"email": f"obcy{i}@example.com", "password": "zle"},
                   headers={"X-Forwarded-For": f"203.0.113.{i + 1}"})
        r = c.post("/login", data={"email": "admin@example.com", "password": "haslo123"},
                   headers={"X-Forwarded-For": "198.51.100.7"})
        assert r.status_code == 302
        db.session.remove()
        db.drop_all()


# --- seed nie nadpisuje hasła istniejącego admina (rotacja: flask set-admin-password) -----------------------------

def test_seed_keeps_existing_admin_password(seeded, app):
    from app.services.seed import seed_base
    app.config["ADMIN_PASSWORD"] = "zupelnie-nowe-haslo"
    seed_base()
    user = User.query.filter_by(email="admin@example.com").one()
    assert user.check_password("haslo123") and not user.check_password("zupelnie-nowe-haslo")
