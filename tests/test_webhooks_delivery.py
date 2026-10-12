"""Wysyłka webhooków (v0.9.0): podpisane żądanie POST na przypięty adres IP, harmonogram ponowień
(60 s, 5 min, 30 min, 2 h, 12 h → `failed` po 6. próbie), brak przekierowań, limit czasu i odczytu odpowiedzi,
ponowna walidacja celu (SSRF) przy każdej wysyłce, lease w `claim_batch`, `send_now`/`retry`, retencja i pętla
workera. Odbiorca to lokalny `ThreadingHTTPServer` na 127.0.0.1 (WEBHOOK_ALLOW_HTTP + allowlista 127.0.0.1)."""
import json
import socket
import threading
import time
from datetime import timedelta

import pytest
import sqlalchemy as sa

from app.extensions import db
from app.models import (
    EVENT_STATUS_CHANGED,
    WEBHOOK_FAILED,
    WEBHOOK_PENDING,
    WEBHOOK_SENT,
    WebhookDelivery,
)
from app.services import webhook_security, webhooks
from app.version import __version__
from tests.conftest import mariadb_url, needs_mariadb  # noqa: F401 (fixture)
from tests.webhook_helpers import NOW, SECRET, make_delivery, make_key, reload


@pytest.fixture(autouse=True)
def frozen_apply_time(monkeypatch):
    """Wynik próby jest zapisywany z `utcnow()` (chwila zapisu); testy z syntetycznym `NOW` zamrażają ten zegar."""
    monkeypatch.setattr(webhooks, "utcnow", lambda: NOW)


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
    assert (d.status, d.attempts, d.next_attempt_at) == (WEBHOOK_SENT, 1, None)
    assert d.sent_at == NOW
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

        def do_handshake(self):
            calls["handshake"] = True

        def shutdown(self, how):
            pass

        def sendall(self, data):
            raise ConnectionResetError("koniec testu")

        def close(self):
            calls["closed"] = True

    class FakeContext:
        def wrap_socket(self, sock, server_hostname=None, do_handshake_on_connect=True):
            calls["sni"] = server_hostname
            calls["deferred_handshake"] = not do_handshake_on_connect
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
    # uścisk po podpięciu watchdoga do gniazda TLS (łączny limit czasu obejmuje też TLS)
    assert calls["deferred_handshake"] and calls["handshake"]
    assert calls.get("closed")
    assert result.ok is False and result.status_code is None and "koniec testu" in result.error


def test_trickling_response_is_cut_at_total_deadline(app, receiver, monkeypatch):
    """Odbiorca sączy status i nagłówki po bajcie co 0,1 s: limit pojedynczego recv nigdy nie mija, ale łączny
    limit czasu (watchdog) przerywa żądanie — worker nie utknie na jednym odbiorcy."""
    monkeypatch.setattr(webhooks, "TIMEOUT", 0.3)
    receiver.set_mode("trickle")
    target = webhook_security.ResolvedTarget(receiver.url, "http", "127.0.0.1", receiver.port, "/hook", "127.0.0.1")
    started = time.monotonic()
    result = webhooks.send_http(target, b"{}", {"Content-Type": "application/json"})
    elapsed = time.monotonic() - started
    assert elapsed < 1, elapsed
    assert result.ok is False and result.status_code is None
    assert "limit czasu" in result.error
    assert len(receiver.requests) == 1


@pytest.mark.parametrize("mode", ["trickle_body_close", "trickle_body_http10"])
def test_trickling_body_after_connection_close_is_cut_at_total_deadline(app, receiver, monkeypatch, mode):
    """`Connection: close` albo HTTP/1.0: http.client zamyka połączenie już w getresponse(), a ciało (sączone po bajcie)
    czytamy później — watchdog musi nadal działać, więc wynik to limit czasu, a nie `HTTP 500: BBB…` po 3 s."""
    monkeypatch.setattr(webhooks, "TIMEOUT", 0.3)
    receiver.set_mode(mode)
    target = webhook_security.ResolvedTarget(receiver.url, "http", "127.0.0.1", receiver.port, "/hook", "127.0.0.1")
    started = time.monotonic()
    result = webhooks.send_http(target, b"{}", {"Content-Type": "application/json"})
    elapsed = time.monotonic() - started
    assert elapsed < 1, elapsed
    assert result.ok is False and result.status_code is None
    assert "limit czasu" in result.error


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


