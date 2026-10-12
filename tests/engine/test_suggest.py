from decimal import Decimal
from pathlib import Path

import pytest

from app.engine.suggest import (
    conversion_guess,
    draft_rules,
    field_candidates,
    learned_pairs,
    load_synonyms,
    norm_tax_id,
    product_candidates,
    suffix_match,
    supplier_candidates,
    tax_ids_match,
    unit_candidates,
)
from app.engine.template import apply_template
from app.engine.validate import validate_invoice
from app.ingest import read_document

SAMPLES = Path(__file__).resolve().parents[2] / "demo" / "samples"


class Permissive:
    def unit_for_alias(self, alias, supplier_id): return alias.lower()
    def is_base_unit(self, code): return True
    def conversion(self, *a): return None
    def product_for(self, *a): return "X"


def tree(name):
    return read_document((SAMPLES / name).read_bytes(), name)


@pytest.mark.parametrize("name,number,gross,n_lines,first_qty,expected_codes", [
    ("alfa-1.xml", "FA/2026/10/001", "155.50", 3, "4", ["unmapped_field"]),
    ("beta-ksef.xml", "FV/B/1024/2026", "1050.00", 2, "20", []),
    ("gamma-ubl.xml", "GAM-2026-0315", "83.46", 2, "12", []),
    ("delta.csv", "D/77/2026", "383.76", 2, "2", []),
    ("epsilon.json", "E-2026-0042", "45.60", 2, "6", []),
])
def test_draft_rules_read_every_sample(name, number, gross, n_lines, first_qty, expected_codes):
    t = tree(name)
    rules = draft_rules(t, load_synonyms())
    res = apply_template(t, rules, Permissive(), supplier_id=1)
    assert [i.code for i in res.issues] == expected_codes
    inv = res.invoice
    assert inv["number"] == number
    assert inv["totals"]["gross"] == gross
    assert len(inv["lines"]) == n_lines
    assert inv["lines"][0]["qty"] == first_qty
    assert validate_invoice(inv) == []


def test_alfa_draft_uses_gs1_and_ai_prefix():
    rules = draft_rules(tree("alfa-1.xml"), load_synonyms())
    assert rules["lines"]["gtin"]["transforms"] == ["strip_ai_prefix"]
    assert rules["lines"]["batch"] == {"path": "TowarKodEan128", "transforms": [{"gs1": "10"}]}
    assert rules["lines"]["expiry_date"]["transforms"] == [{"gs1": "15"}]
    assert rules["lines"]["vat_rate"]["transforms"] == ["strip_percent"]
    assert "currency" not in rules["header"]


def test_ubl_unit_from_attribute():
    rules = draft_rules(tree("gamma-ubl.xml"), load_synonyms())
    assert rules["lines"]["unit"]["path"] == "InvoicedQuantity/@unitCode"


def test_learned_pairs_take_priority():
    t = tree("alfa-1.xml")
    learned = learned_pairs([{"header": {"currency": {"path": "Document/Faktura/Naglowek/FakturaTypPlatnosci"}}}])
    cands = field_candidates(t, "currency", "Document/Faktura/Pozycje/Pozycja", load_synonyms(), learned)
    assert cands[0].path.endswith("FakturaTypPlatnosci") and cands[0].confidence == 0.95


def test_header_fallback_inside_lines_for_csv():
    cands = field_candidates(tree("delta.csv"), "number", "csv/row", load_synonyms())
    assert cands[0].path == "csv/row/NrFaktury" and cands[0].confidence < 0.9


def test_suffix_match():
    assert suffix_match("Invoice/AccountingSupplierParty/Party/PartyName/Name", "PartyName/Name")
    assert not suffix_match("A/TowarKodEan128", "TowarKodEan")
    assert suffix_match("a/B/c", "b/C")


def test_unit_candidates():
    syn = load_synonyms()
    codes = ["szt", "kg", "l", "m", "karton", "worek", "opak"]
    assert unit_candidates("pcs", codes, syn)[0] == {"kind": "unit", "unit": "szt", "confidence": 0.95,
                                                     "reason": "znany kod jednostki"}
    assert unit_candidates("C62", codes, syn)[0]["unit"] == "szt"
    assert unit_candidates("kart.", codes, syn)[0]["unit"] == "karton"
    assert unit_candidates("kartony", codes, syn)[0]["unit"] == "karton"


def test_product_candidates():
    products = [{"code": "TOW-0003", "name": "Masa marcepanowa 5kg", "gtin": None},
                {"code": "TOW-0001", "name": "Posypka czekoladowa 1 kg", "gtin": "5909999000013"}]
    c = product_candidates({"name": "Masa marcepanowa 5 kg", "gtin": "05909999000037"}, products)
    assert c[0]["code"] == "TOW-0003" and c[0]["confidence"] >= 0.7
    c = product_candidates({"name": "coś innego", "gtin": "05909999000013"}, products)
    assert c[0] == {"kind": "product", "code": "TOW-0001", "name": "Posypka czekoladowa 1 kg",
                    "confidence": 1.0, "reason": "zgodny GTIN"}


def test_supplier_candidates_and_tax_ids():
    assert norm_tax_id(" pl 999-000-00-11 ") == "PL9990000011"
    assert tax_ids_match("PL9990000011", "9990000011")
    assert not tax_ids_match("PL9990000011", "9990000022")
    sups = [{"id": 1, "name": "Hurtownia Alfa Sp. z o.o.", "tax_id": "9990000011"}]
    assert supplier_candidates("X", "PL9990000011", sups)[0]["supplier_id"] == 1
    assert supplier_candidates("Hurtownia Alfa", None, sups)[0]["confidence"] >= 0.7


def test_conversion_guess():
    assert conversion_guess("Mąka pszenna typ 450 25 kg", "worek") == {
        "kind": "conversion", "from_unit": "worek", "to_unit": "kg", "factor": "25", "confidence": 0.7}
    g = conversion_guess("Pudełko na tort 30x30", "karton")
    assert g["to_unit"] == "szt" and g["factor"] is None
    assert conversion_guess("Śmietanka 500 ml", "karton")["factor"] == "0.5"
