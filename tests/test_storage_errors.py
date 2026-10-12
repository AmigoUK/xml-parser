"""Magazyn plików: brak pliku źródłowego (utracony wolumen) i błąd zapisu (pełny dysk) dają czytelny komunikat,
nigdy 500 — w negocjacji, przy pobieraniu pliku i przy przyjmowaniu dokumentu (API i panel)."""
import io

import pytest

from app.extensions import db
from app.models import Document, Supplier
from app.services.negotiation import NegotiationError, resolve
from app.services.pipeline import FILE_MISSING_MSG, StorageUnavailable, ingest
from app.services.storage import Storage, get_storage
from tests.conftest import sample_bytes

KEY = {"X-API-Key": "xp_test_demo_key"}


def _doc_without_file():
    doc = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    get_storage().delete(doc.sha256)
    return doc


def test_create_supplier_without_source_file_is_negotiation_error(seeded):
    doc = _doc_without_file()
    with pytest.raises(NegotiationError, match="Brak pliku źródłowego"):
        resolve(doc, "create_supplier", {"name": "Alfa", "tax_id": "PL9990000011"}, True, "admin")
    assert Supplier.query.count() == 0  # nic nie zapisano


def test_use_supplier_without_source_file_is_negotiation_error(seeded):
    s = Supplier(name="Beta", tax_id="PL5550000022")
    db.session.add(s)
    db.session.commit()
    doc = _doc_without_file()
    with pytest.raises(NegotiationError, match="Brak pliku źródłowego"):
        resolve(doc, "use_supplier", {"supplier_id": str(s.id)}, True, "admin")


def test_panel_resolve_without_source_file_flashes(auth_client):
    doc = _doc_without_file()
    r = auth_client.post(f"/dokumenty/{doc.id}/rozwiaz",
                         data={"action": "create_supplier", "name": "Alfa", "tax_id": "PL9990000011"},
                         follow_redirects=True)
    assert r.status_code == 200 and FILE_MISSING_MSG[:30] in r.get_data(as_text=True)


def test_raw_download_without_source_file_redirects_with_message(auth_client):
    doc = _doc_without_file()
    r = auth_client.get(f"/dokumenty/{doc.id}/plik")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/dokumenty/{doc.id}")
    assert FILE_MISSING_MSG[:30] in auth_client.get(f"/dokumenty/{doc.id}").get_data(as_text=True)


def _disk_full(self, data):
    raise OSError(28, "No space left on device")


def test_ingest_storage_error_is_storage_unavailable(seeded, monkeypatch):
    monkeypatch.setattr(Storage, "store", _disk_full)
    with pytest.raises(StorageUnavailable):
        ingest(sample_bytes("alfa-1.xml"), "a.xml")
    assert Document.query.count() == 0


def test_api_upload_storage_error_is_503(seeded, client, monkeypatch):
    monkeypatch.setattr(Storage, "store", _disk_full)
    r = client.post("/api/v1/documents", headers=KEY, data=sample_bytes("alfa-1.xml"))
    assert r.status_code == 503
    body = r.get_json()["error"]
    assert body["code"] == "storage_unavailable" and "Magazyn plików" in body["message"]


def test_panel_upload_storage_error_is_flashed(auth_client, monkeypatch):
    monkeypatch.setattr(Storage, "store", _disk_full)
    r = auth_client.post("/wgraj", data={"file": (io.BytesIO(sample_bytes("alfa-1.xml")), "a.xml")},
                         content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200 and "Magazyn plików" in r.get_data(as_text=True)
