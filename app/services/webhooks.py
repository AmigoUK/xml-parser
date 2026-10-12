"""Wysyłka webhooków z outboxu `WebhookDelivery`: lease (`claim_batch`), podpisane żądanie HTTP na przypięty adres IP
(`send_http`), harmonogram ponowień (`apply_result`), pętla workera (`run_worker`) i retencja (`prune_deliveries`).

Zasady (decyzje 4–7 wydania v0.9.0):
- lease zamiast długiej blokady — `claim_batch` zwiększa `attempts`, odsuwa `next_attempt_at` o czas dzierżawy
  (najgorszy czas całej partii: `limit × TIMEOUT + LEASE_MARGIN`) i commituje; żądanie HTTP idzie poza transakcją,
  a wynik zapisuje osobny, warunkowy commit (`apply_result` — tylko gdy wiersz nie zmienił się w międzyczasie);
- cel walidowany (anty-SSRF) przy każdej wysyłce; połączenie wyłącznie na adres IP zwrócony przez walidację —
  nazwa hosta nie jest rozwiązywana drugi raz (brak okna na DNS rebinding);
- bez przekierowań (3xx = porażka), łączny limit czasu TIMEOUT na całe żądanie (watchdog zamyka gniazdo, więc
  odbiorca sączący bajty nie zatrzyma workera), z odpowiedzi czytamy najwyżej READ_LIMIT bajtów;
- rozwiązywanie nazwy (`getaddrinfo` w `validate_target`) nie ma własnego limitu czasu — resolver, który nie
  odpowiada, może w długiej partii przekroczyć zapas dzierżawy i inny worker wyśle tę samą dostawę drugi raz; to
  dopuszczamy (dostawa „co najmniej raz”): `apply_result` zapisuje wynik warunkowo, a odbiorca deduplikuje po
  `X-XP-Delivery` (uuid stały między próbami).
"""

from __future__ import annotations

import http.client
import json
import logging
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from flask import current_app
from sqlalchemy import update

from ..extensions import db
from ..models import WEBHOOK_FAILED, WEBHOOK_PENDING, WEBHOOK_SENT, ApiKey, WebhookDelivery, utcnow
from ..version import __version__
from .webhook_security import (
    HEADER_DELIVERY,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    ResolvedTarget,
    TargetError,
    parse_allowed_hosts,
    sign,
    validate_target,
)

BACKOFF = (60, 300, 1800, 7200, 43200)  # sekundy po 1., 2., …, 5. nieudanej próbie
MAX_ATTEMPTS = 6  # 6. porażka → failed
TIMEOUT = 5.0  # sekundy na całe żądanie (połączenie, TLS, wysłanie, odpowiedź)
LEASE_MARGIN = 60  # sekundy zapasu dzierżawy ponad najgorszy czas partii (DNS, zapis wyników)
READ_LIMIT = 1024  # bajty odpowiedzi czytane do komunikatu błędu
ERROR_LIMIT = 500  # długość zapisywanego last_error
USER_AGENT = f"xml-parser-webhook/{__version__}"


@dataclass(frozen=True)
class SendResult:
    """Wynik jednej próby; `permanent` = porażka bez ponowień (brak adresu/sekretu, klucz nieaktywny)."""

    ok: bool
    status_code: int | None
    error: str | None
    permanent: bool = False


def _truncate(text: str | None) -> str | None:
    if text is None:
        return None
    return text[:ERROR_LIMIT]


# ---------------------------------------------------------------- klient HTTP z przypiętym IP