def test_server_error_schedules_backoff_sequence(app, receiver, monkeypatch):
    receiver.set_mode("error")
    d = make_delivery(make_key(receiver.url))
    now = NOW
    delays = []
    for attempt in range(1, 6):
        monkeypatch.setattr(webhooks, "utcnow", lambda n=now: n)  # zegar zapisu wyniku idzie z symulowanym czasem
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
        # dzierżawa pokrywa najgorszy czas całej partii: 50 × TIMEOUT + zapas
        lease = timedelta(seconds=50 * webhooks.TIMEOUT + webhooks.LEASE_MARGIN)
        assert (d.attempts, d.next_attempt_at, d.status) == (attempts, NOW + lease, WEBHOOK_PENDING)
    # wydzierżawione wiersze nie wracają przed końcem lease
    assert [d.id for d in webhooks.claim_batch(NOW + timedelta(seconds=30))] == [future.id]
    assert reload(future).attempts == 1
    assert webhooks.claim_batch(NOW + timedelta(seconds=30)) == []
    # limit; dzierżawa liczona od rozmiaru partii
    rows = [make_delivery(key) for _ in range(3)]
    assert [d.id for d in webhooks.claim_batch(NOW + timedelta(seconds=30), limit=2)] == [r.id for r in rows[:2]]
    assert reload(rows[0]).next_attempt_at == NOW + timedelta(seconds=30 + 2 * webhooks.TIMEOUT + 60)


def test_apply_result_skips_row_changed_during_send(app, receiver, monkeypatch, caplog):
    """Wynik zapisywany warunkowo: gdy w trakcie wysyłki ktoś zresetował wiersz („Ponów” w panelu) albo przejął go
    inny worker, stary wynik nie nadpisuje nowego stanu."""
    import logging
    caplog.set_level(logging.WARNING, logger=app.logger.name)
    d = make_delivery(make_key(receiver.url))
    real_send = webhooks.send

    def send_then_reset(delivery, *, now):
        result = real_send(delivery, now=now)
        db.session.execute(sa.update(WebhookDelivery).where(WebhookDelivery.id == delivery.id)
                           .values(status=WEBHOOK_PENDING, attempts=0, next_attempt_at=None))
        db.session.commit()
        return result

    monkeypatch.setattr(webhooks, "send", send_then_reset)
    assert webhooks.deliver_pending(NOW) == 1  # żądanie wyszło
    d = reload(d)
    assert (d.status, d.attempts, d.next_attempt_at, d.sent_at, d.last_status_code) == \
        (WEBHOOK_PENDING, 0, None, None, None)
    assert any("wynik próby 1 pominięty" in r.getMessage() for r in caplog.records)
    # bez zmiany w międzyczasie wynik jest zapisywany, a apply_result zwraca True
    monkeypatch.setattr(webhooks, "send", real_send)
    assert webhooks.deliver_pending(NOW) == 1
    assert reload(d).status == WEBHOOK_SENT
    stale = make_delivery(make_key(receiver.url, name="Klucz B"), attempts=3)
    assert webhooks.apply_result(stale, webhooks.SendResult(True, 200, None), NOW, claimed_attempts=2) is False
    assert reload(stale).status == WEBHOOK_PENDING


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
    progress = []
    assert webhooks.deliver_pending(NOW, limit=2, on_progress=lambda: progress.append(1)) == 2
    assert len(progress) == 2  # po każdej dostawie (worker odświeża wtedy heartbeat)
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
    # wiersz w trakcie wysyłki (lease) albo czekający na termin — send_now nic nie wysyła i nie cofa ani nie
    # zatwierdza niezacommitowanych zmian wywołującego
    sent_before = len(receiver.requests)
    failed = reload(failed)
    key.name = "Hurtownia Alfa — zmiana w toku"
    result = webhooks.send_now(failed)
    assert not result.ok and result.status_code is None
    assert key.name == "Hurtownia Alfa — zmiana w toku"  # nie cofnięto
    db.session.rollback()
    db.session.expire_all()
    assert key.name == "Hurtownia Alfa — ERP"  # i nie zatwierdzono
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
    mtimes = []
    removes = []
    real = webhooks.deliver_pending
    real_remove = db.session.remove

    def counting(now, limit=50, on_progress=None, stop=None):
        calls.append(now)
        mtimes.append(heartbeat.stat().st_mtime_ns)  # heartbeat istnieje już przed pierwszą rundą
        assert on_progress is not None
        if len(calls) == 2:
            raise RuntimeError("chwilowa awaria bazy")  # błąd iteracji nie zatrzymuje workera
        return real(now, limit, on_progress, stop)

    def counting_remove():
        removes.append(1)
        real_remove()

    monkeypatch.setattr(webhooks, "deliver_pending", counting)
    monkeypatch.setattr(db.session, "remove", counting_remove)
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
    assert mtimes == sorted(mtimes) and mtimes[-1] > mtimes[0]  # heartbeat odświeżany w kolejnych rundach
    assert len(removes) >= len(calls)  # db.session.remove() po każdej rundzie, także po błędzie
    assert reload(d).status == WEBHOOK_SENT
    messages = [r.getMessage() for r in caplog.records]
    assert "webhooks-worker: start" in messages and "webhooks-worker: stop" in messages
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert errors and "chwilowa awaria bazy" in str(errors[0].exc_info[1])


