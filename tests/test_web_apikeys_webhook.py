"""Panel „Klucze API” — webhook przy kluczu (v0.9.0): adres z walidacją celu, sekret pokazany raz, „Wyczyść”,
„Rotuj sekret”, „Wyślij testowe zdarzenie”, lista 50 najnowszych dostaw z „Ponów”, tylko dla administratora."""
import html as htmllib
import re
import socket
from datetime import timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    EVENT_STATUS_CHANGED,
    EVENT_TEST,
    WEBHOOK_FAILED,
    WEBHOOK_PENDING,
    WEBHOOK_SENT,
    ApiKey,
    AuditLog,
    User,
    WebhookDelivery,
    utcnow,
)
from app.services.apikeys import create_key
from tests.webhook_helpers import make_delivery, make_key

PUBLIC_IP = "93.184.216.34"
INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)(?![^>]*type=\"application/json\")[^>]*>", re.I)
INLINE_HANDLER = re.compile(r"<[^>]+\son[a-z]+\s*=", re.I)


def _text(r):
    return htmllib.unescape(r.get_data(as_text=True))


def _key(name="Hurtownia Alfa — ERP"):
    key, _ = create_key(name)
    db.session.commit()
    return key


def _fake_dns(monkeypatch, ip):
    """Podmienia DNS — testy nigdy nie pytają prawdziwego resolvera."""
    def fake(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    monkeypatch.setattr(socket, "getaddrinfo", fake)


def _reloaded_key(key_id):
    db.session.expire_all()
    return db.session.get(ApiKey, key_id)


def _assert_no_secret_in_audit(secret):
    for row in AuditLog.query.all():
        assert secret not in repr(row.payload)


def test_set_webhook_url_generates_secret_shown_once(auth_client, monkeypatch):
    _fake_dns(monkeypatch, PUBLIC_IP)
    k = _key()
    r = auth_client.post(f"/klucze-api/{k.id}/webhook", data={"url": "  https://erp.example.com/xp/webhook  "})
    assert r.status_code == 200
    key = _reloaded_key(k.id)
    assert key.webhook_url == "https://erp.example.com/xp/webhook"
    assert key.webhook_secret and len(key.webhook_secret) >= 40
    html = _text(r)
    assert "Sekret webhooka — Skopiuj teraz" in html and key.webhook_secret in html
    assert "Zapisano adres webhooka klucza „Hurtownia Alfa — ERP”." in html
    # tylko raz: kolejne wyświetlenie strony nie pokazuje sekretu
    assert key.webhook_secret not in _text(auth_client.get("/klucze-api"))
    # zmiana adresu przy istniejącym sekrecie nie generuje nowego i nie pokazuje starego
    secret = key.webhook_secret
    r = auth_client.post(f"/klucze-api/{k.id}/webhook", data={"url": "https://erp.example.com/xp/inny"})
    key = _reloaded_key(k.id)
    assert key.webhook_url == "https://erp.example.com/xp/inny" and key.webhook_secret == secret
    assert secret not in _text(r) and "Sekret webhooka — Skopiuj teraz" not in _text(r)
    _assert_no_secret_in_audit(secret)
    # pusty adres to błąd, a nie wyczyszczenie
    r = auth_client.post(f"/klucze-api/{k.id}/webhook", data={"url": "  "}, follow_redirects=True)
    assert "Podaj adres webhooka." in _text(r)
    assert _reloaded_key(k.id).webhook_url == "https://erp.example.com/xp/inny"


def test_set_webhook_url_rejects_private_target_with_flash(auth_client, app, monkeypatch):
    app.config.update(WEBHOOK_ALLOW_HTTP=False, WEBHOOK_ALLOWED_HOSTS="")
    _fake_dns(monkeypatch, PUBLIC_IP)
    k = _key()
    auth_client.post(f"/klucze-api/{k.id}/webhook", data={"url": "https://erp.example.com/xp/webhook"})
    secret = _reloaded_key(k.id).webhook_secret
    _fake_dns(monkeypatch, "10.0.0.5")
    r = auth_client.post(f"/klucze-api/{k.id}/webhook", data={"url": "https://wewnetrzny.example.test/hook"},
                         follow_redirects=True)
    assert r.status_code == 200
    html = _text(r)
    assert "alert-danger" in html and "Sekret webhooka" not in html
    key = _reloaded_key(k.id)
    assert key.webhook_url == "https://erp.example.com/xp/webhook" and key.webhook_secret == secret
    # http bez WEBHOOK_ALLOW_HTTP też odrzucony z komunikatem walidacji
    r = auth_client.post(f"/klucze-api/{k.id}/webhook", data={"url": "http://erp.example.com/xp"},
                         follow_redirects=True)
    assert "Adres http:// jest wyłączony" in _text(r)
    assert _reloaded_key(k.id).webhook_url == "https://erp.example.com/xp/webhook"


def test_clear_webhook(auth_client):
    k = make_key("https://erp.example.com/xp/webhook")
    db.session.commit()
    r = auth_client.post(f"/klucze-api/{k.id}/webhook/wyczysc", follow_redirects=True)
    assert "Wyczyszczono webhook klucza „Hurtownia Alfa — ERP”." in _text(r)
    key = _reloaded_key(k.id)
    assert key.webhook_url is None and key.webhook_secret is None


def test_rotate_secret_changes_value_and_shows_once(auth_client):
    k = make_key("https://erp.example.com/xp/webhook")
    db.session.commit()
    old = k.webhook_secret
    r = auth_client.post(f"/klucze-api/{k.id}/webhook/sekret")
    assert r.status_code == 200
    key = _reloaded_key(k.id)
    assert key.webhook_secret and key.webhook_secret != old
    html = _text(r)
    assert key.webhook_secret in html and "Sekret webhooka — Skopiuj teraz" in html and old not in html
    assert key.webhook_secret not in _text(auth_client.get("/klucze-api"))
    _assert_no_secret_in_audit(key.webhook_secret)
    # bez adresu nie ma czego rotować
    bare = _key("Magazyn")
    r = auth_client.post(f"/klucze-api/{bare.id}/webhook/sekret", follow_redirects=True)
    assert "Najpierw ustaw adres webhooka." in _text(r)
    assert _reloaded_key(bare.id).webhook_secret is None


def test_test_event_sends_synchronously_and_lists_result(auth_client, receiver):
    k = make_key(receiver.url)
    db.session.commit()
    r = auth_client.post(f"/klucze-api/{k.id}/webhook/test", follow_redirects=True)
    html = _text(r)
    assert "Zdarzenie testowe wysłane (HTTP 200)." in html
    assert len(receiver.requests) == 1
    d = WebhookDelivery.query.one()
    assert d.event == EVENT_TEST and d.status == WEBHOOK_SENT and d.last_status_code == 200
    assert EVENT_TEST in html and "text-bg-success" in html
    # bez adresu — komunikat, żadnej dostawy
    bare = _key("Magazyn")
    r = auth_client.post(f"/klucze-api/{bare.id}/webhook/test", follow_redirects=True)
    assert "Najpierw ustaw adres webhooka." in _text(r)
    assert WebhookDelivery.query.count() == 1


def test_test_event_failure_is_listed_not_500(auth_client, receiver):
    receiver.set_mode("error")
    k = make_key(receiver.url)
    db.session.commit()
    r = auth_client.post(f"/klucze-api/{k.id}/webhook/test", follow_redirects=True)
    assert r.status_code == 200
    html = _text(r)
    assert "Zdarzenie testowe nieudane: HTTP 500" in html and "alert-danger" in html
    d = WebhookDelivery.query.one()
    assert d.event == EVENT_TEST and d.status == WEBHOOK_PENDING and d.last_status_code == 500
    assert "awaria odbiorcy" in html  # ostatni błąd na liście dostaw


def test_retry_failed_delivery_resets_schedule(auth_client):
    k = make_key("https://erp.example.com/xp/webhook")
    d = make_delivery(k, status=WEBHOOK_FAILED, attempts=6, next_attempt_at=utcnow() + timedelta(hours=12))
    d.last_error, d.last_status_code = "HTTP 503: niedostępny", 503
    db.session.commit()
    page = _text(auth_client.get("/klucze-api"))
    assert f"/klucze-api/dostawy/{d.id}/ponow" in page
    r = auth_client.post(f"/klucze-api/dostawy/{d.id}/ponow", follow_redirects=True)
    assert "Dostawa zaplanowana ponownie." in _text(r)
    db.session.expire_all()
    d = db.session.get(WebhookDelivery, d.id)
    assert (d.status, d.attempts, d.next_attempt_at, d.last_error, d.last_status_code) == (
        WEBHOOK_PENDING, 0, None, None, None)
    # nieistniejąca dostawa i dostawa, która nie jest „failed” — komunikat, bez zmian
    r = auth_client.post("/klucze-api/dostawy/9999/ponow", follow_redirects=True)
    assert "Nie znaleziono dostawy." in _text(r)
    r = auth_client.post(f"/klucze-api/dostawy/{d.id}/ponow", follow_redirects=True)
    assert "Ponowić można tylko nieudaną dostawę." in _text(r)


def test_deliveries_list_limited_to_50_newest(auth_client):
    k = make_key("https://erp.example.com/xp/webhook")
    start = utcnow() - timedelta(days=1)
    for i in range(55):
        db.session.add(WebhookDelivery(api_key_id=k.id, event=EVENT_STATUS_CHANGED, payload={}, status=WEBHOOK_SENT,
                                       created_at=start + timedelta(minutes=i), last_error=f"wpis-nr-{i:02d}"))
    other = make_key("https://magazyn.example.com/hook", name="Magazyn")
    make_delivery(other, status=WEBHOOK_SENT)
    db.session.commit()
    html = _text(auth_client.get("/klucze-api"))
    assert "wpis-nr-54" in html and "wpis-nr-05" in html
    assert "wpis-nr-04" not in html and "wpis-nr-00" not in html
    assert html.index("wpis-nr-54") < html.index("wpis-nr-05")  # od najnowszej
    assert html.count('data-delivery-row') == 51  # 50 z pierwszego klucza + 1 z drugiego
    empty = html.count("Brak dostaw.")  # klucz demo z seeda nie ma dostaw
    _key("Bez dostaw")
    assert _text(auth_client.get("/klucze-api")).count("Brak dostaw.") == empty + 1


def _operator(client):
    u = User(email="operator@example.com", role="operator")
    u.set_password("operator-haslo-1")
    db.session.add(u)
    db.session.commit()
    client.post("/login", data={"email": "operator@example.com", "password": "operator-haslo-1"})
    return client


def test_webhook_actions_require_admin_role(seeded, client):
    k = make_key("https://erp.example.com/xp/webhook")
    d = make_delivery(k, status=WEBHOOK_FAILED, attempts=6)
    c = _operator(client)
    for path in (f"/klucze-api/{k.id}/webhook", f"/klucze-api/{k.id}/webhook/wyczysc",
                 f"/klucze-api/{k.id}/webhook/sekret", f"/klucze-api/{k.id}/webhook/test",
                 f"/klucze-api/dostawy/{d.id}/ponow"):
        assert c.post(path, data={"url": "https://inny.example.com/"}).status_code == 403, path
    key = _reloaded_key(k.id)
    assert key.webhook_url == "https://erp.example.com/xp/webhook"
    assert WebhookDelivery.query.count() == 1 and db.session.get(WebhookDelivery, d.id).status == WEBHOOK_FAILED
    html = _text(c.get("/klucze-api"))
    assert "Hurtownia Alfa — ERP" in html and "tylko administrator" in html
    for text in ("Wyślij testowe zdarzenie", "Rotuj sekret", "/webhook", "Ponów"):
        assert text not in html


@pytest.fixture
def csrf_app(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "test", "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "STORAGE_DIR": str(tmp_path / "s"), "WTF_CSRF_ENABLED": True, "DEMO_MODE": True,
                      "ADMIN_EMAIL": "admin@example.com", "ADMIN_PASSWORD": "haslo123",
                      "DEMO_API_KEY": "xp_test_demo_key"})
    with app.app_context():
        db.create_all()
        from app.services.seed import seed_base, seed_demo
        seed_base()
        seed_demo()
        yield app
        db.session.remove()
        db.drop_all()


