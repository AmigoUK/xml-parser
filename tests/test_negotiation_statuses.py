"""Pakiet D: negocjacja i statusy (BE-2..5, BE-11, EDGE-3, 6..9, 15, 19, 24, 25). Dane fikcyjne."""
import json

import pytest

from app.extensions import db
from app.models import Document, Product, ProductMapping, Supplier, Unit, UnitConversion
from app.services.negotiation import NegotiationError, resolve
from app.services.pipeline import ingest, process
from tests.conftest import sample_bytes

KEY = {"X-API-Key": "xp_test_demo_key"}
TAX = "9990000555"


def line(sku="S1", ean="5909999000013", name="Posypka", qty="2", price="10.00", net="20.00"):
    out = {"description": name, "quantity": qty, "uom": "szt", "unit_price": price, "net_amount": net,
           "vat_rate": "23"}
    if sku:
        out["sku"] = sku
    if ean:
        out["ean"] = ean
    if name is None:
        del out["description"]
    return out


def inv(num, lines=None, tax=TAX, doc_type=None):
    lines = lines if lines is not None else [line()]
    net = sum(float(x["net_amount"]) for x in lines)
    body = {"invoice": {"number": num, "issue_date": "2026-10-01", "currency": "PLN",
                        "seller": {"name": "Testowy Dostawca", "vat_number": tax},
                        "totals": {"net": f"{net:.2f}", "vat": f"{net * 0.23:.2f}", "gross": f"{net * 1.23:.2f}"},
                        "items": lines}}
    if doc_type:
        body["invoice"]["doc_type"] = doc_type
    return json.dumps(body).encode()


def codes(doc):
    return [i["code"] for i in doc.issues]


@pytest.fixture
def supplier(seeded):
    """Dostawca z szablonem wyuczonym na fakturze JSON."""
    d = ingest(inv("T/1"), "t1.json")
    resolve(d, "create_supplier", {"name": "Testowy Dostawca", "tax_id": TAX}, True, "qa")
    return db.session.get(Supplier, d.supplier_id)


# ------------------------------------------------------------------ BE-3 / EDGE-3


def test_line_without_code_and_gtin_does_not_overwrite_foreign_mapping(supplier):
    d = ingest(inv("T/2", [line(sku="N2", ean=None, name="Nowy towar dwa")]), "t2.json")
    resolve(d, "map_product", {"product_code": "TOW-0003", "line_no": "1"}, True, "qa")
    assert ProductMapping.query.filter_by(supplier_code="N2").one().product.code == "TOW-0003"

    d3 = ingest(inv("T/3", [line(sku=None, ean=None, name="Towar  bez KODU")]), "t3.json")
    resolve(d3, "map_product", {"product_code": "TOW-0010", "line_no": "1"}, True, "qa")
    # cudze mapowanie nietknięte, nowe zapamiętane po nazwie
    assert ProductMapping.query.filter_by(supplier_code="N2").one().product.code == "TOW-0003"
    by_name = ProductMapping.query.filter_by(supplier_name_norm="towar bez kodu").one()
    assert by_name.product.code == "TOW-0010" and by_name.supplier_code is None
    assert "unmapped_product" not in codes(d3)
    assert d3.result["lines"][0]["product_index"] == "TOW-0010"

    # kolejna faktura z tą samą nazwą (inna wielkość liter/spacje) — towar rozpoznany automatycznie
    d4 = ingest(inv("T/4", [line(sku=None, ean=None, name=" towar bez kodu ")]), "t4.json")
    assert d4.result["lines"][0]["product_index"] == "TOW-0010"


def test_line_without_code_gtin_and_name_only_for_this_invoice(supplier):
    d = ingest(inv("T/5", [line(sku=None, ean=None, name=None)]), "t5.json")
    with pytest.raises(NegotiationError, match="tylko dla tej faktury"):
        resolve(d, "map_product", {"product_code": "TOW-0010", "line_no": "1"}, True, "qa")
    resolve(d, "map_product", {"product_code": "TOW-0010", "line_no": "1"}, False, "qa")
    assert d.result["lines"][0]["product_index"] == "TOW-0010"
    assert ProductMapping.query.count() == 0


