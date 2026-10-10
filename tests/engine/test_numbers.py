"""Pakiet C audytu: liczby i wartości (EDGE-1, 2, 10, 11, 16, 21, 28). Wyłącznie fikcyjne dane."""
from decimal import Decimal

import pytest

from app.engine.issues import BLOCKING, WARNING, has_blocking
from app.engine.lookups import MemoryLookups
from app.engine.template import apply_template
from app.engine.transforms import TransformError, apply_chain
from app.engine.values import AmbiguousNumberError, fmt_money, fmt_price, fmt_qty, to_decimal
from app.ingest import read_document


# --- EDGE-1: notacja wykładnicza -------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("1e5", "100000"), ("1E5", "100000"), ("1.5e-3", "0.0015"), ("-2e2", "-200"), ("+1E+3", "1000"),
    ("2.5E2", "250"),
])
def test_exponent_notation_parsed(raw, expected):
    assert to_decimal(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["12a3", "0.1+0.2", "1e5e5", "1e", "e5", "1x2", "NaN", "Infinity", "1e99999"])
def test_letters_inside_number_rejected(raw):
    with pytest.raises(ValueError):
        to_decimal(raw)


def test_currency_and_percent_affixes_still_accepted():
    assert to_decimal("£80.50") == Decimal("80.50")
    assert to_decimal("12,50 zł") == Decimal("12.50")
    assert to_decimal("PLN 100") == Decimal("100")
    assert to_decimal("23%") == Decimal("23")


def test_json_float_exponent_preserved():
    tree = read_document(b'{"q": 1e3, "n": 1E5, "p": 0.5, "s": "x", "big": 1e400}')
    assert to_decimal(tree.first("root/q")) == Decimal("1000")
    assert to_decimal(tree.first("root/n")) == Decimal("100000")
    assert tree.first("root/p") == "0.5"
    with pytest.raises(ValueError):
        to_decimal(tree.first("root/big"))


def test_convert_transform_with_exponent_factor():
    assert apply_chain("5", [{"convert": "1e3"}]) == "5000"
    assert apply_chain("5", [{"convert": 1e3}]) == "5000"


# --- EDGE-2: znak minus ----------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("(100,00)", "-100.00"), ("(2)", "-2"), ("−5,00", "-5.00"), ("–5,00", "-5.00"),
    ("100-", "-100"), ("20,00-", "-20.00"), ("(£20.00)", "-20.00"), ("-3,10", "-3.10"),
])
def test_negative_forms(raw, expected):
    assert to_decimal(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["--5", "-5-", "(-5)", "(5", "5)", "-(5)"])
def test_conflicting_signs_rejected(raw):
    with pytest.raises(ValueError):
        to_decimal(raw)


# --- EDGE-28: brak „-0” -------------------------------------------------------------------------

def test_negative_zero_normalized():
    assert fmt_money(to_decimal("-0")) == "0.00"
    assert fmt_money(to_decimal("-0,001")) == "0.00"
    assert fmt_qty(to_decimal("-0")) == "0"
    assert fmt_price(Decimal("-0.00001")) == "0.00"
    assert apply_chain("0", ["negate"]) == "0"
    assert apply_chain("0", [{"convert": "2"}, "negate"]) == "0"


# --- EDGE-11: niejednoznaczny separator --------------------------------------------------------

@pytest.mark.parametrize("raw", ["1,234", "1.234", "12,345", "-123.456", "(1.234)"])
def test_ambiguous_number_rejected_when_requested(raw):
    with pytest.raises(AmbiguousNumberError):
        to_decimal(raw, reject_ambiguous=True)


@pytest.mark.parametrize("raw,expected", [
    ("0,234", "0.234"), ("1234,567", "1234.567"), ("1,23", "1.23"), ("1.234,56", "1234.56"),
    ("1,234,567", "1234567"), ("1234", "1234"), (",123", "0.123"),
])
def test_unambiguous_numbers_parse_with_reject_flag(raw, expected):
    assert to_decimal(raw, reject_ambiguous=True) == Decimal(expected)


