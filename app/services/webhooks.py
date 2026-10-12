"""Wysyłka webhooków z outboxu `WebhookDelivery`: lease (`claim_batch`), podpisane żądanie HTTP na przypięty adres IP
(`send_http`), harmonogram ponowień (`apply_result`), pętla workera (`run_worker`) i retencja (`prune_deliveries`).

Zasady (decyzje 4–7 wydania v0.9.0):
- lease zamiast długiej blokady — `claim_batch` zwiększa `attempts`, odsuwa `next_attempt_at` o LEASE i commituje;
  żądanie HTTP idzie poza transakcją, a wynik zapisuje osobny commit (`apply_result`);
- cel walidowany (anty-SSRF) przy każdej wysyłce; połączenie wyłącznie na adres IP zwrócony przez walidację —
  nazwa hosta nie jest rozwiązywana drugi raz (brak okna na DNS rebinding);
- bez przekierowań (3xx = porażka), limit czasu TIMEOUT, z odpowiedzi czytamy najwyżej READ_LIMIT bajtów.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from flask import current_app

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
LEASE = timedelta(seconds=60)  # ile wiersz pozostaje „zajęty” przez workera, który go pobrał
TIMEOUT = 5.0  # sekundy na całe żądanie (połączenie + odpowiedź)
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

class _PinnedConnection(http.client.HTTPConnection):
    """Połączenie na wskazany adres IP (bez rozwiązywania nazwy), dla https z TLS i SNI/weryfikacją po nazwie."""

    def __init__(self, target: ResolvedTarget, timeout: float):
        super().__init__(target.host, target.port, timeout=timeout)
        self._target = target

    def connect(self):
        sock = socket.create_connection((self._target.ip, self._target.port), self.timeout)
        if self._target.scheme == "https":
            try:
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self._target.host)
            except BaseException:
                sock.close()
                raise
        self.sock = sock


def _host_header(target: ResolvedTarget) -> str:
    host = f"[{target.host}]" if ":" in target.host else target.host
    default = 443 if target.scheme == "https" else 80
    return host if target.port == default else f"{host}:{target.port}"


def send_http(target: ResolvedTarget, body: bytes, headers: dict) -> SendResult:
    """POST `body` na zwalidowany cel; łączy się tylko z `target.ip`. Nigdy nie rzuca wyjątku sieciowego."""
    if not target.ip:
        return SendResult(False, None, "Brak przypiętego adresu IP celu (cel niezwalidowany).")
    deadline = time.monotonic() + TIMEOUT

    def remaining() -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("timed out")
        return left

    conn = _PinnedConnection(target, timeout=TIMEOUT)
    try:
        conn.connect()
        sock = conn.sock  # getresponse() zeruje conn.sock przy „Connection: close” — limit ustawiamy na gnieździe
        sock.settimeout(remaining())
        all_headers = {"Host": _host_header(target), **headers, "Content-Length": str(len(body))}
        conn.request("POST", target.path, body=body, headers=all_headers)
        sock.settimeout(remaining())
        resp = conn.getresponse()
        try:
            sock.settimeout(remaining())
            excerpt = resp.read(READ_LIMIT)
        finally:
            resp.close()
    except TimeoutError:
        return SendResult(False, None, f"Przekroczono limit czasu odpowiedzi odbiorcy ({TIMEOUT:g} s).")
    except (OSError, http.client.HTTPException) as e:
        return SendResult(False, None, _truncate(f"Błąd połączenia: {type(e).__name__}: {e}"))
    finally:
        conn.close()
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


def apply_result(delivery: WebhookDelivery, result: SendResult, now: datetime) -> None:
    """Zapisuje wynik próby (osobny commit). `attempts` zwiększył już lease."""
    delivery.last_status_code = result.status_code
    if result.ok:
        delivery.status = WEBHOOK_SENT
        delivery.sent_at = now
        delivery.next_attempt_at = None
        delivery.last_error = None
    else:
        delivery.last_error = _truncate(result.error or "Nieznany błąd wysyłki.")
        if result.permanent or delivery.attempts >= MAX_ATTEMPTS:
            delivery.status = WEBHOOK_FAILED
            delivery.next_attempt_at = None
        else:
            step = BACKOFF[min(max(delivery.attempts, 1), len(BACKOFF)) - 1]
            delivery.next_attempt_at = now + timedelta(seconds=step)
        current_app.logger.warning("webhook %s (#%s): próba %s nieudana — %s", delivery.uuid, delivery.id,
                                   delivery.attempts, delivery.last_error)
    db.session.commit()


# ---------------------------------------------------------------- lease i pętle

def _due(now: datetime):
    return db.or_(WebhookDelivery.next_attempt_at.is_(None), WebhookDelivery.next_attempt_at <= now)


def _lock(query):
    """`FOR UPDATE SKIP LOCKED` tylko na MariaDB/MySQL (SQLite: jeden pisarz, worker sekwencyjny)."""
    if db.engine.dialect.name in ("mysql", "mariadb"):
        return query.with_for_update(skip_locked=True)
    return query


def claim_batch(now: datetime, limit: int = 50) -> list[WebhookDelivery]:
    """Pobiera do `limit` zaległych dostaw i dzierżawi je (attempts+1, next_attempt_at=now+LEASE); commit."""
    query = (WebhookDelivery.query
             .filter(WebhookDelivery.status == WEBHOOK_PENDING, _due(now))
             .order_by(WebhookDelivery.next_attempt_at, WebhookDelivery.id)
             .limit(limit))
    rows = _lock(query).all()
    for row in rows:
        row.attempts = (row.attempts or 0) + 1
        row.next_attempt_at = now + LEASE
    db.session.commit()
    return rows


def _attempt(delivery: WebhookDelivery, now: datetime) -> SendResult:
    try:
        result = send(delivery, now=now)
    except Exception as e:  # błąd jednej dostawy nie zatrzymuje partii
        current_app.logger.exception("webhook %s (#%s): nieoczekiwany błąd wysyłki", delivery.uuid, delivery.id)
        result = SendResult(False, None, f"Nieoczekiwany błąd wysyłki: {type(e).__name__}: {e}")
    apply_result(delivery, result, now)
    return result


def deliver_pending(now: datetime, limit: int = 50) -> int:
    """Dzierżawi partię, wysyła i zapisuje wyniki; zwraca liczbę dostaw wysłanych pomyślnie."""
    return sum(1 for delivery in claim_batch(now, limit) if _attempt(delivery, now).ok)


def send_now(delivery: WebhookDelivery) -> SendResult:
    """Synchroniczna wysyłka jednej dostawy (panel: „Wyślij testowe zdarzenie”, „Ponów”). Wysyła tylko dostawę
    oczekującą i niezadzierżawioną — inaczej zwraca porażkę bez zmian w bazie."""
    now = utcnow()
    query = WebhookDelivery.query.filter(WebhookDelivery.id == delivery.id,
                                         WebhookDelivery.status == WEBHOOK_PENDING, _due(now))
    row = _lock(query).first()
    if row is None:
        db.session.rollback()
        return SendResult(False, None, "Dostawa nie czeka na wysyłkę (wysłana, porzucona albo właśnie wysyłana).")
    row.attempts = (row.attempts or 0) + 1
    row.next_attempt_at = now + LEASE
    db.session.commit()
    return _attempt(row, now)


def retry(delivery: WebhookDelivery, now: datetime | None = None) -> None:
    """„Ponów”: dostawa wraca do kolejki od zera (ten sam uuid)."""
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
        path.touch()
        os.utime(path)
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
                    sent = deliver_pending(utcnow())
                    if sent:
                        logger.info("webhooks-worker: wysłano %s dostaw", sent)
                finally:
                    db.session.remove()
        except Exception:
            logger.exception("webhooks-worker: błąd iteracji (ponowienie za %s s)", interval)
        _touch(heartbeat, logger)
        stop.wait(interval)
    logger.info("webhooks-worker: stop")
