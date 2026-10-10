"""Poprawki z końcowego przeglądu v0.1.0."""
import io

import pytest

from app.extensions import db
from app.ingest import ReaderError, read_document
from app.models import Document, Supplier, Template
from app.services.negotiation import resolve
from app.services.pipeline import ingest
from tests.conftest import sample_bytes
from tests.test_learning import resolve_with_top_suggestions

KEY = {"X-API-Key": "xp_test_demo_key"}


# --- I2: szablon dla znanego dostawcy bez szablonu ---------------------------------------------
def test_known_supplier_without_template_learns_template(seeded):
    db.session.add(Supplier(name="Hurtownia Alfa", tax_id="PL9990000011"))
    db.session.commit()
    d1 = ingest(sample_bytes("alfa-1.xml"), "alfa-1.xml")
    assert d1.supplier_id and d1.template_id is None
    resolve_with_top_suggestions(d1)
    assert d1.status == "approved" and d1.template_id
    d2 = ingest(sample_bytes("alfa-2.xml"), "alfa-2.xml")
    assert d2.status == "approved", d2.issues
    assert d2.template_id == d1.template_id
    assert Template.query.count() == 1


def test_editor_save_creates_template_for_known_supplier(auth_client):
    db.session.add(Supplier(name="Hurtownia Alfa", tax_id="PL9990000011"))
    db.session.commit()
    d = ingest(sample_bytes("alfa-1.xml"), "alfa-1.xml")
    assert d.template_id is None and d.draft_rules
    r = auth_client.post(f"/szablony/dokument/{d.id}/zapisz", json={"rules": d.draft_rules, "comment": "x"})
    assert r.status_code == 200, r.get_data(as_text=True)
    db.session.refresh(d)
    assert d.template_id and d.draft_rules is None and Template.query.count() == 1


def test_draft_label_text(auth_client):
    d = ingest(sample_bytes("alfa-1.xml"), "alfa-1.xml")
    html = auth_client.get(f"/dokumenty/{d.id}").get_data(as_text=True)
    assert "szablon powstanie po rozpoznaniu dostawcy i zapisie mapowania" in html


# --- I3: pliki binarne ---------------------------------------------------------------------------
@pytest.mark.parametrize("data", [
    b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj", b"PK\x03\x04\x14\x00\x00\x00", b"\x89PNG\r\n\x1a\n",
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"abc\x01\x02\x03\x04\x05\x06\x07\x08" * 50,
])
def test_binary_rejected_by_reader(data):
    with pytest.raises(ReaderError, match="binarny"):
        read_document(data)


def test_utf16_without_bom_gets_encoding_message():
    with pytest.raises(ReaderError, match="UTF-16"):
        read_document("<a><b>tekst</b></a>".encode("utf-16-le"))


def test_pdf_and_zip_rejected_via_pipeline(seeded):
    for data in (b"%PDF-1.4 tekst bez zer\n" + b"abc " * 50, b"PK\x03\x04" + b"abc " * 50):
        d = ingest(data, "x.bin")
        assert d.status == "rejected" and d.issues[0]["code"] == "unreadable"


def test_polish_cp1250_csv_still_readable():
    csv = "numer;nazwa\nFV/1;Żółć gęślą\n".encode("cp1250")
    assert read_document(csv).fmt == "csv"


# --- I4: skrajne wartości ------------------------------------------------------------------------
def test_huge_number_gives_invalid_value_not_500(seeded, client):
    data = sample_bytes("epsilon.json").replace(b'"net": 45.60', b'"net": 123456789012345678901234567890')
    r = client.post("/api/v1/documents", headers=KEY, data=data)
    assert r.status_code == 201, r.get_data(as_text=True)
    assert r.get_json()["status"] == "needs_review"


def test_huge_line_values_do_not_crash(seeded, client):
    data = sample_bytes("epsilon.json").replace(b"5.10", b"999999999999999999").replace(b"30.60", b"1")
    assert client.post("/api/v1/documents", headers=KEY, data=data).status_code == 201


def test_long_values_truncated(seeded):
    data = sample_bytes("epsilon.json").replace(b"E-2026-0042", b"N" * 300)
    d = ingest(data, "f" * 400 + ".json")
    assert d.number == "N" * 128 and len(d.filename) == 255
    assert db.session.get(Document, d.id).number == "N" * 128


def test_resolve_rolls_back_on_unexpected_error(seeded, monkeypatch):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")

    def boom(doc):
        raise RuntimeError("x")
    monkeypatch.setattr("app.services.negotiation.process", boom)
    with pytest.raises(RuntimeError):
        resolve(d, "allow_duplicate", {}, False, "t")
    assert not db.session.new and not db.session.dirty


# --- reprocess odrzuconego -----------------------------------------------------------------------
def test_reprocess_keeps_manual_rejection(auth_client):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    resolve(d, "reject", {}, False, "t")
    assert d.status == "rejected"
    r = auth_client.post(f"/dokumenty/{d.id}/ponownie", follow_redirects=True)
    assert "nie cofa odrzucenia" in r.get_data(as_text=True)
    db.session.refresh(d)
    assert d.status == "rejected"


def test_reprocess_unreadable_allowed(auth_client):
    d = ingest(b"<a><b></a>", "bad.xml")
    assert d.status == "rejected"
    auth_client.post(f"/dokumenty/{d.id}/ponownie")
    db.session.refresh(d)
    assert d.status == "rejected" and d.issues[0]["code"] == "unreadable"
