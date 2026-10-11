import io
import re
from datetime import datetime

import pytest

from app.api.timeutil import format_api_datetime
from app.extensions import db
from app.models import Document, utcnow
from app.services import pipeline
from app.services.negotiation import resolve, restore
from tests.conftest import sample_bytes
from tests.test_learning import resolve_with_top_suggestions

KEY = {"X-API-Key": "xp_test_demo_key"}


def test_requires_key(seeded, client):
    r = client.get("/api/v1/documents")
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "unauthorized"
    assert client.get("/api/v1/documents", headers={"X-API-Key": "zly"}).status_code == 401


def test_upload_multipart_and_get(seeded, client):
    r = client.post("/api/v1/documents", headers=KEY,
                    data={"file": (io.BytesIO(sample_bytes("epsilon.json")), "epsilon.json")},
                    content_type="multipart/form-data")
    assert r.status_code == 201
    body = r.get_json()
    assert body["status"] == "needs_review" and body["format"] == "json"
    assert body["invoice"]["number"] == "E-2026-0042"
    assert body["issues"][0]["code"] == "unknown_supplier"
    r2 = client.get(f"/api/v1/documents/{body['id']}", headers=KEY)
    assert r2.status_code == 200 and r2.get_json()["id"] == body["id"]


def test_upload_raw_body(seeded, client):
    r = client.post("/api/v1/documents", headers={**KEY, "X-Filename": "delta.csv", "Content-Type": "text/csv"},
                    data=sample_bytes("delta.csv"))
    assert r.status_code == 201 and r.get_json()["format"] == "csv"


def test_api_empty_body_400(seeded, client):
    r = client.post("/api/v1/documents", headers=KEY, data=b"")
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "empty_body"


def test_unreadable_returns_201_rejected(seeded, client):
    r = client.post("/api/v1/documents", headers=KEY, data=b"<a><b></a>")
    assert r.status_code == 201 and r.get_json()["status"] == "rejected"


def test_too_large(seeded, app, client):
    app.config["MAX_DOCUMENT_BYTES"] = 10
    r = client.post("/api/v1/documents", headers=KEY, data=b"<a>" + b"x" * 50 + b"</a>")
    assert r.status_code == 413 and r.get_json()["error"]["code"] == "too_large"


def test_list_filter_and_reprocess(seeded, client):
    client.post("/api/v1/documents", headers=KEY, data=sample_bytes("alfa-1.xml"))
    r = client.get("/api/v1/documents?status=needs_review", headers=KEY)
    items = r.get_json()["items"]
    assert len(items) == 1 and "invoice" not in items[0]
    r = client.post(f"/api/v1/documents/{items[0]['id']}/reprocess", headers=KEY)
    assert r.status_code == 200 and r.get_json()["status"] == "needs_review"
    assert client.get("/api/v1/documents?status=zly", headers=KEY).status_code == 400
    assert client.get("/api/v1/documents/9999", headers=KEY).status_code == 404


def test_suppliers_and_docs_page(seeded, client):
    assert client.get("/api/v1/suppliers", headers=KEY).get_json() == {"items": []}
    assert client.get("/api/docs").status_code == 200
    assert client.get("/static/openapi.yaml").status_code == 200


def test_too_large_http_limit_json(seeded, app, client):
    app.config["MAX_CONTENT_LENGTH"] = 100
    r = client.post("/api/v1/documents", headers=KEY, data=b"<a>" + b"x" * 500 + b"</a>")
    assert r.status_code == 413 and r.get_json()["error"]["code"] == "too_large"


def test_bad_limit_400(seeded, client):
    assert client.get("/api/v1/documents?limit=abc", headers=KEY).status_code == 400


def test_list_without_sync_parameters_keeps_old_shape_newest_first(seeded, client):
    """Bez `updated_since` i `cursor` lista działa jak dotąd: tylko `items` (bez `next_cursor`), od najnowszych."""
    ids = [_post(client, data)["id"] for data in (sample_bytes("alfa-1.xml"), b"<a><b></a>", b"<x/>")]
    body = client.get("/api/v1/documents", headers=KEY).get_json()
    assert set(body) == {"items"}
    assert [i["id"] for i in body["items"]] == sorted(ids, reverse=True)


