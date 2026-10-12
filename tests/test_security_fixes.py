"""Poprawki bezpieczeństwa z audytu 2026-10-11 (znaleziska średnie): nagłówki HSTS/Permissions-Policy, placeholder
klucza demo, agregacja wpisów `login_blocked` i retencja dziennika (`flask prune-audit`), rotacja hasła administratora
(`flask set-admin-password`, widok „Zmień hasło”), budżet podpowiedzi rozmytych towarów."""
import json
import time
from datetime import timedelta

import pytest
from flask import g

from app import create_app
from app.extensions import db
from app.models import ApiKey, AuditLog, User, utcnow


def _login(client, email="admin@example.com", password="haslo123"):
    return client.post("/login", data={"email": email, "password": password})


def _app(tmp_path, **cfg):
    base = {"TESTING": True, "SECRET_KEY": "test", "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "STORAGE_DIR": str(tmp_path / "s"), "WTF_CSRF_ENABLED": False}
    return create_app({**base, **cfg})


# --- nagłówki: Permissions-Policy zawsze, HSTS tylko przy HTTPS ------------------------------------------------

def test_permissions_policy_always_and_no_hsts_over_http(client):
    r = client.get("/login")
    assert r.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
    assert "Strict-Transport-Security" not in r.headers


def test_hsts_when_request_is_secure(client):
    r = client.get("/login", base_url="https://panel.example.test")
    assert r.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


def test_hsts_behind_trusted_proxy_with_forwarded_proto(tmp_path):
    app = _app(tmp_path, TRUSTED_PROXY_COUNT=1)
    with app.app_context():
        db.create_all()
        r = app.test_client().get("/login", headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "10.0.0.9"})
        assert r.headers["Strict-Transport-Security"].startswith("max-age=31536000")
        r = app.test_client().get("/login", headers={"X-Forwarded-Proto": "http", "X-Forwarded-For": "10.0.0.9"})
        assert "Strict-Transport-Security" not in r.headers


# --- klucz demo: wartość przykładowa i za krótkie klucze nie stają się kluczami API ----------------------------

@pytest.mark.parametrize("key", ["xp_demo_klucz_do_testow", "xp_krotki"])
def test_seed_refuses_placeholder_or_short_demo_key(tmp_path, key, capsys):
    from app.services.seed import seed_base
    app = _app(tmp_path, TESTING=False, SECRET_KEY="k" * 40, DEMO_MODE=True, DEMO_API_KEY=key, ADMIN_PASSWORD="")
    with app.app_context():
        db.create_all()
        seed_base()
        assert ApiKey.query.count() == 0
    err = capsys.readouterr().err
    assert "DEMO_API_KEY" in err and "24" in err


def test_seed_creates_demo_key_for_strong_value(tmp_path):
    from app.services.seed import seed_base
    app = _app(tmp_path, TESTING=False, SECRET_KEY="k" * 40, DEMO_MODE=True, DEMO_API_KEY="xp_" + "a" * 30,
               ADMIN_PASSWORD="")
    with app.app_context():
        db.create_all()
        seed_base()
        assert ApiKey.query.filter_by(active=True).count() == 1


def test_env_example_has_no_demo_key_value():
    from pathlib import Path
    text = Path(__file__).resolve().parent.parent.joinpath(".env.example").read_text(encoding="utf-8")
    assert "xp_demo_klucz_do_testow" not in text and "DEMO_API_KEY=" in text and "token_urlsafe" in text


# --- dziennik: zablokowane próby logowania nie zapisują wiersza przy każdym żądaniu ---------------------------

def test_blocked_login_logs_once_per_ip_per_window(seeded, client):
    for _ in range(5):
        assert _login(client, password="zle").status_code == 200
    assert AuditLog.query.filter_by(action="login_failed").count() == 5
    for _ in range(10):
        assert _login(client, password="zle").status_code == 429
    rows = AuditLog.query.filter_by(action="login_blocked").all()
    assert len(rows) == 1
    assert rows[0].payload["email"] == "admin@example.com" and rows[0].payload["ip"]
    # inny e-mail z tego samego IP w oknie blokady — nadal jeden wpis (dedupe po IP, nie po parze)
    assert _login(client, email="ktos@example.com", password="zle").status_code in (200, 429)
    assert AuditLog.query.filter_by(action="login_blocked").count() == 1


def test_login_audit_truncates_attacker_email(seeded, client):
    long_email = "a" * 300 + "@example.com"
    _login(client, email=long_email, password="zle")
    row = AuditLog.query.filter_by(action="login_failed").order_by(AuditLog.id.desc()).first()
    assert len(row.payload["email"]) <= 100