def test_gtin_only_line_does_not_repoint_code_mapping(supplier):
    d = ingest(inv("T/6", [line(sku="K1", ean="5909999000099", name="Coś")]), "t6.json")
    # GTIN istnieje w kartotece (TOW-0009) — tworzymy jawne mapowanie kodu K1 → TOW-0001
    db.session.add(ProductMapping(supplier_id=supplier.id, supplier_code="K1", supplier_gtin="05909999000099",
                                  product_id=Product.query.filter_by(code="TOW-0001").one().id))
    db.session.commit()
    d = ingest(inv("T/7", [line(sku=None, ean="5909999000075", name="Bez kodu z GTIN")]), "t7.json")
    resolve(d, "map_product", {"product_code": "TOW-0002", "line_no": "1"}, True, "qa")
    assert ProductMapping.query.filter_by(supplier_code="K1").one().product.code == "TOW-0001"
    assert ProductMapping.query.filter_by(supplier_gtin="05909999000075").one().product.code == "TOW-0002"


def test_one_off_mapping_of_aggregated_issue_covers_all_its_lines(supplier):
    lines = [line(sku="X9", ean=None, name="Wiele razy", net="20.00") for _ in range(3)]
    d = ingest(inv("T/8", lines), "t8.json")
    unm = [i for i in d.issues if i["code"] == "unmapped_product"]
    assert len(unm) == 1 and unm[0]["count"] == 3
    resolve(d, "map_product", {"product_code": "TOW-0002", "line_no": "1"}, False, "qa")
    assert [ln["product_index"] for ln in d.result["lines"]] == ["TOW-0002"] * 3
    assert "unmapped_product" not in codes(d)


# ------------------------------------------------------------------ EDGE-25


@pytest.mark.parametrize("line_no", ["0", "-1", "2", "abc"])
def test_line_no_out_of_range_is_error(supplier, line_no):
    d = ingest(inv("T/9", [line(sku="Q1", ean=None, name="Jeden")]), "t9.json")
    with pytest.raises(NegotiationError, match="Brak pozycji"):
        resolve(d, "map_product", {"product_code": "TOW-0002", "line_no": line_no}, True, "qa")
    assert ProductMapping.query.count() == 0


def test_line_no_out_of_range_via_form_is_flashed(supplier, client):
    client.post("/login", data={"email": "admin@example.com", "password": "haslo123"})
    d = ingest(inv("T/10", [line(sku="Q2", ean=None, name="Jeden")]), "t10.json")
    r = client.post(f"/dokumenty/{d.id}/rozwiaz",
                    data={"action": "map_product", "product_code": "TOW-0002", "line_no": "0", "remember": "1"},
                    follow_redirects=True)
    assert "Brak pozycji nr 0" in r.get_data(as_text=True)
    assert ProductMapping.query.count() == 0


# ------------------------------------------------------------------ BE-2 / EDGE-6


def _rejected(supplier):
    d = ingest(inv("R/1", [line(sku="R1", ean=None, name="Odrzucany")]), "r1.json")
    resolve(d, "reject", {}, True, "qa")
    assert d.status == "rejected"
    return d


def test_api_reprocess_does_not_revive_rejected(supplier, client):
    d = _rejected(supplier)
    d.api_key_id = 1
    db.session.commit()
    r = client.post(f"/api/v1/documents/{d.id}/reprocess", headers=KEY)
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "rejected"
    assert db.session.get(Document, d.id).status == "rejected"


def test_resolve_on_rejected_document_is_refused(supplier):
    d = _rejected(supplier)
    with pytest.raises(NegotiationError, match="odrzucony"):
        resolve(d, "allow_duplicate", {}, True, "qa")
    assert db.session.get(Document, d.id).status == "rejected"


def test_web_reprocess_and_editor_save_keep_rejection(supplier, client):
    client.post("/login", data={"email": "admin@example.com", "password": "haslo123"})
    d = _rejected(supplier)
    client.post(f"/dokumenty/{d.id}/ponownie")
    assert db.session.get(Document, d.id).status == "rejected"
    rules = d.template.active_version.rules
    r = client.post(f"/szablony/dokument/{d.id}/zapisz", json={"rules": rules, "comment": "x"})
    assert r.status_code == 200 and r.get_json()["status"] == "rejected"
    assert db.session.get(Document, d.id).status == "rejected"


def test_restore_action_revives_rejected(supplier, client):
    client.post("/login", data={"email": "admin@example.com", "password": "haslo123"})
    d = _rejected(supplier)
    html = client.get(f"/dokumenty/{d.id}").get_data(as_text=True)
    assert f"/dokumenty/{d.id}/przywroc" in html
    r = client.post(f"/dokumenty/{d.id}/przywroc", follow_redirects=True)
    assert "Przywrócono" in r.get_data(as_text=True)
    d = db.session.get(Document, d.id)
    assert d.status != "rejected" and d.rejected_by is None
    client.post(f"/dokumenty/{d.id}/ponownie")
    assert db.session.get(Document, d.id).status != "rejected"


