"""Outbox webhooków: zdarzenia zmiany statusu dokumentu zapisywane w tej samej sesji co sama zmiana.

Wiersz `WebhookDelivery` trafia tylko do `db.session` (bez flush/commit) — commit albo rollback wywołującego
decyduje, czy zdarzenie powstanie. Wysyłką (bajty, podpis, ponowienia) zajmuje się worker. Moduł nie importuje
`pipeline` (cykl importów: to pipeline woła outbox)."""
from __future__ import annotations

from flask import current_app, has_request_context, request

from app.extensions import db
from app.models import EVENT_STATUS_CHANGED, EVENT_TEST, ApiKey, Document, WebhookDelivery


def document_url(doc_id: int) -> str | None:
    """Adres dokumentu w panelu: `PUBLIC_BASE_URL`, a bez niej adres bieżącego żądania; poza żądaniem `None`."""
    base = (current_app.config.get("PUBLIC_BASE_URL") or "").strip()
    if not base and has_request_context():
        base = request.host_url
    if not base:
        return None
    return f"{base.rstrip('/')}/dokumenty/{doc_id}"


def build_payload(doc: Document, previous: str | None) -> dict:
    """Ładunek zdarzenia `document.status_changed` (czas w formacie REST API v1: UTC z `Z`)."""
    # import lokalny: pakiet app.api importuje trasy, a te pipeline — import na poziomie modułu dałby cykl
    from app.api.timeutil import format_api_datetime
    return {"event": EVENT_STATUS_CHANGED, "id": doc.id, "status": doc.status, "previous_status": previous,
            "updated_at": format_api_datetime(doc.updated_at), "document_url": document_url(doc.id)}


def _webhook_key(key_id: int | None) -> ApiKey | None:
    key = db.session.get(ApiKey, key_id) if key_id is not None else None
    return key if key is not None and key.active and key.webhook_url else None


def emit_status_change(doc: Document, previous: str | None) -> WebhookDelivery | None:
    """Kolejkuje zdarzenie zmiany statusu dla klucza API dokumentu. Dokument z panelu (bez klucza), klucz
    nieaktywny albo bez adresu webhooka → brak zdarzenia (`None`)."""
    key = _webhook_key(doc.api_key_id)
    if key is None:
        return None
    delivery = WebhookDelivery(api_key_id=key.id, document_id=doc.id, event=EVENT_STATUS_CHANGED,
                               payload=build_payload(doc, previous))
    db.session.add(delivery)
    return delivery


def enqueue_test(key: ApiKey) -> WebhookDelivery:
    """Zdarzenie `webhook.test` w kształcie zdarzenia dokumentu — pola dokumentu puste (`null`)."""
    delivery = WebhookDelivery(api_key_id=key.id, document_id=None, event=EVENT_TEST,
                               payload={"event": EVENT_TEST, "id": None, "status": None, "previous_status": None,
                                        "updated_at": None, "document_url": None})
    db.session.add(delivery)
    return delivery
