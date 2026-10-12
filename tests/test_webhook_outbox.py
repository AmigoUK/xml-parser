"""Webhooki (v0.9.0): emisja zdarzeń zmiany statusu dokumentu do outboxu `webhook_deliveries`.

Wiersz outboxu powstaje w tej samej sesji co zmiana dokumentu (bez flush) — commit albo rollback wywołującego
decyduje, czy zdarzenie zostanie wysłane. Dane fikcyjne."""
import pytest

from app.extensions import db
from app.models import (
    EVENT_STATUS_CHANGED,
    EVENT_TEST,
    WEBHOOK_PENDING,
    ApiKey,
    Document,
    WebhookDelivery,
)
from app.services.apikeys import hash_key
from app.services.dbutil import commit_with_retry
from app.services.negotiation import resolve, restore
from app.services.pipeline import ingest, process
from app.services.webhook_outbox import build_payload, document_url, emit_status_change, enqueue_test
from tests.conftest import sample_bytes
from tests.test_negotiation_statuses import inv

KEY = {"X-API-Key": "xp_test_demo_key"}
HOOK = "https://odbiorca.example/webhook"
PAYLOAD_KEYS = {"event", "id", "status", "previous_status", "updated_at", "document_url"}
OTHER_TAX = "1110000222"


def demo_key() -> ApiKey:
    return ApiKey.query.filter_by(key_hash=hash_key("xp_test_demo_key")).one()


@pytest.fixture
def hooked(seeded):
    """Klucz demo z adresem webhooka."""
    key = demo_key()
    key.webhook_url, key.webhook_secret = HOOK, "sekret-testowy"
    db.session.commit()
    return key


def deliveries(**filters):
    return WebhookDelivery.query.filter_by(**filters).order_by(WebhookDelivery.id).all()


def api_ingest(client, name="alfa-1.xml"):
    r = client.post("/api/v1/documents", headers=KEY, data=sample_bytes(name))
    assert r.status_code in (200, 201), r.get_json()
    return r.get_json()


def test_ingest_by_api_key_with_webhook_creates_one_delivery(hooked, client):
    doc = api_ingest(client)
    rows = deliveries()
    assert len(rows) == 1
    d = rows[0]
    assert d.event == EVENT_STATUS_CHANGED and d.status == WEBHOOK_PENDING and d.attempts == 0
    assert d.api_key_id == hooked.id and d.document_id == doc["id"] and len(d.uuid) == 36
    assert set(d.payload) == PAYLOAD_KEYS
    assert d.payload["event"] == EVENT_STATUS_CHANGED
    assert d.payload["id"] == doc["id"]
    assert d.payload["status"] == doc["status"] and doc["status"] != "received"
    assert d.payload["previous_status"] == "received"
    assert d.payload["document_url"] == f"http://localhost/dokumenty/{doc['id']}"


def test_no_delivery_without_webhook_url(seeded, client):
    key = demo_key()
    key.webhook_url = ""
    db.session.commit()
    api_ingest(client)
    assert deliveries() == []
    key.webhook_url = None
    db.session.commit()
    api_ingest(client, "beta-ksef.xml")
    assert deliveries() == []


def test_no_delivery_for_panel_document_without_api_key(hooked, auth_client):
    doc = ingest(sample_bytes("alfa-1.xml"), "alfa-1.xml")
    assert doc.api_key_id is None and doc.status != "received"
    r = auth_client.post(f"/dokumenty/{doc.id}/rozwiaz", data={"action": "reject"})
    assert r.status_code == 302
    assert db.session.get(Document, doc.id).status == "rejected"
    assert deliveries() == []


def test_no_delivery_when_status_unchanged(hooked, client):
    doc = api_ingest(client)
    r = client.post(f"/api/v1/documents/{doc['id']}/reprocess", headers=KEY)
    assert r.status_code == 200 and r.get_json()["status"] == doc["status"]
    assert len(deliveries()) == 1


def test_reject_in_panel_emits_rejected(hooked, client, auth_client):
    doc = api_ingest(client)
    r = auth_client.post(f"/dokumenty/{doc['id']}/rozwiaz", data={"action": "reject"})
    assert r.status_code == 302
    rows = deliveries(document_id=doc["id"])
    assert len(rows) == 2
    assert rows[1].payload["status"] == "rejected"
    assert rows[1].payload["previous_status"] == doc["status"]


def test_restore_emits_with_previous_rejected(hooked, client, auth_client):
    doc = api_ingest(client)
    auth_client.post(f"/dokumenty/{doc['id']}/rozwiaz", data={"action": "reject"})
    r = auth_client.post(f"/dokumenty/{doc['id']}/przywroc")
    assert r.status_code == 302
    rows = deliveries(document_id=doc["id"])
    assert len(rows) == 3
    assert rows[2].payload["previous_status"] == "rejected"
    assert rows[2].payload["status"] == doc["status"]