def test_prune_audit_removes_old_login_rows_by_default(app):
    old = utcnow() - timedelta(days=100)
    rows = [AuditLog(user="anonim", action="login_failed", entity="user", payload={}, created_at=old),
            AuditLog(user="anonim", action="login_blocked", entity="user", payload={}, created_at=old),
            AuditLog(user="admin", action="approve", entity="document", entity_id=1, payload={}, created_at=old),
            AuditLog(user="anonim", action="login_failed", entity="user", payload={}, created_at=utcnow())]
    db.session.add_all(rows)
    db.session.commit()
    r = app.test_cli_runner().invoke(args=["prune-audit", "--days", "90"])
    assert r.exit_code == 0, r.output
    assert "2" in r.output
    assert sorted(a.action for a in AuditLog.query.all()) == ["approve", "login_failed"]
    r = app.test_cli_runner().invoke(args=["prune-audit", "--days", "90", "--all-actions"])
    assert r.exit_code == 0, r.output
    assert [a.action for a in AuditLog.query.all()] == ["login_failed"]


def test_prune_audit_default_days_from_config_and_validation(app):
    app.config["AUDIT_RETENTION_DAYS"] = 30
    db.session.add(AuditLog(user="anonim", action="login_failed", entity="user", payload={},
                            created_at=utcnow() - timedelta(days=31)))
    db.session.commit()
    r = app.test_cli_runner().invoke(args=["prune-audit"])
    assert r.exit_code == 0 and AuditLog.query.count() == 0, r.output
    r = app.test_cli_runner().invoke(args=["prune-audit", "--days", "0"])
    assert r.exit_code != 0


# --- hasło administratora: komenda CLI i widok zmiany hasła ----------------------------------------------------

def test_set_admin_password_cli_updates_existing_user_and_invalidates_sessions(seeded, app, client):
    _login(client)
    assert client.get("/pulpit").status_code == 200
    r = app.test_cli_runner().invoke(args=["set-admin-password", "--password-stdin"], input="nowe-haslo-123\n")
    assert r.exit_code == 0, r.output
    assert "admin@example.com" in r.output
    db.session.expire_all()  # CLI commitowało w osobnej sesji; w produkcji każde żądanie ma świeżą sesję
    user = User.query.filter_by(email="admin@example.com").one()
    assert user.check_password("nowe-haslo-123") and not user.check_password("haslo123")
    g.pop("_login_user", None)  # w testach kontekst aplikacji (a więc g) jest wspólny dla żądań
    assert client.get("/pulpit").status_code == 302  # stare ciasteczko sesji nieważne (rotacja session_token)
    assert AuditLog.query.filter_by(action="password_set").count() == 1


def test_set_admin_password_cli_creates_missing_user_and_rejects_weak(app):
    runner = app.test_cli_runner()
    r = runner.invoke(args=["set-admin-password", "--email", "nowy@example.com", "--password-stdin"],
                      input="zmien-mnie\n")
    assert r.exit_code != 0 and "10" in r.output
    r = runner.invoke(args=["set-admin-password", "--email", "nowy@example.com", "--password-stdin"], input="krotkie\n")
    assert r.exit_code != 0
    assert User.query.filter_by(email="nowy@example.com").first() is None
    r = runner.invoke(args=["set-admin-password", "--email", "Nowy@Example.com", "--password-stdin"],
                      input="dlugie-haslo-42\n")
    assert r.exit_code == 0, r.output
    assert User.query.filter_by(email="nowy@example.com").one().check_password("dlugie-haslo-42")


def test_set_admin_password_cli_from_env(seeded, app, monkeypatch):
    app.config["ADMIN_PASSWORD"] = "z-env-haslo-99"
    r = app.test_cli_runner().invoke(args=["set-admin-password", "--from-env"])
    assert r.exit_code == 0, r.output
    assert User.query.filter_by(email="admin@example.com").one().check_password("z-env-haslo-99")


def test_password_change_view_requires_login(seeded, client):
    assert client.get("/konto/haslo").status_code == 302
    assert client.post("/konto/haslo", data={}).status_code == 302