def test_result_time_is_taken_at_apply_not_at_batch_start(app, receiver, monkeypatch):
    """Partia zadzierżawiona o `now` w przeszłości: sent_at/next_attempt_at liczone od chwili zapisu wyniku."""
    past = NOW - timedelta(hours=2)
    monkeypatch.setattr(webhooks, "utcnow", lambda: NOW)
    ok = make_delivery(make_key(receiver.url), doc_id=1)
    assert webhooks.deliver_pending(past) == 1
    assert reload(ok).sent_at == NOW
    receiver.set_mode("error")
    bad = make_delivery(make_key(receiver.url), doc_id=2, next_attempt_at=past)
    assert webhooks.deliver_pending(past) == 0
    assert reload(bad).next_attempt_at == NOW + timedelta(seconds=60)


def test_deliver_pending_stops_between_deliveries(app, receiver):
    key = make_key(receiver.url)
    rows = [make_delivery(key, doc_id=i) for i in (1, 2)]
    stop = threading.Event()
    assert webhooks.deliver_pending(NOW, stop=stop, on_progress=stop.set) == 1
    assert len(receiver.requests) == 1
    states = [reload(d) for d in rows]
    assert states[0].status == WEBHOOK_SENT
    assert states[1].status == WEBHOOK_PENDING and states[1].attempts == 1  # zadzierżawiona, wróci po dzierżawie
    assert states[1].next_attempt_at > NOW


def test_run_worker_exits_promptly_when_stopped_mid_batch(app, receiver, monkeypatch):
    key = make_key(receiver.url)
    rows = [make_delivery(key, doc_id=i) for i in (1, 2, 3)]
    stop = threading.Event()
    real_send = webhooks.send

    def slow_send(delivery, now=None):
        result = real_send(delivery, now=now)
        stop.set()  # SIGTERM w trakcie pierwszej dostawy
        return result

    monkeypatch.setattr(webhooks, "send", slow_send)
    worker = threading.Thread(target=webhooks.run_worker, args=(app,), kwargs={"interval": 30, "stop": stop},
                              daemon=True)
    started = time.monotonic()
    worker.start()
    worker.join(5)
    assert not worker.is_alive() and time.monotonic() - started < 5
    assert len(receiver.requests) == 1
    assert [reload(d).status for d in rows].count(WEBHOOK_PENDING) == 2