def test_duplicate_cascade_emits_for_demoted_document(hooked):
    """Oryginał (niższe id) przetworzony po zatwierdzeniu późniejszej kopii degraduje ją do duplikatu —
    każdy zmieniony dokument z kluczem webhooka dostaje własne zdarzenie."""
    a = ingest(inv("KAS/1", tax=OTHER_TAX), "a.json", source="api", api_key_id=hooked.id)
    b = ingest(inv("KAS/1", tax=OTHER_TAX) + b"\n", "b.json", source="api", api_key_id=hooked.id)
    assert a.status == b.status == "needs_review"
    resolve(b, "create_supplier", {"name": "Kaskada sp. z o.o.", "tax_id": OTHER_TAX}, True, "qa")
    assert b.status == "approved"
    before = len(deliveries())
    process(a)
    db.session.commit()
    assert db.session.get(Document, b.id).status == "duplicate"
    new = deliveries()[before:]
    assert len(new) == 2  # po jednym zdarzeniu na zmieniony dokument, bez podwójnej emisji
    by_doc = {d.document_id: d.payload for d in new}
    assert set(by_doc) == {a.id, b.id}
    assert (by_doc[b.id]["previous_status"], by_doc[b.id]["status"]) == ("approved", "duplicate")
    assert by_doc[a.id]["status"] == "approved"


def test_outbox_row_disappears_with_rollback(hooked, client, app):
    doc = db.session.get(Document, api_ingest(client)["id"])
    app.config["MAX_LINES"] = 0
    process(doc)
    assert doc.status == "rejected"
    assert len(deliveries()) == 2  # autoflush: wiersz jest w tej samej sesji
    db.session.rollback()
    assert len(deliveries()) == 1
    assert db.session.get(Document, doc.id).status != "rejected"


def test_commit_with_retry_leaves_single_delivery(hooked, client, app):
    doc = db.session.get(Document, api_ingest(client)["id"])
    app.config["MAX_LINES"] = 0
    attempts = []

    def apply():
        attempts.append(1)
        process(doc)
        if len(attempts) == 1:  # wyścig o unikalny klucz → IntegrityError → rollback i ponowienie
            db.session.add(ApiKey(name="kolizja", prefix="xp_test_de", key_hash=hash_key("xp_test_demo_key")))
    commit_with_retry(apply)
    assert len(attempts) == 2
    rejected = deliveries(document_id=doc.id)[1:]
    assert len(rejected) == 1 and rejected[0].payload["status"] == "rejected"


def test_outbox_failure_does_not_corrupt_processing_result(hooked, client, app, monkeypatch):
    """Błąd outboxu nie jest błędem przetwarzania: wyjątek idzie do wywołującego (rollback), a wynik dokumentu
    nie zamienia się w needs_review/internal_error."""
    from app.services import webhook_outbox

    doc = db.session.get(Document, api_ingest(client)["id"])
    app.config["MAX_LINES"] = 0

    def broken(*_args, **_kwargs):
        raise RuntimeError("outbox niedostępny")
    monkeypatch.setattr(webhook_outbox, "build_payload", broken)
    with pytest.raises(RuntimeError, match="outbox niedostępny"):
        process(doc)
    assert doc.status == "rejected"
    assert "internal_error" not in [i["code"] for i in doc.issues]
    db.session.rollback()
    assert len(deliveries()) == 1


def test_document_url_falls_back_to_request_host_then_null(app):
    app.config["PUBLIC_BASE_URL"] = "https://faktury.example/"
    assert document_url(7) == "https://faktury.example/dokumenty/7"
    with app.test_request_context(base_url="https://panel.example:8443/"):
        assert document_url(7) == "https://faktury.example/dokumenty/7"
    app.config["PUBLIC_BASE_URL"] = ""
    with app.test_request_context(base_url="https://panel.example:8443/"):
        assert document_url(7) == "https://panel.example:8443/dokumenty/7"
    assert document_url(7) is None  # bez żądania (worker, CLI) i bez PUBLIC_BASE_URL


def test_inactive_key_does_not_enqueue(hooked, client):
    doc = db.session.get(Document, api_ingest(client)["id"])
    hooked.active = False
    db.session.commit()
    assert emit_status_change(doc, "received") is None
    db.session.commit()
    assert len(deliveries()) == 1


def test_payload_updated_at_matches_api_format(hooked, client, app):
    doc = api_ingest(client)
    payload = deliveries()[0].payload
    assert payload["updated_at"] == doc["updated_at"] and payload["updated_at"].endswith("Z")
    with app.test_request_context():  # ten sam host co klient testowy (http://localhost/)
        assert build_payload(db.session.get(Document, doc["id"]), "received") == payload
    test = enqueue_test(hooked)
    db.session.commit()
    assert test.event == EVENT_TEST and test.document_id is None and test.api_key_id == hooked.id
    assert test.payload == {"event": EVENT_TEST, "id": None, "status": None, "previous_status": None,
                            "updated_at": None, "document_url": None}