def _left(deadline: float) -> float:
    """Czas pozostały do `deadline` (monotonic); po jego upływie TimeoutError."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError("timed out")
    return left


class _PinnedConnection(http.client.HTTPConnection):
    """Połączenie na wskazany adres IP (bez rozwiązywania nazwy), dla https z TLS i SNI/weryfikacją po nazwie.

    Łączny limit czasu: limity pojedynczych operacji gniazda to tylko dolna granica (odbiorca może sączyć po bajcie),
    więc od chwili powstania gniazda pilnuje go watchdog (`threading.Timer`), który w terminie robi
    `shutdown(SHUT_RDWR)` — każde czekające `recv`/`send` natychmiast się kończy, a `expired` mówi, dlaczego.
    Watchdog żyje do `stop_watchdog()` w `send_http`, a nie do `close()`: `getresponse()` zamyka połączenie przy
    `Connection: close`/HTTP/1.0, a ciało odpowiedzi czytamy dopiero potem (gniazdo trzyma wtedy `resp.fp`)."""

    def __init__(self, target: ResolvedTarget, deadline: float):
        super().__init__(target.host, target.port, timeout=TIMEOUT)
        self._target = target
        self._deadline = deadline
        self._watched = None
        self._timer = None
        self.expired = False

    def _expire(self):
        self.expired = True
        sock = self._watched
        if sock is not None:
            try:
                # bazowe socket.shutdown, nie SSLSocket.shutdown: to drugie zeruje `_sslobj` i ściga się z wątkiem
                # głównym (AttributeError/ValueError zamiast OSError); samo zamknięcie kierunków fd wystarcza
                socket.socket.shutdown(sock, socket.SHUT_RDWR)
            except OSError:
                pass

    def connect(self):
        sock = socket.create_connection((self._target.ip, self._target.port), _left(self._deadline))
        self._watched = sock
        self._timer = threading.Timer(max(0.0, self._deadline - time.monotonic()), self._expire)
        self._timer.daemon = True
        self._timer.start()
        if self._target.scheme == "https":
            try:
                sock.settimeout(_left(self._deadline))
                # uścisk TLS dopiero po podpięciu watchdoga do gniazda SSL (wrap_socket odłącza pierwotne gniazdo)
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self._target.host,
                                                                do_handshake_on_connect=False)
                self._watched = sock
                if self.expired:
                    raise TimeoutError("timed out")
                sock.do_handshake()
            except BaseException:
                sock.close()
                raise
        self.sock = sock

    def stop_watchdog(self):
        if self._timer is not None:
            self._timer.cancel()


def _host_header(target: ResolvedTarget) -> str:
    host = f"[{target.host}]" if ":" in target.host else target.host
    default = 443 if target.scheme == "https" else 80
    return host if target.port == default else f"{host}:{target.port}"


def send_http(target: ResolvedTarget, body: bytes, headers: dict) -> SendResult:
    """POST `body` na zwalidowany cel; łączy się tylko z `target.ip`. Nigdy nie rzuca wyjątku sieciowego."""
    if not target.ip:
        return SendResult(False, None, "Brak przypiętego adresu IP celu (cel niezwalidowany).")
    deadline = time.monotonic() + TIMEOUT
    timeout_error = SendResult(False, None, f"Przekroczono limit czasu odpowiedzi odbiorcy ({TIMEOUT:g} s).")
    conn = _PinnedConnection(target, deadline)
    try:
        conn.connect()
        sock = conn.sock  # getresponse() zeruje conn.sock przy „Connection: close” — limit ustawiamy na gnieździe
        sock.settimeout(_left(deadline))
        all_headers = {"Host": _host_header(target), **headers, "Content-Length": str(len(body))}
        conn.request("POST", target.path, body=body, headers=all_headers)
        sock.settimeout(_left(deadline))
        resp = conn.getresponse()
        try:
            sock.settimeout(_left(deadline))
            excerpt = resp.read(READ_LIMIT)
        finally:
            resp.close()
    except TimeoutError:
        return timeout_error
    except (OSError, http.client.HTTPException) as e:
        if conn.expired:  # watchdog zamknął gniazdo — skutkiem jest zerwane połączenie, przyczyną limit czasu
            return timeout_error
        return SendResult(False, None, _truncate(f"Błąd połączenia: {type(e).__name__}: {e}"))
    finally:
        conn.stop_watchdog()  # najpierw watchdog — potem fd może zostać zamknięte i (pod innym obiektem) użyte ponownie
        conn.close()
    # Watchdog, który zdążył zadziałać po pełnej odpowiedzi 2xx, a przed `stop_watchdog()`, też daje „limit czasu”:
    # dostawa zostanie ponowiona (dostarczenie „co najmniej raz”, odbiorca deduplikuje po X-XP-Delivery).
    if conn.expired:
        return timeout_error
    if 200 <= resp.status < 300:
        return SendResult(True, resp.status, None)
    text = excerpt.decode("utf-8", errors="replace").strip()
    return SendResult(False, resp.status, _truncate(f"HTTP {resp.status}: {text}" if text else f"HTTP {resp.status}"))


# ---------------------------------------------------------------- wysyłka jednej dostawy

def encode_payload(payload: dict) -> bytes:
    """Bajty ciała żądania — te same, które podpisujemy (kolejność kluczy stała)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def send(delivery: WebhookDelivery, *, now: datetime) -> SendResult:
    """Jedna próba wysyłki (bez zapisu wyniku). `now` służy harmonogramowi; znacznik czasu podpisu to czas bieżący."""
    key = db.session.get(ApiKey, delivery.api_key_id)
    if key is None or not key.active:
        return SendResult(False, None, "Klucz API jest nieaktywny lub usunięty — dostawa porzucona.", True)
    if not (key.webhook_url or "").strip():
        return SendResult(False, None, "Klucz API nie ma ustawionego adresu webhooka — dostawa porzucona.", True)
    if not key.webhook_secret:
        return SendResult(False, None, "Brak sekretu podpisu webhooka dla klucza API — dostawa porzucona.", True)
    cfg = current_app.config
    try:
        target = validate_target(key.webhook_url, allow_http=bool(cfg.get("WEBHOOK_ALLOW_HTTP")),
                                 allowed_hosts=parse_allowed_hosts(cfg.get("WEBHOOK_ALLOWED_HOSTS") or ""),
                                 resolve=True)
    except TargetError as e:
        return SendResult(False, None, str(e))
    body = encode_payload(delivery.payload)
    ts = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        HEADER_TIMESTAMP: ts,
        HEADER_SIGNATURE: sign(key.webhook_secret, ts, body),
        HEADER_DELIVERY: delivery.uuid,
    }
    return send_http(target, body, headers)