def test_webhook_forms_require_csrf(csrf_app):
    client = csrf_app.test_client()
    token = re.search(r'name="csrf-token" content="([^"]+)"', client.get("/login").get_data(as_text=True)).group(1)
    client.post("/login", data={"email": "admin@example.com", "password": "haslo123", "csrf_token": token})
    k = make_key("https://erp.example.com/xp/webhook")
    d = make_delivery(k, status=WEBHOOK_FAILED, attempts=6)
    secret = k.webhook_secret
    for path in (f"/klucze-api/{k.id}/webhook", f"/klucze-api/{k.id}/webhook/wyczysc",
                 f"/klucze-api/{k.id}/webhook/sekret", f"/klucze-api/{k.id}/webhook/test",
                 f"/klucze-api/dostawy/{d.id}/ponow"):
        assert client.post(path, data={"url": "https://inny.example.com/"}).status_code == 400, path
    key = _reloaded_key(k.id)
    assert (key.webhook_url, key.webhook_secret) == ("https://erp.example.com/xp/webhook", secret)
    assert WebhookDelivery.query.count() == 1 and db.session.get(WebhookDelivery, d.id).status == WEBHOOK_FAILED
    # każdy formularz webhooka na stronie niesie token
    html = client.get("/klucze-api").get_data(as_text=True)
    forms = re.findall(r"<form[^>]*>.*?</form>", html, re.S)
    hooks = [f for f in forms if f"/klucze-api/{k.id}/webhook" in f or "/ponow" in f]
    assert len(hooks) == 5 and all('name="csrf_token"' in f for f in hooks)


def test_no_inline_handlers_on_apikeys_with_webhook(auth_client):
    auth_client.post("/demo/wczytaj/alfa-1.xml")
    from app.models import Document
    doc = Document.query.first()
    k = make_key("https://erp.example.com/xp/webhook")
    d = make_delivery(k, status=WEBHOOK_FAILED, attempts=6)
    d.document_id, d.last_error = doc.id, "HTTP 500: " + "x" * 400
    make_delivery(k, status=WEBHOOK_SENT)
    db.session.commit()
    r = auth_client.get("/klucze-api")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert f'href="/dokumenty/{doc.id}"' in html and "Ponów" in html and "cell-truncate" in html
    assert not INLINE_SCRIPT.search(html) and not INLINE_HANDLER.search(html)