def test_ambiguous_default_unchanged_without_flag():
    # wartości kanoniczne (zawsze z kropką) czytane wewnętrznie nie mogą być odrzucane
    assert to_decimal("1.234") == Decimal("1.234")


@pytest.mark.parametrize("raw,sep,expected", [
    ("1,234", ",", "1.234"), ("1,234", ".", "1234"), ("1.234", ",", "1234"), ("1.234", ".", "1.234"),
    ("1.234,5", ",", "1234.5"), ("1,234.5", ".", "1234.5"), ("12", ",", "12"),
])
def test_explicit_decimal_separator(raw, sep, expected):
    assert to_decimal(raw, decimal_sep=sep) == Decimal(expected)


@pytest.mark.parametrize("raw,sep", [("1,234.5", ","), ("1.234,5", "."), ("1,2,3", ",")])
def test_explicit_separator_conflict_rejected(raw, sep):
    with pytest.raises(ValueError):
        to_decimal(raw, decimal_sep=sep)


def test_decimal_transform_separator_argument():
    assert apply_chain("1,234", [{"decimal": ","}]) == "1.234"
    assert apply_chain("1,234", [{"decimal": "."}]) == "1234"
    with pytest.raises(TransformError):
        apply_chain("1,234", ["decimal"])
    with pytest.raises(TransformError):
        apply_chain("1", [{"decimal": ";"}])
    # wynik transformacji jest kanoniczny — kolejne kroki liczbowe go nie odrzucają
    assert apply_chain("1,234", [{"decimal": ","}, {"convert": "2"}]) == "2.468"
    assert apply_chain("1,234", [{"decimal": ","}, "negate"]) == "-1.234"


def _csv_tree(qty: str, price: str = "10", net: str = "10"):
    data = ("Nr;Data;Waluta;NIP;Kod;Nazwa;Ilosc;JM;Cena;Netto;Brutto\n"
            f"X/1;2026-10-01;PLN;9990000011;K1;Towar testowy;{qty};szt;{price};{net};{net}\n")
    return read_document(data.encode())


CSV_RULES = {
    "line_path": "csv/row",
    "header": {"number": {"path": "csv/row/Nr"}, "issue_date": {"path": "csv/row/Data"},
               "currency": {"path": "csv/row/Waluta"}, "supplier.tax_id": {"path": "csv/row/NIP"},
               "totals.gross": {"path": "csv/row/Brutto"}},
    "lines": {"supplier_code": {"path": "Kod"}, "name": {"path": "Nazwa"}, "qty": {"path": "Ilosc"},
              "unit": {"path": "JM"}, "unit_price_net": {"path": "Cena"}, "net": {"path": "Netto"}},
}


def _lookups():
    return MemoryLookups(product_by_code={(1, "K1"): "TOW-1"})


def test_ambiguous_value_in_document_is_blocking_with_hint():
    res = apply_template(_csv_tree("1,234", "10", "10"), CSV_RULES, _lookups(), supplier_id=1)
    amb = [i for i in res.issues if i.code == "ambiguous_number"]
    assert len(amb) == 1 and amb[0].severity == BLOCKING and amb[0].field == "qty"
    assert "separator" in amb[0].message
    assert res.invoice["lines"][0]["qty"] is None


def test_ambiguous_value_resolved_by_explicit_separator():
    rules = {**CSV_RULES, "lines": {**CSV_RULES["lines"], "qty": {"path": "Ilosc", "transforms": [{"decimal": ","}]}}}
    res = apply_template(_csv_tree("1,234", "10", "12,34"), rules, _lookups(), supplier_id=1)
    assert not [i for i in res.issues if i.code == "ambiguous_number"]
    assert res.invoice["lines"][0]["qty"] == "1.234"