def apply_result(delivery: WebhookDelivery, result: SendResult, now: datetime, *,
                 claimed_attempts: int | None = None) -> bool:
    """Zapisuje wynik próby osobnym commitem — warunkowo: tylko gdy wiersz nadal jest `pending` z licznikiem prób
    z dzierżawy (`claimed_attempts`, domyślnie bieżące `delivery.attempts`). Jeśli w trakcie wysyłki ktoś go zmienił
    („Ponów” w panelu, inny worker po wygaśnięciu dzierżawy), wynik jest pomijany i zwracane jest False."""
    delivery_id, uuid = delivery.id, delivery.uuid
    attempts = delivery.attempts if claimed_attempts is None else claimed_attempts
    values = {"last_status_code": result.status_code}
    if result.ok:
        values.update(status=WEBHOOK_SENT, sent_at=now, next_attempt_at=None, last_error=None)
    else:
        values["last_error"] = _truncate(result.error or "Nieznany błąd wysyłki.")
        if result.permanent or attempts >= MAX_ATTEMPTS:
            values.update(status=WEBHOOK_FAILED, next_attempt_at=None)
        else:
            step = BACKOFF[min(max(attempts, 1), len(BACKOFF)) - 1]
            values["next_attempt_at"] = now + timedelta(seconds=step)
    stmt = (update(WebhookDelivery)
            .where(WebhookDelivery.id == delivery_id, WebhookDelivery.status == WEBHOOK_PENDING,
                   WebhookDelivery.attempts == attempts)
            .values(**values)
            .execution_options(synchronize_session=False))
    applied = db.session.execute(stmt).rowcount == 1
    db.session.commit()  # wygasza obiekty sesji — kolejny odczyt `delivery` pokaże stan z bazy
    if not applied:
        current_app.logger.warning("webhook %s (#%s): wiersz zmienił się w trakcie wysyłki — wynik próby %s pominięty",
                                   uuid, delivery_id, attempts)
    elif not result.ok:
        current_app.logger.warning("webhook %s (#%s): próba %s nieudana — %s", uuid, delivery_id, attempts,
                                   values["last_error"])
    return applied


# ---------------------------------------------------------------- lease i pętle

def _due(now: datetime):
    return db.or_(WebhookDelivery.next_attempt_at.is_(None), WebhookDelivery.next_attempt_at <= now)


def _lock(query):
    """`FOR UPDATE SKIP LOCKED` tylko na MariaDB/MySQL (SQLite: jeden pisarz, worker sekwencyjny)."""
    if db.engine.dialect.name in ("mysql", "mariadb"):
        return query.with_for_update(skip_locked=True)
    return query


def lease_for(limit: int) -> timedelta:
    """Dzierżawa partii: najgorszy czas wysyłki wszystkich jej dostaw (`limit × TIMEOUT`) plus zapas — wiersz nie
    może wrócić do kolejki innego workera, zanim ten, który go pobrał, zdąży go wysłać."""
    return timedelta(seconds=limit * TIMEOUT + LEASE_MARGIN)


def _claim(query, now: datetime, limit: int) -> list[tuple[WebhookDelivery, int]]:
    """Dzierżawi wiersze z zapytania; zwraca pary (wiersz, licznik prób z dzierżawy) — licznik zapamiętany przed
    commitem, bo po nim obiekt jest wygaszony, a ponowny odczyt mógłby już zobaczyć cudzą zmianę."""
    rows = _lock(query).all()
    claimed = []
    lease_until = now + lease_for(limit)
    for row in rows:
        row.attempts = (row.attempts or 0) + 1
        row.next_attempt_at = lease_until
        claimed.append((row, row.attempts))
    if claimed:  # pusty wynik: nic do zapisania, sesja wywołującego zostaje nietknięta
        db.session.commit()
    return claimed


def _pending_due(now: datetime):
    return WebhookDelivery.query.filter(WebhookDelivery.status == WEBHOOK_PENDING, _due(now))


def claim_batch(now: datetime, limit: int = 50) -> list[WebhookDelivery]:
    """Pobiera do `limit` zaległych dostaw i dzierżawi je (attempts+1, next_attempt_at=now+lease_for(limit));
    commit."""
    return [row for row, _ in _claim_batch(now, limit)]