def test_password_change_view_validates_and_keeps_current_session(seeded, client):
    _login(client)
    html = client.get("/konto/haslo").get_data(as_text=True)
    assert 'name="current_password"' in html and 'name="new_password"' in html and 'name="new_password2"' in html
    r = client.post("/konto/haslo", data={"current_password": "zle", "new_password": "nowe-haslo-123",
                                          "new_password2": "nowe-haslo-123"})
    assert r.status_code == 200 and "Obecne hasło" in r.get_data(as_text=True)
    r = client.post("/konto/haslo", data={"current_password": "haslo123", "new_password": "nowe-haslo-123",
                                          "new_password2": "inne-haslo-123"})
    assert r.status_code == 200 and "nie są takie same" in r.get_data(as_text=True)
    r = client.post("/konto/haslo", data={"current_password": "haslo123", "new_password": "krotkie",
                                          "new_password2": "krotkie"})
    assert r.status_code == 200 and "10" in r.get_data(as_text=True)
    assert User.query.filter_by(email="admin@example.com").one().check_password("haslo123")
    r = client.post("/konto/haslo", data={"current_password": "haslo123", "new_password": "nowe-haslo-123",
                                          "new_password2": "nowe-haslo-123"})
    assert r.status_code == 302
    user = User.query.filter_by(email="admin@example.com").one()
    assert user.check_password("nowe-haslo-123")
    assert client.get("/pulpit").status_code == 200  # bieżąca sesja odświeżona, nie wylogowana
    assert AuditLog.query.filter_by(action="password_change").count() == 1


def test_password_change_invalidates_other_sessions(seeded, app, client):
    other = app.test_client()
    _login(other)
    _login(client)
    client.post("/konto/haslo", data={"current_password": "haslo123", "new_password": "nowe-haslo-123",
                                      "new_password2": "nowe-haslo-123"})
    g.pop("_login_user", None)  # w testach kontekst aplikacji (a więc g) jest wspólny dla żądań
    assert other.get("/pulpit").status_code == 302


def test_nav_links_to_password_change(auth_client):
    html = auth_client.get("/pulpit").get_data(as_text=True)
    assert 'href="/konto/haslo"' in html


# --- podpowiedzi towarów: indeks kartoteki i budżet porównań rozmytych -----------------------------------------

def test_product_candidates_fast_with_large_catalogue():
    from app.engine.suggest import ProductIndex, product_candidates
    products = [{"code": f"P{i}", "name": f"Towar numer {i} opis {i % 7} wariant {i % 13}", "gtin": None}
                for i in range(5000)]
    index = ProductIndex(products)
    t0 = time.perf_counter()
    for i in range(200):
        out = product_candidates({"name": f"Towar numer {i * 17} opis {i % 7}"}, products, index=index)
        assert out and out[0]["confidence"] <= 0.9
    assert time.perf_counter() - t0 < 5.0


def test_product_candidates_same_results_with_and_without_index():
    from app.engine.suggest import ProductIndex, product_candidates
    products = [{"code": "A", "name": "Masa marcepanowa 5kg", "gtin": "5909999000037"},
                {"code": "B", "name": "Mąka pszenna typ 450", "gtin": None},
                {"code": "C", "name": "Masa cukrowa 1 kg", "gtin": None}]
    line = {"name": "Masa marcepanowa 5 kg", "gtin": "05909999000037"}
    plain = product_candidates(line, products)
    indexed = product_candidates(line, products, index=ProductIndex(products))
    assert plain == indexed
    assert plain[0] == {"kind": "product", "code": "A", "name": "Masa marcepanowa 5kg", "confidence": 1.0,
                        "reason": "zgodny GTIN"}
    assert [c["code"] for c in plain][1] == "C"
    assert product_candidates(line, products, index=ProductIndex(products), fuzzy=False) == plain[:1]


def test_fuzzy_product_suggestions_limited_per_document(seeded, client, monkeypatch):
    import app.services.pipeline as pipeline
    from app.services.pipeline import ingest
    from tests.test_negotiation_statuses import inv, line
    monkeypatch.setattr(pipeline, "MAX_FUZZY_PRODUCT_LINES", 2)
    lines = [line(sku=f"S{i}", ean=None, name=name) for i, name in
             enumerate(["Maka pszenna 450", "Maka zytnia 750", "Maslo extra 1kg"], start=1)]
    doc = ingest(inv("BUDZET/1", lines), "b.json", source="upload")
    unmapped = [i for i in doc.issues if i["code"] == "unmapped_product"]
    assert len(unmapped) == 3
    reasons = [{s["reason"] for s in i["suggestions"]} for i in unmapped]
    assert "podobna nazwa" in reasons[0] and "podobna nazwa" in reasons[1]
    assert "podobna nazwa" not in reasons[2] and "nowy towar w kartotece" in reasons[2]