def test_restore_requires_post(supplier, client):
    client.post("/login", data={"email": "admin@example.com", "password": "haslo123"})
    d = _rejected(supplier)
    assert client.get(f"/dokumenty/{d.id}/przywroc").status_code == 405


def test_too_many_lines_rejection_is_automatic_and_reprocessable(supplier, client):
    client.application.config["MAX_LINES"] = 1
    r = client.post("/api/v1/documents", headers={**KEY, "X-Filename": "m.json"},
                    data=inv("M/1", [line(sku="M1", ean=None), line(sku="M2", ean=None)]))
    js = r.get_json()
    assert js["status"] == "rejected" and js["issues"][0]["code"] == "too_many_lines"
    client.application.config["MAX_LINES"] = 100
    r = client.post(f"/api/v1/documents/{js['id']}/reprocess", headers=KEY)
    assert r.status_code == 200 and r.get_json()["status"] != "rejected"


# ------------------------------------------------------------------ BE-5 / EDGE-24


def test_reprocess_original_after_allow_duplicate_keeps_original(supplier):
    a = ingest(inv("D/1"), "a.json")
    assert a.status == "approved"
    b = ingest(inv("D/1"), "b.json")
    assert b.status == "duplicate"
    resolve(b, "allow_duplicate", {}, True, "qa")
    assert b.status == "approved"
    process(a)
    db.session.commit()
    assert a.status == "approved" and "duplicate" not in codes(a)


def test_rejecting_original_releases_its_duplicates(supplier):
    a = ingest(inv("D/2", [line(sku="Z1", ean=None, name="Nieznany")]), "a.json")
    assert a.status == "needs_review"
    b = ingest(inv("D/2", [line(sku="Z1", ean=None, name="Nieznany")]), "b.json")
    assert b.status == "duplicate"
    resolve(a, "reject", {}, True, "qa")
    b = db.session.get(Document, b.id)
    assert b.status == "needs_review" and "duplicate" not in codes(b)


def test_restoring_original_makes_later_copy_duplicate_again(supplier, client):
    client.post("/login", data={"email": "admin@example.com", "password": "haslo123"})
    a = ingest(inv("D/3"), "a.json")
    b = ingest(inv("D/3"), "b.json")
    resolve(a, "reject", {}, True, "qa")
    assert db.session.get(Document, b.id).status == "approved"
    client.post(f"/dokumenty/{a.id}/przywroc")
    assert db.session.get(Document, a.id).status == "approved"
    b = db.session.get(Document, b.id)
    assert b.status == "duplicate"  # nigdy dwie zatwierdzone kopie tej samej faktury


# ------------------------------------------------------------------ BE-4 + niejednoznaczny przelicznik


def test_add_conversion_twice_updates_existing(supplier):
    d = ingest(inv("C/1"), "c.json")
    resolve(d, "add_conversion", {"from_unit": "karton", "to_unit": "szt", "factor": "10"}, True, "qa")
    resolve(d, "add_conversion", {"from_unit": "karton", "to_unit": "szt", "factor": "12"}, True, "qa")
    rows = UnitConversion.query.all()
    assert len(rows) == 1 and rows[0].factor == 12


def test_add_conversion_ambiguous_factor_is_error(supplier):
    d = ingest(inv("C/2"), "c.json")
    for raw in ("1,000", "1.000"):
        with pytest.raises(NegotiationError, match="[Nn]iejednoznaczn"):
            resolve(d, "add_conversion", {"from_unit": "karton", "to_unit": "szt", "factor": raw}, True, "qa")
    assert UnitConversion.query.count() == 0


def _crud_conv(client, factor, supplier_id=""):
    units = {u.code: u.id for u in Unit.query.all()}
    return client.post("/przeliczniki/nowy", data={"from_unit_id": units["karton"], "to_unit_id": units["szt"],
                                                   "factor": factor, "supplier_id": supplier_id},
                       follow_redirects=True)


def test_crud_conversion_ambiguous_factor_is_validation_error(auth_client):
    html = _crud_conv(auth_client, "1,000").get_data(as_text=True)
    assert "iejednoznaczn" in html
    assert UnitConversion.query.count() == 0
    _crud_conv(auth_client, "1,5")
    assert UnitConversion.query.one().factor == 1.5


def test_crud_conversion_duplicate_is_validation_error(auth_client):
    _crud_conv(auth_client, "10")
    html = _crud_conv(auth_client, "12").get_data(as_text=True)
    assert "już istnieje" in html
    assert UnitConversion.query.count() == 1


