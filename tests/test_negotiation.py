import pytest

from app.extensions import db
from app.models import Product, ProductMapping, Supplier, UnitAlias
from app.services.negotiation import NegotiationError, resolve
from app.services.pipeline import ingest
from tests.conftest import sample_bytes


def codes(doc):
    return [i["code"] for i in doc.issues]


def test_create_supplier_creates_template(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    resolve(d, "create_supplier", {"name": "Hurtownia Alfa Sp. z o.o.", "tax_id": "PL9990000011"}, True, "admin")
    assert d.supplier_id and d.template_id and d.draft_rules is None
    assert "unknown_supplier" not in codes(d)
    assert Supplier.query.one().tax_id == "PL9990000011"


def test_remember_requires_supplier(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    with pytest.raises(NegotiationError, match="rozpoznaj dostawcę"):
        resolve(d, "map_unit", {"alias": "pcs", "unit": "szt"}, True, "admin")


def test_one_off_unit_override_does_not_create_alias(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    resolve(d, "map_unit", {"alias": "pcs", "unit": "szt"}, False, "admin")
    assert "unknown_unit" not in codes(d)
    assert UnitAlias.query.filter_by(alias_norm="pcs").count() == 0


def test_map_field_default_creates_new_version(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    resolve(d, "create_supplier", {"name": "Alfa", "tax_id": "PL9990000011"}, True, "admin")
    resolve(d, "map_field", {"field": "currency", "value": "GBP"}, True, "admin")
    assert d.template.active_version.version == 2
    assert d.template.active_version.rules["defaults"]["currency"] == "GBP"
    assert d.result["currency"] == "GBP"


def test_map_field_line_path_absolute_converted_to_relative(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    resolve(d, "map_field", {"field": "batch", "path": "Document/Faktura/Pozycje/Pozycja/TowarKod"}, True, "admin")
    assert d.draft_rules["lines"]["batch"] == {"path": "TowarKod", "transforms": []}


def test_map_field_one_off_rejected_for_line_fields(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    with pytest.raises(NegotiationError):
        resolve(d, "map_field", {"field": "qty", "value": "1"}, False, "admin")


def test_create_product_and_mapping(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    resolve(d, "create_supplier", {"name": "Alfa", "tax_id": "PL9990000011"}, True, "admin")
    resolve(d, "create_product", {"line_no": 3, "code": "TOW-0999", "name": "Masa marcepanowa 5 kg", "unit": "szt"},
            True, "admin")
    assert Product.query.filter_by(code="TOW-0999").one().gtin == "05909999000037"
    assert ProductMapping.query.filter_by(supplier_code="A-300").one().product.code == "TOW-0999"
    assert "unmapped_product" not in codes(d)


def test_reject_and_allow_duplicate(seeded):
    ingest(sample_bytes("alfa-1.xml"), "a.xml")
    d2 = ingest(sample_bytes("alfa-1.xml"), "b.xml")
    assert d2.status == "duplicate"
    resolve(d2, "allow_duplicate", {}, True, "admin")
    assert "duplicate" not in codes(d2)
    resolve(d2, "reject", {}, True, "admin")
    assert d2.status == "rejected"


def test_unknown_action(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    with pytest.raises(NegotiationError):
        resolve(d, "hack", {}, True, "admin")


def test_add_conversion_invalid_factor_is_polish_error(seeded):
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    resolve(d, "create_supplier", {"name": "Alfa", "tax_id": "PL9990000011"}, True, "admin")
    for bad in ("0", "-2", "abc", "0.0000001"):
        with pytest.raises(NegotiationError):
            resolve(d, "add_conversion", {"from_unit": "kg", "to_unit": "szt", "factor": bad, "scope": "supplier"},
                    True, "admin")


def test_create_product_same_code_twice_allocates_fresh(seeded):
    # dwie pozycje nieznane w kartotece: bez GTIN w kartotece i bez mapowań dostawcy
    for p in Product.query.all():
        p.gtin = None
    ProductMapping.query.delete()
    db.session.commit()
    d = ingest(sample_bytes("alfa-1.xml"), "a.xml")
    resolve(d, "create_supplier", {"name": "Alfa", "tax_id": "PL9990000011"}, True, "admin")
    unmapped = [i for i in d.issues if i["code"] == "unmapped_product"]
    assert len(unmapped) >= 2
    code = unmapped[0]["suggestions"][0]["code"]
    for i in unmapped[:2]:  # stare (nieodświeżone) podpowiedzi o tym samym kodzie
        resolve(d, "create_product", {"line_no": i["line_no"], "code": code, "name": "Towar", "unit": "szt"},
                True, "admin")
    assert Product.query.filter(Product.name == "Towar").count() == 2
    assert ProductMapping.query.count() == 2
