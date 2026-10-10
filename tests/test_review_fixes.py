"""Poprawki z końcowego przeglądu przed v0.2.0 (FR-2, FR-5, FR-6)."""
from decimal import Decimal

import pytest

from app.engine.suggest import conversion_guess
from app.engine.values import parse_factor
from app.extensions import db
from app.models import Template, Unit, UnitConversion
from app.services.negotiation import NegotiationError, parse_factor_input, resolve
from app.services.pipeline import ingest
from tests.conftest import sample_bytes
from tests.test_negotiation_statuses import _crud_conv, inv, supplier  # noqa: F401 (fixture)


# ------------------------------------------------------------------ FR-2: przelicznik X.YYY
@pytest.mark.parametrize("raw,expected", [
    ("1.125", "1.125"), ("2.375", "2.375"), ("12.125", "12.125"), ("1.000", "1"),
    ("1,5", "1.5"), ("1,1250", "1.125"), ("0,125", "0.125"), ("1125", "1125"), ("1 125", "1125"),
    ("1e3", "1000"), ("1,000.5", "1000.5"), (12, "12"), (1.5, "1.5"),
])
def test_parse_factor_dot_is_always_decimal(raw, expected):
    assert parse_factor(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["1,125", "12,125", "1,000"])
def test_parse_factor_comma_three_digits_ambiguous_with_working_hint(raw):
    with pytest.raises(ValueError) as exc:
        parse_factor(raw)
    msg = str(exc.value)
    assert "iejednoznaczn" in msg
    dotted, plain = raw.replace(",", "."), raw.replace(",", "")
    assert dotted in msg and plain in msg
    # obie podsuwane formy są akceptowane
    assert parse_factor(dotted) and parse_factor(plain)


@pytest.mark.parametrize("raw", ["0", "-1", "0.000", "1.234.567", "abc", "", None, True])
def test_parse_factor_invalid(raw):
    with pytest.raises(ValueError):
        parse_factor(raw)


def test_negotiation_wrapper_uses_same_rules():
    assert parse_factor_input("1.125") == Decimal("1.125")
    with pytest.raises(ValueError, match="1.125"):
        parse_factor_input("1,125")


@pytest.mark.parametrize("name", ["Ser żółty 1125 g", "Olej 1,125 l", "Mąka 2.375 kg", "Woda 500 ml"])
def test_conversion_guess_is_accepted_by_parser(name):
    g = conversion_guess(name, "szt")
    assert g["factor"]
    parse_factor(g["factor"])  # podpowiedź systemu nigdy nie jest odrzucana


def test_conversion_guess_1125_g(seeded):
    assert conversion_guess("Ser żółty 1125 g", "szt")["factor"] == "1.125"


def test_negotiation_accepts_suggested_factor(supplier):  # noqa: F811
    d = ingest(inv("FR2/1"), "fr2.json")
    resolve(d, "add_conversion", {"from_unit": "karton", "to_unit": "szt", "factor": "1.125"}, True, "qa")
    assert UnitConversion.query.one().factor == Decimal("1.125")


def test_negotiation_ambiguous_comma_message(supplier):  # noqa: F811
    d = ingest(inv("FR2/2"), "fr2.json")
    with pytest.raises(NegotiationError, match=r"1\.125.*1125"):
        resolve(d, "add_conversion", {"from_unit": "karton", "to_unit": "szt", "factor": "1,125"}, True, "qa")
    assert UnitConversion.query.count() == 0


def test_crud_conversion_accepts_dot_decimal(auth_client):
    html = _crud_conv(auth_client, "1,125").get_data(as_text=True)
    assert "1.125" in html and "1125" in html
    assert UnitConversion.query.count() == 0
    _crud_conv(auth_client, "1.125")
    assert UnitConversion.query.one().factor == Decimal("1.125")


def _editor_save(auth_client, transforms):
    d = ingest(sample_bytes("alfa-1.xml"), "alfa-1.xml")
    resolve(d, "create_supplier", {"name": "Hurtownia Alfa", "tax_id": "PL9990000011"}, True, "admin")
    rules = Template.query.one().active_version.rules
    lines = {**rules["lines"], "qty": {"path": rules["lines"]["qty"]["path"], "transforms": transforms}}
    return d, auth_client.post(f"/szablony/dokument/{d.id}/zapisz", json={"rules": {**rules, "lines": lines}})


def test_editor_convert_dot_decimal(auth_client):
    _, r = _editor_save(auth_client, [{"convert": "1.125"}])
    assert r.status_code == 200, r.get_data(as_text=True)


def test_editor_convert_comma_three_digits_rejected_with_hint(auth_client):
    _, r = _editor_save(auth_client, [{"convert": "1,125"}])
    assert r.status_code == 400
    assert "1125" in r.get_data(as_text=True)
