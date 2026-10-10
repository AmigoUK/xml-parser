from decimal import Decimal
from pathlib import Path

from app.engine.issues import BLOCKING, WARNING, has_blocking
from app.engine.lookups import MemoryLookups
from app.engine.template import apply_template
from app.ingest import read_document

SAMPLES = Path(__file__).resolve().parents[2] / "demo" / "samples"

ALFA_RULES = {
    "line_path": "Document/Faktura/Pozycje/Pozycja",
    "header": {
        "number": {"path": "Document/Faktura/Naglowek/FakturaNumer"},
        "issue_date": {"path": "Document/Faktura/Naglowek/FakturaDataWystawienia"},
        "supplier.tax_id": {"path": "Document/Faktura/Naglowek/DostawcaNIP"},
        "supplier.name": {"path": "Document/Faktura/Naglowek/DostawcaNazwa"},
        "totals.net": {"path": "Document/Faktura/Naglowek/FakturaWartoscNetto"},
        "totals.gross": {"path": "Document/Faktura/Naglowek/FakturaWartoscBrutto"},
        "delivery_notes": {"path": "Document/Faktura/Naglowek/FakturaNumeryWZ"},
    },
    "lines": {
        "supplier_code": {"path": "TowarKod"},
        "gtin": {"path": "TowarKodEan", "transforms": ["strip_ai_prefix"]},
        "name": {"path": "TowarNazwa"},
        "qty": {"path": "Ilosc"},
        "unit": {"path": "TowarJm"},
        "unit_price_net": {"path": "CenaNetto"},
        "net": {"path": "WartoscNetto"},
        "vat_rate": {"path": "StawkaVat", "transforms": ["strip_percent"]},
        "batch": {"path": "TowarKodEan128", "transforms": [{"gs1": "10"}]},
        "expiry_date": {"path": "TowarKodEan128", "transforms": [{"gs1": "15"}]},
    },
    "defaults": {},
}


def alfa():
    return read_document((SAMPLES / "alfa-1.xml").read_bytes())


def full_lookups():
    return MemoryLookups(
        aliases={("pcs", 1): "szt"},
        product_by_gtin={"05909999000013": "TOW-0001", "05909999000020": "TOW-0002",
                         "05909999000037": "TOW-0003"},
    )


def codes(res):
    return [i.code for i in res.issues]


def test_missing_currency_is_blocking_then_default_fixes():
    res = apply_template(alfa(), ALFA_RULES, full_lookups(), supplier_id=1)
    assert codes(res) == ["unmapped_field"]
    assert res.issues[0].field == "currency" and res.issues[0].severity == BLOCKING
    rules = {**ALFA_RULES, "defaults": {"currency": "GBP"}}
    res = apply_template(alfa(), rules, full_lookups(), supplier_id=1)
    assert res.issues == []
    inv = res.invoice
    assert inv["currency"] == "GBP" and inv["number"] == "FA/2026/10/001"
    assert inv["delivery_notes"] == ["WZ-ALFA-0001"]
    assert inv["totals"]["gross"] == "155.50"
    l1 = inv["lines"][0]
    assert l1["gtin"] == "05909999000013" and l1["unit"] == "szt" and l1["unit_source"] == "pcs"
    assert l1["qty"] == "4" and l1["unit_price_net"] == "12.50" and l1["net"] == "50.00"
    assert l1["vat_rate"] == "0" and l1["batch"] == "L2607" and l1["expiry_date"] == "2027-07-09"
    assert l1["product_index"] == "TOW-0001" and l1["line_no"] == 1


def test_unknown_unit_reported_once_per_alias_and_override_fixes():
    rules = {**ALFA_RULES, "defaults": {"currency": "GBP"}}
    lk = full_lookups()
    lk.aliases = {}
    res = apply_template(alfa(), rules, lk, supplier_id=1)
    assert codes(res) == ["unknown_unit"]
    assert res.issues[0].source_value == "pcs"
    res = apply_template(alfa(), rules, lk, supplier_id=1, overrides={"units": {"pcs": "szt"}})
    assert res.issues == []


def test_unmapped_product_per_line_and_override():
    rules = {**ALFA_RULES, "defaults": {"currency": "GBP"}}
    lk = full_lookups()
    del lk.product_by_gtin["05909999000037"]
    res = apply_template(alfa(), rules, lk, supplier_id=1)
    assert codes(res) == ["unmapped_product"] and res.issues[0].line_no == 3
    res = apply_template(alfa(), rules, lk, supplier_id=1, overrides={"products": {"3": "TOW-0003"}})
    assert res.issues == []


def test_conversion_applied_and_missing_conversion():
    tree = read_document((SAMPLES / "delta.csv").read_bytes())
    rules = {
        "line_path": "csv/row",
        "header": {"number": {"path": "csv/row/NrFaktury"}, "issue_date": {"path": "csv/row/DataWystawienia"},
                   "currency": {"path": "csv/row/Waluta"}, "supplier.tax_id": {"path": "csv/row/SprzedawcaNIP"},
                   "totals.gross": {"path": "csv/row/RazemBrutto"}},
        "lines": {"supplier_code": {"path": "Kod"}, "name": {"path": "Nazwa"}, "gtin": {"path": "EAN"},
                  "qty": {"path": "Ilosc"}, "unit": {"path": "JM"}, "unit_price_net": {"path": "CenaNetto"},
                  "net": {"path": "WartoscNetto"}},
    }
    lk = MemoryLookups(units={"szt": True, "karton": False}, aliases={("kart.", 3): "karton"},
                       product_by_gtin={"05909999000068": "TOW-0006", "05909999000075": "TOW-0007"})
    res = apply_template(tree, rules, lk, supplier_id=3)
    assert codes(res) == ["missing_conversion", "missing_conversion"]
    lk.conversions[(3, None, "karton")] = ("szt", Decimal("12"))
    res = apply_template(tree, rules, lk, supplier_id=3)
    assert res.issues == []
    l1 = res.invoice["lines"][0]
    assert res.invoice["issue_date"] == "2026-10-09"
    assert (l1["qty"], l1["unit"], l1["unit_price_net"], l1["net"], l1["conversion_factor"]) == \
        ("24", "szt", "8.00", "192.00", "12")


def test_transform_error_and_invalid_value():
    rules = {**ALFA_RULES, "defaults": {"currency": "GBP"},
             "lines": {**ALFA_RULES["lines"], "expiry_date": {"path": "TowarKodEan128", "transforms": [{"gs1": "17"}]},
                       "gtin": {"path": "TowarKodEan"}}}
    res = apply_template(alfa(), rules, full_lookups(), supplier_id=1)
    sev = {i.code: i.severity for i in res.issues}
    # oba problemy dotyczą pól niewymaganych -> tylko ostrzeżenia
    assert sev["transform_error"] == WARNING and sev["invalid_value"] == WARNING
    # surowy 16-cyfrowy EAN nie pasuje do kartoteki -> towar nieprzypisany (blokujący)
    assert sev["unmapped_product"] == BLOCKING and has_blocking(res.issues)


def test_missing_line_path_blocks():
    res = apply_template(alfa(), {"header": {}, "lines": {}}, full_lookups())
    assert any(i.field == "line_path" and i.severity == BLOCKING for i in res.issues)


def test_constant_rule_and_field_override():
    rules = {**ALFA_RULES, "header": {**ALFA_RULES["header"], "currency": {"constant": "EUR"}}}
    res = apply_template(alfa(), rules, full_lookups(), 1, overrides={"fields": {"currency": "PLN"}})
    assert res.invoice["currency"] == "PLN" and res.issues == []