def test_ambiguous_value_inferred_from_other_values_in_document():
    # „12,34” jednoznacznie wskazuje przecinek dziesiętny → „1,234” to 1.234
    res = apply_template(_csv_tree("1,234", "10,00", "12,34"), CSV_RULES, _lookups(), supplier_id=1)
    assert not [i for i in res.issues if i.code == "ambiguous_number"]
    assert res.invoice["lines"][0]["qty"] == "1.234"
    # „10.00” wskazuje kropkę dziesiętną → „1,234” to tysiące
    res = apply_template(_csv_tree("1,234", "10.00", "12340.00"), CSV_RULES, _lookups(), supplier_id=1)
    assert res.invoice["lines"][0]["qty"] == "1234"


def test_conflicting_document_evidence_keeps_ambiguity_blocking():
    res = apply_template(_csv_tree("1,234", "10.00", "12,34"), CSV_RULES, _lookups(), supplier_id=1)
    assert [i for i in res.issues if i.code == "ambiguous_number"]


def test_json_numbers_are_never_ambiguous():
    data = (b'{"number": "J/1", "issue_date": "2026-10-01", "currency": "GBP", "vat": "GB999000044",'
            b' "gross": 12.34, "items": [{"sku": "K1", "name": "Towar", "qty": 1.234, "uom": "szt",'
            b' "net": 12.34}]}')
    rules = {"line_path": "root/items",
             "header": {"number": {"path": "root/number"}, "issue_date": {"path": "root/issue_date"},
                        "currency": {"path": "root/currency"}, "supplier.tax_id": {"path": "root/vat"},
                        "totals.gross": {"path": "root/gross"}},
             "lines": {"supplier_code": {"path": "sku"}, "name": {"path": "name"}, "qty": {"path": "qty"},
                       "unit": {"path": "uom"}, "net": {"path": "net"}}}
    res = apply_template(read_document(data), rules, _lookups(), supplier_id=1)
    assert not [i for i in res.issues if i.code == "ambiguous_number"]
    assert res.invoice["lines"][0]["qty"] == "1.234"


def test_json_number_without_other_evidence_is_not_ambiguous():
    tree = read_document(b'{"a": {"qty": 1.234, "net": 10, "label": "1,234"}}')
    assert tree.first("root/a/qty") == "1.234"
    assert to_decimal(tree.first("root/a/qty"), reject_ambiguous=True) == Decimal("1.234")
    assert to_decimal(tree.first("root/a/net"), reject_ambiguous=True) == Decimal("10")
    with pytest.raises(AmbiguousNumberError):  # tekst w JSON-ie nadal podlega regule
        to_decimal(tree.first("root/a/label"), reject_ambiguous=True)
    huge = read_document(b'{"n": ' + b"9" * 5000 + b'}')
    with pytest.raises(ValueError):
        to_decimal(huge.first("root/n"))


def test_ambiguous_issue_in_transform_chain_reported_as_ambiguous():
    rules = {**CSV_RULES, "lines": {**CSV_RULES["lines"], "qty": {"path": "Ilosc", "transforms": ["decimal"]}}}
    res = apply_template(_csv_tree("1,234", "10", "10"), rules, _lookups(), supplier_id=1)
    amb = [i for i in res.issues if i.code == "ambiguous_number"]
    assert len(amb) == 1 and amb[0].severity == BLOCKING


# --- EDGE-16: convert z czynnikiem ≤ 0 --------------------------------------------------------

@pytest.mark.parametrize("factor", ["0", 0, -1, "-2", "abc"])
def test_convert_rejects_non_positive_factor(factor):
    with pytest.raises(TransformError):
        apply_chain("5", [{"convert": factor}])


# --- EDGE-10: stawki VAT ------------------------------------------------------------------------

def _vat_tree(rate: str):
    data = ("Nr;Data;Waluta;NIP;Kod;Nazwa;Ilosc;JM;Cena;Netto;Brutto;Stawka\n"
            f"X/1;2026-10-01;PLN;9990000011;K1;Towar testowy;1;szt;10.00;10.00;10.00;{rate}\n")
    return read_document(data.encode())