def _second_key(app):
    from app.extensions import db
    from app.services.apikeys import create_key
    create_key("B", "xp_other_key_b")
    db.session.commit()
    return {"X-API-Key": "xp_other_key_b"}


def test_keys_are_isolated(seeded, app, client):
    b = _second_key(app)
    doc = client.post("/api/v1/documents", headers=KEY, data=sample_bytes("alfa-1.xml")).get_json()
    assert client.get(f"/api/v1/documents/{doc['id']}", headers=b).status_code == 404
    r = client.post(f"/api/v1/documents/{doc['id']}/reprocess", headers=b)
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"
    assert client.get("/api/v1/documents", headers=b).get_json() == {"items": []}
    assert len(client.get("/api/v1/documents", headers=KEY).get_json()["items"]) == 1


def test_panel_document_invisible_to_api(seeded, app, client):
    from app.services.pipeline import ingest
    with app.app_context():
        doc = ingest(sample_bytes("alfa-1.xml"), "a.xml", source="upload")
        doc_id = doc.id
    assert client.get(f"/api/v1/documents/{doc_id}", headers=KEY).status_code == 404
    assert client.get("/api/v1/documents", headers=KEY).get_json() == {"items": []}


def test_json_404_405(seeded, client):
    r = client.get("/api/v1/nic", headers=KEY)
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"
    r = client.delete("/api/v1/suppliers", headers=KEY)
    assert r.status_code == 405 and r.get_json()["error"]["code"] == "method_not_allowed"


# --- updated_at: format, wiarygodność (touch) i brak zmian przy samym odczycie -------------------------------

ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def _post(client, data=None) -> dict:
    r = client.post("/api/v1/documents", headers=KEY, data=sample_bytes("alfa-1.xml") if data is None else data)
    assert r.status_code == 201
    return r.get_json()


def _get(client, doc_id) -> dict:
    r = client.get(f"/api/v1/documents/{doc_id}", headers=KEY)
    assert r.status_code == 200
    return r.get_json()


def _reprocess(client, doc_id) -> dict:
    r = client.post(f"/api/v1/documents/{doc_id}/reprocess", headers=KEY)
    assert r.status_code == 200
    return r.get_json()


def _set_updated_at(doc_id, value: datetime) -> None:
    db.session.get(Document, doc_id).updated_at = value
    db.session.commit()


def test_created_and_updated_at_are_iso_utc_with_microseconds(seeded, client):
    body = _post(client)
    assert ISO_UTC.match(body["created_at"]) and ISO_UTC.match(body["updated_at"])
    assert body["updated_at"] >= body["created_at"]  # format jest leksykograficznie uporządkowany
    items = client.get("/api/v1/documents", headers=KEY).get_json()["items"]
    assert [i["id"] for i in items] == [body["id"]] and "invoice" not in items[0]  # lista skrócona, czasy są
    assert ISO_UTC.match(items[0]["created_at"]) and ISO_UTC.match(items[0]["updated_at"])


def test_updated_at_grows_and_created_at_stays_after_operator_resolves_issues(seeded, client):
    created = _post(client)
    assert created["status"] == "needs_review"
    resolve_with_top_suggestions(db.session.get(Document, created["id"]))  # operator w panelu → approved
    after = _get(client, created["id"])
    assert after["status"] == "approved"
    assert after["created_at"] == created["created_at"]
    assert after["updated_at"] > created["updated_at"]


def test_updated_at_grows_on_reject_and_on_restore(seeded, client):
    created = _post(client)
    doc = db.session.get(Document, created["id"])
    resolve(doc, "reject", {}, user="qa")
    rejected = _get(client, created["id"])
    assert rejected["status"] == "rejected" and rejected["updated_at"] > created["updated_at"]
    restore(doc, "qa")
    restored = _get(client, created["id"])
    assert restored["status"] == "needs_review" and restored["updated_at"] > rejected["updated_at"]
    assert restored["created_at"] == created["created_at"]


