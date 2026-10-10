from pathlib import Path

import pytest

from app.ingest import ReaderError, read_document

SAMPLES = Path(__file__).resolve().parent.parent / "demo" / "samples"


def test_xml_alfa():
    t = read_document((SAMPLES / "alfa-1.xml").read_bytes(), "alfa-1.xml")
    assert t.fmt == "xml"
    assert t.first("Document/Faktura/Naglowek/FakturaNumer") == "FA/2026/10/001"
    assert t.detect_line_group() == "Document/Faktura/Pozycje/Pozycja"


def test_xml_namespaces_stripped_and_attrs():
    t = read_document((SAMPLES / "gamma-ubl.xml").read_bytes())
    assert t.first("Invoice/ID") == "GAM-2026-0315"
    assert t.detect_line_group() == "Invoice/InvoiceLine"
    line = t.nodes_at("Invoice/InvoiceLine")[0]
    assert t.first("InvoicedQuantity/@unitCode", context=line) == "C62"


def test_xml_rejects_doctype():
    evil = b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x "y">]><a>&x;</a>'
    with pytest.raises(ReaderError, match="DOCTYPE"):
        read_document(evil)


def test_xml_malformed():
    with pytest.raises(ReaderError):
        read_document(b"<a><b></a>")


def test_json_epsilon_keeps_number_strings():
    t = read_document((SAMPLES / "epsilon.json").read_bytes(), "epsilon.json")
    assert t.fmt == "json"
    assert t.first("root/invoice/totals/net") == "45.60"
    assert t.detect_line_group() == "root/invoice/items"
    assert t.values("root/invoice/items/quantity") == ["6", "5"]


def test_csv_delta():
    t = read_document((SAMPLES / "delta.csv").read_bytes(), "delta.csv")
    assert t.fmt == "csv"
    assert t.detect_line_group() == "csv/row"
    assert t.values("csv/row/JM") == ["kart.", "kart."]
    assert t.first("csv/row/NrFaktury") == "D/77/2026"


def test_csv_cp1250_fallback():
    data = "Nr;Nazwa\n1;Mąka\n".encode("cp1250")
    t = read_document(data, "x.csv")
    assert t.first("csv/row/Nazwa") == "Mąka"


@pytest.mark.parametrize("data", [b"", b"   ", b"Nr;Nazwa\n"])
def test_empty_inputs_rejected(data):
    with pytest.raises(ReaderError):
        read_document(data, "x.csv")


def test_xml_rejects_late_doctype():
    evil = b'<?xml version="1.0"?><!-- ' + b"x" * 5000 + b' --><!DOCTYPE a><a>1</a>'
    with pytest.raises(ReaderError, match="DOCTYPE"):
        read_document(evil)


def test_xml_rejects_utf16_without_bom():
    evil = '<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x "y">]><a>&x;</a>'.encode("utf-16-le")
    with pytest.raises(ReaderError):
        read_document(evil)


def test_xml_rejects_utf16_with_bom():
    with pytest.raises(ReaderError):
        read_document("<a>1</a>".encode("utf-16"))


def test_json_deep_nesting_rejected():
    with pytest.raises(ReaderError):
        read_document(b"[" * 5000 + b"]" * 5000)


def test_json_deep_nesting_objects_rejected():
    with pytest.raises(ReaderError):
        read_document(b'{"a":' * 3000 + b"1" + b"}" * 3000)


def test_csv_oversized_field_rejected():
    data = b"A;B\n" + b"x" * 200000 + b";1\n"
    with pytest.raises(ReaderError):
        read_document(data, "x.csv")