def test_conversion_duplicates_impossible_in_db(seeded):
    # dawniej: stare duplikaty → wygrywał najnowszy; od pakietu E duplikat klucza odrzuca baza (BE-17),
    # a migracja zostawia najnowszy wiersz
    from sqlalchemy.exc import IntegrityError

    from app.services.lookups_db import DbLookups
    units = {u.code: u.id for u in Unit.query.all()}
    db.session.add(UnitConversion(from_unit_id=units["karton"], to_unit_id=units["szt"], factor="12"))
    db.session.commit()
    db.session.add(UnitConversion(from_unit_id=units["karton"], to_unit_id=units["szt"], factor="10"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    assert DbLookups().conversion(None, None, "karton")[1] == 12


# ------------------------------------------------------------------ EDGE-7


def test_override_to_deleted_product_blocks(supplier, client):
    client.post("/login", data={"email": "admin@example.com", "password": "haslo123"})
    p = Product(code="TMP-1", name="Tymczasowy", unit_id=Unit.query.filter_by(code="szt").one().id)
    db.session.add(p)
    db.session.commit()
    d = ingest(inv("O/1", [line(sku="ZZ", ean=None, name="Inny")]), "o.json")
    resolve(d, "map_product", {"product_code": "TMP-1", "line_no": "1"}, False, "qa")
    assert d.status == "approved"
    # panel blokuje usunięcie towaru użytego w dokumencie (BE-14) — symulujemy usunięcie poza panelem
    client.post(f"/towary/{p.id}/usun")
    assert Product.query.filter_by(code="TMP-1").first() is not None
    db.session.delete(p)
    db.session.commit()
    assert Product.query.filter_by(code="TMP-1").first() is None
    d = db.session.get(Document, d.id)
    process(d)
    db.session.commit()
    assert d.status == "needs_review"
    issue = next(i for i in d.issues if i["code"] == "unmapped_product")
    assert issue["severity"] == "blocking" and "TMP-1" in issue["message"]
    assert d.result["lines"][0]["product_index"] is None


def test_override_to_deleted_unit_blocks(seeded):
    from app.engine.lookups import MemoryLookups
    from app.engine.template import apply_template
    from app.ingest import read_document
    tree = read_document(inv("O/2", [line(sku="ZZ", ean=None)]), "o.json")
    rules = {"line_path": "root/invoice/items",
             "lines": {"unit": {"path": "uom"}, "name": {"path": "description"}}}
    res = apply_template(tree, rules, MemoryLookups(units={"kg": True}), None, {"units": {"szt": "usunieta"}})
    assert any(i.code == "unknown_unit" for i in res.issues)


# ------------------------------------------------------------------ BE-11 / EDGE-9 / EDGE-8


def test_create_supplier_with_existing_tax_id_reuses_supplier(supplier):
    d = ingest(inv("S/1", tax="PL 999-000-05-55"), "s.json")
    # identyfikacja już działa — wymuszamy ścieżkę „utwórz” na nowym dokumencie bez dostawcy
    d.supplier_id = None
    db.session.commit()
    resolve(d, "create_supplier", {"name": "Kolejny", "tax_id": "PL 999-000-05.55"}, True, "qa")
    assert Supplier.query.count() == 1 and d.supplier_id == supplier.id


def test_create_supplier_stores_normalized_tax_id(seeded):
    d = ingest(inv("S/2", tax="pl 999-000-07.77"), "s.json")
    resolve(d, "create_supplier", {"name": "Nowy", "tax_id": "pl 999-000-07.77"}, True, "qa")
    assert Supplier.query.one().tax_id == "PL9990000777"


def test_crud_supplier_duplicate_tax_id_is_error(auth_client):
    auth_client.post("/dostawcy/nowy", data={"name": "A", "tax_id": "PL9990000888"})
    html = auth_client.post("/dostawcy/nowy", data={"name": "B", "tax_id": "999-000-08-88"},
                            follow_redirects=True).get_data(as_text=True)
    assert "już istnieje" in html
    assert Supplier.query.count() == 1
    auth_client.post("/dostawcy/nowy", data={"name": "C", "tax_id": "DE9990000888"})  # inny kraj → wolno
    assert Supplier.query.count() == 2
    s = Supplier.query.filter_by(name="A").one()
    r = auth_client.post(f"/dostawcy/{s.id}/edycja", data={"name": "A2", "tax_id": "PL 999 000 08 88"},
                         follow_redirects=True)
    assert "Zapisano" in r.get_data(as_text=True)  # edycja samego siebie nie jest duplikatem
    assert db.session.get(Supplier, s.id).tax_id == "PL9990000888"


def test_identify_is_deterministic_lowest_id(seeded):
    s1 = Supplier(name="Pierwszy", tax_id="PL9990000999")
    s2 = Supplier(name="Drugi", tax_id="9990000999")
    db.session.add_all([s2, s1])  # kolejność wstawienia ≠ kolejność alfabetyczna
    db.session.commit()
    first = min(s1.id, s2.id)
    for n in range(3):
        d = ingest(inv(f"I/{n}", tax="9990000999"), f"i{n}.json")
        assert d.supplier_id == first


@pytest.mark.parametrize("a,b,same", [
    ("FR123456789", "DE123456789", False),
    ("PL9990000555", "9990000555", True),
    ("pl 999-000-05-55", "PL9990000555", True),
    ("DE123456789", "123456789", True),
    ("PL9990000555", "PL9990000556", False),
])
def test_tax_ids_match_country_prefix(a, b, same):
    from app.engine.suggest import tax_ids_match
    assert tax_ids_match(a, b) is same


def test_foreign_prefix_not_identified_as_other_country(seeded):
    db.session.add(Supplier(name="DE firma", tax_id="DE123456789"))
    db.session.commit()
    d = ingest(inv("F/1", tax="FR123456789"), "f.json")
    assert d.supplier_id is None


# ------------------------------------------------------------------ EDGE-15


def test_editor_refuses_empty_rules(auth_client):
    d = ingest(sample_bytes("alfa-1.xml"), "alfa-1.xml")
    resolve(d, "create_supplier", {"name": "Hurtownia Alfa", "tax_id": "PL9990000011"}, True, "admin")
    versions = d.template.active_version.version
    r = auth_client.post(f"/szablony/dokument/{d.id}/zapisz", json={"rules": {}})
    assert r.status_code == 400 and "pozycj" in r.get_json()["error"]
    assert db.session.get(Document, d.id).template.active_version.version == versions


def test_editor_warns_when_required_mapping_removed(auth_client):
    d = ingest(sample_bytes("alfa-1.xml"), "alfa-1.xml")
    resolve(d, "create_supplier", {"name": "Hurtownia Alfa", "tax_id": "PL9990000011"}, True, "admin")
    rules = d.template.active_version.rules
    assert "number" in rules["header"]
    stripped = {**rules, "header": {k: v for k, v in rules["header"].items() if k != "number"}}
    r = auth_client.post(f"/szablony/dokument/{d.id}/zapisz", json={"rules": stripped})
    body = r.get_json()
    assert r.status_code == 400 and body["needs_confirm"] is True and "Numer faktury" in body["error"]
    r = auth_client.post(f"/szablony/dokument/{d.id}/zapisz", json={"rules": stripped, "confirm_incomplete": True})
    assert r.status_code == 200


# ------------------------------------------------------------------ EDGE-19


def _zero_lines(doc_type):
    from app.engine.lookups import MemoryLookups
    from app.engine.template import apply_template
    from app.ingest import read_document
    tree = read_document(inv("Z/1", []), "z.json")
    rules = {"line_path": "root/invoice/items", "header": {"number": {"path": "root/invoice/number"}},
             "defaults": {"doc_type": doc_type}}
    res = apply_template(tree, rules, MemoryLookups())
    return [i for i in res.issues if i.field == "line_path"]


@pytest.mark.parametrize("doc_type", ["correction", "advance", "KOR", "zaliczka"])
def test_zero_lines_correction_is_warning(doc_type):
    issues = _zero_lines(doc_type)
    assert issues and all(i.severity == "warning" for i in issues)


def test_zero_lines_invoice_still_blocks():
    issues = _zero_lines("invoice")
    assert issues and issues[0].severity == "blocking"


# ------------------------------------------------------------------ OpenAPI


def test_openapi_documents_vat_codes_and_aggregation():
    from pathlib import Path

    import yaml
    spec = yaml.safe_load((Path(__file__).resolve().parent.parent / "app/static/openapi.yaml").read_text())
    issue = spec["components"]["schemas"]["Issue"]["properties"]
    assert {"count", "line_nos"} <= set(issue)
    vat = spec["components"]["schemas"]["InvoiceLine"]["properties"]["vat_rate"]
    assert "zw" in json.dumps(vat) and "np" in json.dumps(vat) and "oo" in json.dumps(vat)
    assert "409" in spec["paths"]["/documents/{id}/reprocess"]["post"]["responses"]