VAT_RULES = {**CSV_RULES, "lines": {**CSV_RULES["lines"], "vat_rate": {"path": "Stawka"}}}


@pytest.mark.parametrize("raw,code", [("zw", "zw"), ("ZW", "zw"), ("np", "np"), ("NP", "np"), ("oo", "oo"),
                                      (" Zw ", "zw"), ("np I", "np I"), ("NP II", "np II")])
def test_vat_exempt_codes_preserved(raw, code):
    res = apply_template(_vat_tree(raw), VAT_RULES, _lookups(), supplier_id=1)
    assert res.invoice["lines"][0]["vat_rate"] == code
    assert not [i for i in res.issues if i.field == "vat_rate"]


@pytest.mark.parametrize("raw", ["0,23", "0.23", "0.08"])
def test_vat_fraction_warns(raw):
    res = apply_template(_vat_tree(raw), VAT_RULES, _lookups(), supplier_id=1)
    warn = [i for i in res.issues if i.field == "vat_rate"]
    assert len(warn) == 1 and warn[0].severity == WARNING and warn[0].code == "vat_rate_fraction"
    assert "ułamek" in warn[0].message
    assert res.invoice["lines"][0]["vat_rate"] == str(to_decimal(raw)).rstrip("0")


@pytest.mark.parametrize("raw,expected", [("23", "23"), ("0", "0"), ("23%", "23"), ("8,0", "8")])
def test_vat_numeric_rates_unchanged(raw, expected):
    res = apply_template(_vat_tree(raw), VAT_RULES, _lookups(), supplier_id=1)
    assert res.invoice["lines"][0]["vat_rate"] == expected
    assert not [i for i in res.issues if i.field == "vat_rate"]


def test_vat_unknown_text_still_warning():
    res = apply_template(_vat_tree("abc"), VAT_RULES, _lookups(), supplier_id=1)
    assert [i.code for i in res.issues if i.field == "vat_rate"] == ["invalid_value"]


# --- EDGE-21: waluta ISO 4217 -------------------------------------------------------------------

def _cur_tree(cur: str):
    data = ("Nr;Data;Waluta;NIP;Kod;Nazwa;Ilosc;JM;Cena;Netto;Brutto\n"
            f"X/1;2026-10-01;{cur};9990000011;K1;Towar testowy;1;szt;10.00;10.00;10.00\n")
    return read_document(data.encode())


@pytest.mark.parametrize("raw,expected", [("PLN", "PLN"), ("pln ", "PLN"), ("zł", "PLN"), ("ZŁ", "PLN"),
                                          ("zl", "PLN"), ("EURO", "EUR"), ("€", "EUR"), ("£", "GBP"),
                                          ("gbp", "GBP"), ("USD", "USD"), ("CHF", "CHF")])
def test_currency_normalized(raw, expected):
    res = apply_template(_cur_tree(raw), CSV_RULES, _lookups(), supplier_id=1)
    assert res.invoice["currency"] == expected
    assert not [i for i in res.issues if i.field == "currency"]


@pytest.mark.parametrize("raw", ["XYZ", "złoty polski", "EU", "12"])
def test_unknown_currency_is_blocking_problem(raw):
    res = apply_template(_cur_tree(raw), CSV_RULES, _lookups(), supplier_id=1)
    cur = [i for i in res.issues if i.field == "currency"]
    assert len(cur) == 1 and cur[0].severity == BLOCKING and cur[0].code == "invalid_value"
    assert "ISO 4217" in cur[0].message
    assert has_blocking(res.issues)


def test_long_number_text_rejected_quickly():
    # ReDoS: dopiski przed/po liczbie dawały koszt kwadratowy dla długich wartości
    import time

    import pytest

    from app.engine.values import to_decimal

    start = time.monotonic()
    with pytest.raises(ValueError):
        to_decimal("1" + "a" * 50_000 + "!")
    assert time.monotonic() - start < 0.5