def test_reject_and_restore_stamp_updated_at_with_touch(seeded, client, monkeypatch):
    """Przy zmianie kolumn `onupdate` też dałoby „teraz”, więc sam wzrost nie dowodzi jawnego `touch()`. Z podstawionym
    zegarem widać źródło wartości: ustawiona jawnie wygrywa z `onupdate` (odrzucenie nie przechodzi przez process())."""
    created = _post(client)
    doc = db.session.get(Document, created["id"])
    clock = {"now": datetime(2031, 1, 1, 12, 0, 0, 111111)}
    monkeypatch.setattr(pipeline, "utcnow", lambda: clock["now"])
    resolve(doc, "reject", {}, user="qa")
    assert _get(client, created["id"])["updated_at"] == "2031-01-01T12:00:00.111111Z"
    clock["now"] = datetime(2031, 1, 2, 12, 0, 0, 222222)
    restore(doc, "qa")
    assert _get(client, created["id"])["updated_at"] == "2031-01-02T12:00:00.222222Z"


def test_reprocess_refreshes_updated_at(seeded, client):
    created = _post(client)
    again = _reprocess(client, created["id"])
    assert again["status"] == created["status"] and again["created_at"] == created["created_at"]
    assert again["updated_at"] > created["updated_at"]


@pytest.mark.parametrize("payload, status", [
    pytest.param(sample_bytes("alfa-1.xml"), "needs_review", id="ten-sam-wynik"),
    pytest.param(b"<a><b></a>", "rejected", id="plik-nieczytelny-wczesny-return"),
])
def test_reprocess_refreshes_updated_at_even_when_no_column_changes(seeded, client, payload, status):
    """`onupdate` odpala się tylko przy zmianie kolumny, a ponowne przetworzenie tego samego pliku nie zmienia
    żadnej — więc `updated_at` musi być odświeżane jawnie (`touch`), inaczej zostałoby 2020-01-01."""
    created = _post(client, payload)
    assert created["status"] == status
    _set_updated_at(created["id"], datetime(2020, 1, 1))
    before = format_api_datetime(utcnow())
    again = _reprocess(client, created["id"])
    assert again["status"] == status
    assert again["updated_at"] >= before, again["updated_at"]  # „teraz”, nie 2020-01-01T00:00:00.000000Z


def test_internal_error_branch_refreshes_updated_at(seeded, client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("zepsuta reguła")
    # błąd na samym początku _process: nic nie jest po drodze zapisywane (autoflush), więc przy powtórzeniu tego
    # samego błędu status, error i issues zostają bez zmian i `updated_at` odświeża wyłącznie jawny touch
    monkeypatch.setattr(pipeline, "load_tree", boom)
    created = _post(client)
    assert created["issues"][0]["code"] == "internal_error"
    _set_updated_at(created["id"], datetime(2020, 1, 1))
    before = format_api_datetime(utcnow())
    again = _reprocess(client, created["id"])
    assert again["issues"][0]["code"] == "internal_error"
    assert again["updated_at"] >= before, again["updated_at"]


def test_process_of_manually_rejected_document_does_not_touch(seeded, client):
    """Straż ręcznego odrzucenia: `process()` niczego nie zmienia, więc nie odświeża też `updated_at`."""
    created = _post(client)
    doc = db.session.get(Document, created["id"])
    resolve(doc, "reject", {}, user="qa")
    rejected = _get(client, created["id"])
    pipeline.process(doc)
    db.session.commit()
    assert _get(client, created["id"])["updated_at"] == rejected["updated_at"]


def test_reading_does_not_change_updated_at(seeded, client):
    created = _post(client)
    first, second = _get(client, created["id"]), _get(client, created["id"])
    assert first["updated_at"] == second["updated_at"] == created["updated_at"]
    listed = [client.get("/api/v1/documents", headers=KEY).get_json()["items"][0]["updated_at"] for _ in range(2)]
    assert listed == [created["updated_at"]] * 2