def _claim_batch(now: datetime, limit: int) -> list[tuple[WebhookDelivery, int]]:
    query = _pending_due(now).order_by(WebhookDelivery.next_attempt_at, WebhookDelivery.id).limit(limit)
    return _claim(query, now, limit)


def _attempt(delivery: WebhookDelivery, claimed_attempts: int, now: datetime) -> SendResult:
    try:
        result = send(delivery, now=now)
    except Exception as e:  # błąd jednej dostawy nie zatrzymuje partii
        current_app.logger.exception("webhook %s (#%s): nieoczekiwany błąd wysyłki", delivery.uuid, delivery.id)
        result = SendResult(False, None, f"Nieoczekiwany błąd wysyłki: {type(e).__name__}: {e}")
    apply_result(delivery, result, now, claimed_attempts=claimed_attempts)
    return result


def deliver_pending(now: datetime, limit: int = 50, on_progress=None) -> int:
    """Dzierżawi partię, wysyła i zapisuje wyniki; zwraca liczbę dostaw wysłanych pomyślnie. `on_progress()` jest
    wołane po każdej dostawie (worker odświeża wtedy heartbeat, więc długa partia nie wywraca healthchecku)."""
    sent = 0
    for delivery, attempts in _claim_batch(now, limit):
        if _attempt(delivery, attempts, now).ok:
            sent += 1
        if on_progress is not None:
            on_progress()
    return sent


def send_now(delivery: WebhookDelivery) -> SendResult:
    """Synchroniczna wysyłka jednej dostawy (panel: „Wyślij testowe zdarzenie”, „Ponów”).

    Wywołujący musi wcześniej zacommitować swoje zmiany (np. nowy wiersz z `enqueue_test` albo `retry`) — tu jest
    jeden commit dzierżawy i jeden commit wyniku. Wysyła tylko dostawę oczekującą i niezadzierżawioną; inaczej
    zwraca porażkę, nie zmieniając bazy ani sesji wywołującego."""
    now = utcnow()
    claimed = _claim(_pending_due(now).filter(WebhookDelivery.id == delivery.id), now, 1)
    if not claimed:
        return SendResult(False, None, "Dostawa nie czeka na wysyłkę (wysłana, porzucona albo właśnie wysyłana).")
    row, attempts = claimed[0]
    return _attempt(row, attempts, now)


def retry(delivery: WebhookDelivery, now: datetime | None = None) -> None:
    """„Ponów”: dostawa wraca do kolejki od zera (ten sam uuid) i jest wymagalna od razu. `now` jest
    zarezerwowane (kontrakt) — wymagalność „od razu” oznacza `next_attempt_at = None`, niezależnie od zegara."""
    delivery.status = WEBHOOK_PENDING
    delivery.attempts = 0
    delivery.next_attempt_at = None
    delivery.last_error = None
    delivery.last_status_code = None
    db.session.commit()


def prune_deliveries(days: int) -> int:
    """Usuwa wysłane i porzucone dostawy starsze niż `days` dni (oczekujące zostają); bez commitu."""
    if days <= 0:
        raise ValueError("Retencja musi wynosić co najmniej 1 dzień.")
    cutoff = utcnow() - timedelta(days=days)
    return (WebhookDelivery.query
            .filter(WebhookDelivery.status.in_((WEBHOOK_SENT, WEBHOOK_FAILED)), WebhookDelivery.created_at < cutoff)
            .delete(synchronize_session=False))


def _touch(heartbeat: str | None, logger: logging.Logger) -> None:
    if not heartbeat:
        return
    try:
        path = Path(heartbeat)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()  # aktualizuje mtime także istniejącego pliku
    except OSError:
        logger.warning("webhooks-worker: nie udało się zapisać heartbeatu %s", heartbeat, exc_info=True)


def run_worker(app, *, interval: float = 5.0, stop: threading.Event, heartbeat: str | None = None) -> None:
    """Pętla workera: co `interval` s wysyła zaległe dostawy, aż `stop` zostanie ustawione (SIGTERM/SIGINT)."""
    logger = app.logger
    logger.info("webhooks-worker: start")
    while not stop.is_set():
        _touch(heartbeat, logger)
        try:
            with app.app_context():
                try:
                    sent = deliver_pending(utcnow(), on_progress=lambda: _touch(heartbeat, logger))
                    if sent:
                        logger.info("webhooks-worker: wysłano %s dostaw", sent)
                finally:
                    db.session.remove()
        except Exception:
            logger.exception("webhooks-worker: błąd iteracji (ponowienie za %s s)", interval)
        _touch(heartbeat, logger)
        stop.wait(interval)
    logger.info("webhooks-worker: stop")
