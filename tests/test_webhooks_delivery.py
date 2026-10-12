"""Wysyłka webhooków (v0.9.0): podpisane żądanie POST na przypięty adres IP, harmonogram ponowień
(60 s, 5 min, 30 min, 2 h, 12 h → `failed` po 6. próbie), brak przekierowań, limit czasu i odczytu odpowiedzi,
ponowna walidacja celu (SSRF) przy każdej wysyłce, lease w `claim_batch`, `send_now`/`retry`, retencja i pętla
workera. Odbiorca to lokalny `ThreadingHTTPServer` na 127.0.0.1 (WEBHOOK_ALLOW_HTTP + allowlista 127.0.0.1)."""
import json
import os
import socket
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import sqlalchemy as sa

from app.extensions import db
from app.models import (
    EVENT_STATUS_CHANGED,
    WEBHOOK_FAILED,
    WEBHOOK_PENDING,
    WEBHOOK_SENT,
    ApiKey,
    WebhookDelivery,
    utcnow,
)
from app.services import webhook_security, webhooks
from app.version import __version__
from tests.conftest import mariadb_url, needs_mariadb  # noqa: F401 (fixture)

SECRET = "sekret-testowy-hurtowni-alfa"
NOW = utcnow().replace(microsecond=0)
SHUTDOWN_POLL = 0.05


# ---------------------------------------------------------------- odbiorca testowy

class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):  # zerwane połączenia (timeout klienta) nie brudzą wyjścia
        pass


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _record(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.requests.append({"method": self.command, "path": self.path, "headers": dict(self.headers),
                                     "body": body})

    def _reply(self, code, body=b"", headers=()):
        self.send_response(code)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._record()
        self._reply(200, b"ok")

    def do_POST(self):
        self._record()
        mode = self.server.mode
        try:
            if mode == "ok":
                self._reply(200, b"ok")
            elif mode == "error":
                self._reply(500, b"awaria odbiorcy")
            elif mode == "redirect":
                self._reply(302, b"", [("Location", "/inne")])
            elif mode == "slow":
                self.server.release.wait(5)
                self._reply(200, b"za pozno")
            elif mode == "big":
                # zapowiada 10 MB, wysyła 2 KB i czeka — pełny odczyt zawisłby do limitu czasu
                self.send_response(500)
                self.send_header("Content-Length", str(10 * 1024 * 1024))
                self.end_headers()
                self.wfile.write(b"B" * 2048)
                self.wfile.flush()
                self.server.release.wait(5)
        except OSError:
            pass


class Receiver:
    def __init__(self):
        self.server = _Server(("127.0.0.1", 0), _Handler)
        self.server.requests = []
        self.server.mode = "ok"
        self.server.release = threading.Event()
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/hook?zrodlo=xp"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": SHUTDOWN_POLL},
                                       daemon=True)
        self.thread.start()

    @property
    def requests(self):
        return self.server.requests

    def set_mode(self, mode):
        self.server.mode = mode

    def close(self):
        self.server.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


@pytest.fixture
def receiver(app):
    app.config.update(WEBHOOK_ALLOW_HTTP=True, WEBHOOK_ALLOWED_HOSTS="127.0.0.1")
    rec = Receiver()
    try:
        yield rec
    finally:
        rec.close()


@pytest.fixture
def no_connection(monkeypatch):
    """Każda próba połączenia z celem kończy test błędem (cel zablokowany = zero ruchu sieciowego)."""
    def boom(*args, **kwargs):
        raise AssertionError(f"niedozwolone połączenie: {args!r}")
    monkeypatch.setattr(webhooks.socket, "create_connection", boom)


def make_key(url, *, secret=SECRET, active=True, name="Hurtownia Alfa — ERP"):
    key = ApiKey(name=name, prefix="xp_test", key_hash=os.urandom(32).hex(), active=active, webhook_url=url,
                 webhook_secret=secret)
    db.session.add(key)
    db.session.flush()
    return key


