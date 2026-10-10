from app.extensions import db
from app.models import Supplier
from app.services.pipeline import ingest, load_tree
from app.services.templates import create_template
from tests.conftest import sample_bytes


def issue(doc, code):
    return next(i for i in doc.issues if i["code"] == code)


def test_alfa_first_time_needs_review(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "alfa-1.xml")
    assert d.status == "needs_review" and d.fmt == "xml"
    codes = [i["code"] for i in d.issues]
    assert codes[0] == "unknown_supplier"
    assert {"unmapped_field", "unknown_unit", "unmapped_product"} <= set(codes)
    sup = issue(d, "unknown_supplier")["suggestions"][0]
    assert sup == {"kind": "create_supplier", "name": "Hurtownia Alfa Sp. z o.o.", "tax_id": "PL9990000011",
                   "confidence": 0.9, "reason": "dane odczytane z faktury"}
    assert issue(d, "unknown_unit")["suggestions"][0]["unit"] == "szt"
    prod = issue(d, "unmapped_product")
    assert prod["line_no"] == 3 and prod["suggestions"][0]["code"] == "TOW-0003"
    cur = issue(d, "unmapped_field")
    assert cur["field"] == "currency"
    assert {"kind": "default", "value": "PLN", "confidence": 0.5, "reason": "typowa wartość"} in cur["suggestions"]
    assert d.result["lines"][0]["product_index"] == "TOW-0001"
    assert d.draft_rules["line_path"] == "Document/Faktura/Pozycje/Pozycja"


def test_unreadable_file_rejected(seeded):
    d = ingest(b"<a><b></a>", "zly.xml")
    assert d.status == "rejected"
    assert d.issues[0]["code"] == "unreadable" and "XML" in d.issues[0]["message"]


def test_duplicate_same_file(seeded):
    ingest(sample_bytes("alfa-1.xml"), "a.xml")
    d2 = ingest(sample_bytes("alfa-1.xml"), "a-kopia.xml")
    assert d2.status == "duplicate" and d2.issues[0]["code"] == "duplicate"


def test_duplicate_same_supplier_number(seeded):
    db.session.add(Supplier(name="Hurtownia Alfa", tax_id="PL9990000011"))
    db.session.commit()
    d1 = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    assert d1.supplier_id is not None
    d2 = ingest(sample_bytes("alfa-1.xml") + b"\n<!-- inna kopia -->\n", "b.xml")
    assert d2.status == "duplicate"


def test_same_format_new_supplier_not_misattributed(seeded):
    s = Supplier(name="Hurtownia Alfa", tax_id="PL9990000011")
    db.session.add(s)
    db.session.flush()
    d1 = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    tree = load_tree(d1)
    tpl = create_template(s, tree.leaf_paths(), tree.fingerprint(), "xml", d1.draft_rules, "admin")
    db.session.commit()
    omega = (sample_bytes("alfa-2.xml")
             .replace(b"PL9990000011", b"PL9990000088")
             .replace(b"Hurtownia Alfa Sp. z o.o.", b"Hurtownia Omega"))
    d2 = ingest(omega, "omega.xml")
    assert d2.supplier_id is None
    assert d2.issues[0]["code"] == "unknown_supplier"
    kinds = {x["kind"]: x for x in d2.issues[0]["suggestions"]}
    assert kinds["create_supplier"]["name"] == "Hurtownia Omega"
    assert kinds["clone_template"]["template_id"] == tpl.id
    assert d2.draft_rules == tpl.active_version.rules


def test_known_supplier_template_is_used(seeded):
    s = Supplier(name="Hurtownia Alfa", tax_id="9990000011")
    db.session.add(s)
    db.session.flush()
    d1 = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    tree = load_tree(d1)
    rules = {**d1.draft_rules, "defaults": {"currency": "GBP"}}
    tpl = create_template(s, tree.leaf_paths(), tree.fingerprint(), "xml", rules, "admin")
    db.session.commit()
    d2 = ingest(sample_bytes("alfa-2.xml"), "b.xml")
    assert d2.template_id == tpl.id and d2.template_version_id == tpl.active_version_id
    assert d2.result["currency"] == "GBP"
    assert [i["code"] for i in d2.issues] == ["unknown_unit"]


def test_oversize_document_rejected(seeded):
    import pytest
    from app.services.pipeline import DocumentTooLarge
    seeded.config["MAX_DOCUMENT_BYTES"] = 100
    with pytest.raises(DocumentTooLarge):
        ingest(b"x" * 101, "duzy.xml")
