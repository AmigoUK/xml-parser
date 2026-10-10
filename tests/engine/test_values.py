from decimal import Decimal

import pytest

from app.engine.values import fmt_money, fmt_price, fmt_qty, normalize_gtin, parse_date, to_decimal


@pytest.mark.parametrize("raw,expected", [
    ("80.50", "80.50"), ("12,5", "12.5"), ("1 234,56", "1234.56"), ("1.234,56", "1234.56"),
    ("1,234.56", "1234.56"), ("£80.50", "80.50"), ("-3,10", "-3.10"), ("1 000", "1000"),
    ("5", "5"), ("0", "0"),
])
def test_to_decimal_formats(raw, expected):
    assert to_decimal(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", [None, "", "abc", "--"])
def test_to_decimal_invalid(raw):
    with pytest.raises(ValueError):
        to_decimal(raw)


def test_formatters():
    assert fmt_money(Decimal("80.5")) == "80.50"
    assert fmt_money(Decimal("1.005")) == "1.01"
    assert fmt_price(Decimal("8")) == "8.00"
    assert fmt_price(Decimal("1.6")) == "1.60"
    assert fmt_price(Decimal("0.12345")) == "0.1235"
    assert fmt_qty(Decimal("5.000")) == "5"
    assert fmt_qty(Decimal("2.50")) == "2.5"
    assert fmt_qty(Decimal("500")) == "500"


@pytest.mark.parametrize("raw,expected", [
    ("2026-10-09", "2026-10-09"), ("09.10.2026", "2026-10-09"), ("09/10/2026", "2026-10-09"),
    ("20261009", "2026-10-09"), ("2026-10-08T10:00:00Z", "2026-10-08"),
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_parse_date_invalid():
    with pytest.raises(ValueError):
        parse_date("32.13.2026")


def test_normalize_gtin():
    assert normalize_gtin("5909999000013") == "05909999000013"
    assert normalize_gtin(" 05909999000013 ") == "05909999000013"
    with pytest.raises(ValueError):
        normalize_gtin("5909999000014")