def make_delivery(key, *, doc_id=7, status=WEBHOOK_PENDING, next_attempt_at=None, created_at=None, attempts=0):
    payload = {"event": EVENT_STATUS_CHANGED, "id": doc_id, "status": "approved", "previous_status": "received",
               "updated_at": "2026-10-12T10:00:00Z", "document_url": f"https://xp.example.test/dokumenty/{doc_id}"}
    d = WebhookDelivery(api_key_id=key.id, event=EVENT_STATUS_CHANGED, payload=payload, status=status,
                        next_attempt_at=next_attempt_at, attempts=attempts)
    if created_at is not None:
        d.created_at = created_at
    db.session.add(d)
    db.session.commit()
    return d


def reload(delivery):
    db.session.expire_all()
    return db.session.get(WebhookDelivery, delivery.id)


# ---------------------------------------------------------------- wysyłka

def test_deliver_sends_signed_request_and_marks_sent(app, receiver):
    key = make_key(receiver.url)
    d = make_delivery(key)
    assert webhooks.deliver_pending(NOW) == 1
    assert len(receiver.requests) == 1
    req = receiver.requests[0]
    h = req["headers"]
    assert req["method"] == "POST" and req["path"] == "/hook?zrodlo=xp"
    assert h["Content-Type"] == "application/json"
    assert h["User-Agent"] == f"xml-parser-webhook/{__version__}"
    assert h["Host"] == f"127.0.0.1:{receiver.port}"
    assert h[webhook_security.HEADER_DELIVERY] == d.uuid
    assert int(h["Content-Length"]) == len(req["body"])
    ts = h[webhook_security.HEADER_TIMESTAMP]
    assert abs(int(ts) - time.time()) < 60
    assert webhook_security.verify(SECRET, ts, req["body"], h[webhook_security.HEADER_SIGNATURE])
    assert req["body"] == json.dumps(d.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert json.loads(req["body"])["event"] == EVENT_STATUS_CHANGED
    d = reload(d)
    assert (d.status, d.attempts, d.sent_at, d.next_attempt_at) == (WEBHOOK_SENT, 1, NOW, None)
    assert (d.last_status_code, d.last_error) == (200, None)


def test_connects_to_pinned_ip_with_original_host_header(app, receiver, monkeypatch):
    """Nazwa hosta rozwiązana raz w walidacji; połączenie idzie na przypięty IP, nagłówek Host zostaje oryginalny."""
    real = socket.getaddrinfo
    lookups = []

    def fake_getaddrinfo(host, *args, **kwargs):
        lookups.append(host)
        if host == "odbiorca.example.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", receiver.port))]
        return real(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    app.config["WEBHOOK_ALLOWED_HOSTS"] = "odbiorca.example.test"
    d = make_delivery(make_key(f"http://odbiorca.example.test:{receiver.port}/hook"))
    assert webhooks.deliver_pending(NOW) == 1
    assert lookups.count("odbiorca.example.test") == 1
    assert receiver.requests[0]["headers"]["Host"] == f"odbiorca.example.test:{receiver.port}"
    assert reload(d).status == WEBHOOK_SENT


def test_https_wraps_pinned_socket_with_sni(monkeypatch):
    """https: gniazdo na przypięty IP owinięte TLS z `server_hostname` = oryginalna nazwa (weryfikacja certyfikatu)."""
    calls = {}

    class FakeSock:
        def settimeout(self, value):
            pass

        def sendall(self, data):
            raise ConnectionResetError("koniec testu")

        def close(self):
            calls["closed"] = True

    class FakeContext:
        def wrap_socket(self, sock, server_hostname=None):
            calls["sni"] = server_hostname
            return sock

    def fake_connect(address, timeout=None):
        calls["address"] = address
        return FakeSock()

    monkeypatch.setattr(webhooks.socket, "create_connection", fake_connect)
    monkeypatch.setattr(webhooks.ssl, "create_default_context", FakeContext)
    target = webhook_security.ResolvedTarget("https://hooks.example.test/x", "https", "hooks.example.test", 443,
                                             "/x", "203.0.113.10")
    result = webhooks.send_http(target, b"{}", {"Content-Type": "application/json"})
    assert calls["address"] == ("203.0.113.10", 443)
    assert calls["sni"] == "hooks.example.test"
    assert calls.get("closed")
    assert result.ok is False and result.status_code is None and "koniec testu" in result.error


def test_delivery_uuid_stable_across_retries(app, receiver):
    receiver.set_mode("error")
    d = make_delivery(make_key(receiver.url))
    now = NOW
    for delay in (0, 60, 300):
        now += timedelta(seconds=delay)
        webhooks.deliver_pending(now)
    receiver.set_mode("ok")
    webhooks.deliver_pending(now + timedelta(seconds=1800))
    ids = {r["headers"][webhook_security.HEADER_DELIVERY] for r in receiver.requests}
    assert len(receiver.requests) == 4
    assert ids == {d.uuid}
    d = reload(d)
    assert (d.status, d.attempts) == (WEBHOOK_SENT, 4)


def test_server_error_schedules_backoff_sequence(app, receiver):
    receiver.set_mode("error")
    d = make_delivery(make_key(receiver.url))
    now = NOW
    delays = []
    for attempt in range(1, 6):
        assert webhooks.deliver_pending(now) == 0
        d = reload(d)
        assert (d.status, d.attempts) == (WEBHOOK_PENDING, attempt)
        delays.append(int((d.next_attempt_at - now).total_seconds()))
        # przed terminem nic nie wychodzi
        assert webhooks.deliver_pending(d.next_attempt_at - timedelta(seconds=1)) == 0
        assert len(receiver.requests) == attempt
        now = d.next_attempt_at
    assert delays == [60, 300, 1800, 7200, 43200]
    assert list(webhooks.BACKOFF) == delays and webhooks.MAX_ATTEMPTS == 6


def test_sixth_failure_marks_failed_with_last_error_and_code(app, receiver):
    receiver.set_mode("error")
    d = make_delivery(make_key(receiver.url))
    now = NOW
    for _ in range(6):
        webhooks.deliver_pending(now)
        d = reload(d)
        now = (d.next_attempt_at or now) + timedelta(seconds=1)
    assert (d.status, d.attempts, d.next_attempt_at, d.sent_at) == (WEBHOOK_FAILED, 6, None, None)
    assert d.last_status_code == 500
    assert d.last_error.startswith("HTTP 500") and "awaria odbiorcy" in d.last_error
    assert webhooks.deliver_pending(now + timedelta(days=2)) == 0
    assert len(receiver.requests) == 6


def test_apply_result_truncates_last_error(app):
    d = make_delivery(make_key("https://hooks.example.test/x"), attempts=1)
    webhooks.apply_result(d, webhooks.SendResult(False, 502, "x" * 5000), NOW)
    d = reload(d)
    assert len(d.last_error) == 500
    assert (d.status, d.next_attempt_at, d.last_status_code) == (WEBHOOK_PENDING, NOW + timedelta(seconds=60), 502)


def test_redirect_302_is_failure_not_followed(app, receiver):
    receiver.set_mode("redirect")
    d = make_delivery(make_key(receiver.url))
    assert webhooks.deliver_pending(NOW) == 0
    assert [(r["method"], r["path"]) for r in receiver.requests] == [("POST", "/hook?zrodlo=xp")]
    d = reload(d)
    assert (d.status, d.last_status_code) == (WEBHOOK_PENDING, 302)
    assert d.last_error.startswith("HTTP 302")


def test_timeout_is_failure(app, receiver, monkeypatch):
    monkeypatch.setattr(webhooks, "TIMEOUT", 0.3)
    receiver.set_mode("slow")
    d = make_delivery(make_key(receiver.url))
    started = time.monotonic()
    assert webhooks.deliver_pending(NOW) == 0
    assert time.monotonic() - started < 2
    d = reload(d)
    assert (d.status, d.attempts, d.last_status_code) == (WEBHOOK_PENDING, 1, None)
    assert "czas" in d.last_error.lower()
    assert d.next_attempt_at == NOW + timedelta(seconds=60)


def test_response_read_limited_to_1kb(app, receiver, monkeypatch):
    monkeypatch.setattr(webhooks, "TIMEOUT", 2.0)
    receiver.set_mode("big")
    d = make_delivery(make_key(receiver.url))
    started = time.monotonic()
    assert webhooks.deliver_pending(NOW) == 0
    assert time.monotonic() - started < 1.5  # pełny odczyt czekałby do limitu czasu
    d = reload(d)
    assert d.last_status_code == 500
    assert "B" * 100 in d.last_error and "czas" not in d.last_error.lower()
    assert len(d.last_error) <= 500


def test_blocked_target_fails_without_connection(app, no_connection):
    """Bez allowlisty: loopback, sieć prywatna, metadata chmury i http bez WEBHOOK_ALLOW_HTTP — żadnego połączenia."""
    app.config.update(WEBHOOK_ALLOW_HTTP=False, WEBHOOK_ALLOWED_HOSTS="")
    urls = ["https://127.0.0.1/hook", "https://10.0.0.5/hook", "https://169.254.169.254/latest",
            "http://203.0.113.10/hook"]
    rows = [make_delivery(make_key(u, name=f"Klucz {i}")) for i, u in enumerate(urls)]
    assert webhooks.deliver_pending(NOW) == 0
    for d in rows:
        d = reload(d)
        assert (d.status, d.attempts, d.last_status_code) == (WEBHOOK_PENDING, 1, None)
        assert d.next_attempt_at == NOW + timedelta(seconds=60)  # zwykły backoff, nie porażka trwała
        assert d.last_error
    assert "SSRF" in reload(rows[0]).last_error
    assert "https" in reload(rows[3]).last_error


def test_target_revalidated_at_send_time(app, receiver, monkeypatch):
    """Adres poprawny przy zapisie, ale przy wysyłce (zmiana DNS lub konfiguracji) wskazuje sieć wewnętrzną."""
    key = make_key(receiver.url)
    first = make_delivery(key)
    assert webhooks.deliver_pending(NOW) == 1
    assert reload(first).status == WEBHOOK_SENT
    # 1) administrator zdjął 127.0.0.1 z allowlisty
    app.config["WEBHOOK_ALLOWED_HOSTS"] = ""
    second = make_delivery(key)
    assert webhooks.deliver_pending(NOW) == 0
    assert "SSRF" in reload(second).last_error
    # 2) DNS rebinding: nazwa, która była publiczna, teraz rozwiązuje się na adres metadata
    key.webhook_url = "http://hooks.example.test/hook"
    db.session.commit()
    real = socket.getaddrinfo

    def rebinding(host, *args, **kwargs):
        if host == "hooks.example.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))]
        return real(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", rebinding)
    monkeypatch.setattr(webhooks.socket, "create_connection",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("połączenie z zablokowanym celem")))
    third = make_delivery(key)
    assert webhooks.deliver_pending(NOW) == 0
    assert "169.254.169.254" in reload(third).last_error
    assert len(receiver.requests) == 1


def test_missing_url_or_inactive_key_marks_failed(app, no_connection):
    cases = [
        make_delivery(make_key(None, name="Bez adresu")),
        make_delivery(make_key("", name="Pusty adres")),
        make_delivery(make_key("https://hooks.example.test/x", active=False, name="Nieaktywny")),
        make_delivery(make_key("https://hooks.example.test/x", secret=None, name="Bez sekretu")),
    ]
    assert webhooks.deliver_pending(NOW) == 0
    errors = []
    for d in cases:
        d = reload(d)
        assert (d.status, d.attempts, d.next_attempt_at, d.last_status_code) == (WEBHOOK_FAILED, 1, None, None)
        errors.append(d.last_error)
    assert all(errors)
    assert "adres" in errors[0].lower() and "nieaktywny" in errors[2].lower() and "sekret" in errors[3].lower()


# ---------------------------------------------------------------- lease i harmonogram

def test_claim_sets_lease_and_attempts(app):
    key = make_key("https://hooks.example.test/x")
    due_null = make_delivery(key)
    due_past = make_delivery(key, next_attempt_at=NOW - timedelta(minutes=5), attempts=2)
    future = make_delivery(key, next_attempt_at=NOW + timedelta(seconds=1))
    make_delivery(key, status=WEBHOOK_SENT)
    make_delivery(key, status=WEBHOOK_FAILED)
    claimed = webhooks.claim_batch(NOW)
    assert [d.id for d in claimed] == [due_null.id, due_past.id]
    for d, attempts in ((due_null, 1), (due_past, 3)):
        d = reload(d)
        assert (d.attempts, d.next_attempt_at, d.status) == (attempts, NOW + timedelta(seconds=60), WEBHOOK_PENDING)
    # wydzierżawione wiersze nie wracają przed końcem lease
    assert [d.id for d in webhooks.claim_batch(NOW + timedelta(seconds=30))] == [future.id]
    assert reload(future).attempts == 1
    assert webhooks.claim_batch(NOW + timedelta(seconds=30)) == []
    # limit
    for _ in range(3):
        make_delivery(key)
    assert len(webhooks.claim_batch(NOW + timedelta(seconds=30), limit=2)) == 2


@needs_mariadb
def test_claim_skips_rows_locked_by_other_connection(mariadb_url, tmp_path):
    """MariaDB: wiersz zablokowany przez innego workera (SELECT … FOR UPDATE) jest pomijany (SKIP LOCKED)."""
    from app import create_app
    app = create_app({"TESTING": True, "SECRET_KEY": "x", "SQLALCHEMY_DATABASE_URI": mariadb_url,
                      "STORAGE_DIR": str(tmp_path / "s"), "DEMO_MODE": True, "ADMIN_PASSWORD": ""})
    engine = sa.create_engine(mariadb_url)
    try:
        with app.app_context():
            db.create_all()
            key = make_key("https://hooks.example.test/x")
            locked, free = make_delivery(key), make_delivery(key)
            locked_id, free_id = locked.id, free.id
            with engine.connect() as other:
                trans = other.begin()
                other.execute(sa.text("SELECT id FROM webhook_deliveries WHERE id = :i FOR UPDATE"), {"i": locked_id})
                claimed = webhooks.claim_batch(NOW)
                assert [d.id for d in claimed] == [free_id]
                trans.rollback()
            assert [d.id for d in webhooks.claim_batch(NOW)] == [locked_id]
            db.session.remove()
            db.drop_all()
    finally:
        engine.dispose()
        with app.app_context():
            db.engine.dispose()


def test_deliver_pending_sqlite_sequential(app, receiver):
    key = make_key(receiver.url)
    rows = [make_delivery(key, doc_id=i) for i in range(1, 4)]
    later = make_delivery(key, doc_id=9, next_attempt_at=NOW + timedelta(hours=1))
    make_delivery(key, doc_id=10, status=WEBHOOK_SENT)
    assert webhooks.deliver_pending(NOW, limit=2) == 2
    assert webhooks.deliver_pending(NOW) == 1
    assert [json.loads(r["body"])["id"] for r in receiver.requests] == [1, 2, 3]
    assert all(reload(d).status == WEBHOOK_SENT for d in rows)
    assert reload(later).status == WEBHOOK_PENDING and reload(later).attempts == 0


def test_send_now_and_retry_reset(app, receiver):
    key = make_key(receiver.url)
    d = make_delivery(key)
    result = webhooks.send_now(d)
    assert result.ok and result.status_code == 200
    d = reload(d)
    assert (d.status, d.attempts, d.last_status_code) == (WEBHOOK_SENT, 1, 200)
    # porażka trwała → „Ponów” resetuje licznik i błąd, kolejna wysyłka zaczyna od zera
    failed = make_delivery(key, status=WEBHOOK_FAILED, attempts=6)
    failed.last_error, failed.last_status_code = "HTTP 500: awaria", 500
    db.session.commit()
    webhooks.retry(failed, NOW)
    failed = reload(failed)
    assert (failed.status, failed.attempts, failed.next_attempt_at, failed.last_error, failed.last_status_code) == \
        (WEBHOOK_PENDING, 0, None, None, None)
    receiver.set_mode("error")
    result = webhooks.send_now(failed)
    assert not result.ok and result.status_code == 500
    failed = reload(failed)
    assert (failed.status, failed.attempts, failed.last_status_code) == (WEBHOOK_PENDING, 1, 500)
    # wiersz w trakcie wysyłki (lease) albo czekający na termin — send_now nic nie wysyła
    sent_before = len(receiver.requests)
    result = webhooks.send_now(failed)
    assert not result.ok and result.status_code is None
    assert len(receiver.requests) == sent_before and reload(failed).attempts == 1


def test_prune_deliveries_only_sent_failed_older_than_days(app):
    key = make_key("https://hooks.example.test/x")
    old = NOW - timedelta(days=31)
    fresh = NOW - timedelta(days=29)
    make_delivery(key, status=WEBHOOK_SENT, created_at=old)
    make_delivery(key, status=WEBHOOK_FAILED, created_at=old)
    keep = {make_delivery(key, status=WEBHOOK_PENDING, created_at=old).id,
            make_delivery(key, status=WEBHOOK_SENT, created_at=fresh).id,
            make_delivery(key, status=WEBHOOK_FAILED, created_at=fresh).id}
    assert webhooks.prune_deliveries(30) == 2
    db.session.commit()
    assert {d.id for d in WebhookDelivery.query.all()} == keep
    for bad in (0, -1):
        with pytest.raises(ValueError):
            webhooks.prune_deliveries(bad)


# ---------------------------------------------------------------- worker

def test_run_worker_stops_on_event_and_touches_heartbeat(app, receiver, tmp_path, caplog, monkeypatch):
    import logging
    caplog.set_level(logging.INFO, logger=app.logger.name)
    d = make_delivery(make_key(receiver.url))
    heartbeat = tmp_path / "hb" / "worker.heartbeat"
    stop = threading.Event()
    calls = []
    real = webhooks.deliver_pending

    def counting(now, limit=50):
        calls.append(now)
        if len(calls) == 2:
            raise RuntimeError("chwilowa awaria bazy")  # błąd iteracji nie zatrzymuje workera
        return real(now, limit)

    monkeypatch.setattr(webhooks, "deliver_pending", counting)
    worker = threading.Thread(target=webhooks.run_worker, args=(app,),
                              kwargs={"interval": 0.01, "stop": stop, "heartbeat": str(heartbeat)}, daemon=True)
    try:
        worker.start()
        deadline = time.monotonic() + 5
        while (len(calls) < 4 or not heartbeat.exists()) and time.monotonic() < deadline:
            time.sleep(0.01)
        first_mtime = heartbeat.stat().st_mtime
        stop.set()
        worker.join(5)
    finally:
        stop.set()
    assert not worker.is_alive()
    assert len(calls) >= 4
    assert time.time() - first_mtime < 10
    assert reload(d).status == WEBHOOK_SENT
    messages = [r.getMessage() for r in caplog.records]
    assert "webhooks-worker: start" in messages and "webhooks-worker: stop" in messages
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert errors and "chwilowa awaria bazy" in str(errors[0].exc_info[1])
