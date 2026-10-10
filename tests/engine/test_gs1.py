import pytest

from app.engine.gs1 import GS1Error, gs1_date, gtin_check_digit, is_valid_gtin, parse_gs1


def test_check_digit():
    assert gtin_check_digit("590999900001") == "3"
    assert is_valid_gtin("5909999000013")
    assert is_valid_gtin("05909999000013")
    assert not is_valid_gtin("5909999000014")
    assert not is_valid_gtin("59099990000")
    assert not is_valid_gtin("abc")


def test_parse_plain_sequence():
    assert parse_gs1("01059099990000131527070910L2607") == {
        "01": "05909999000013", "15": "270709", "10": "L2607",
    }


def test_parse_with_fnc1_separator():
    assert parse_gs1("0105909999000013" + "10L26" + "\x1d" + "15270709") == {
        "01": "05909999000013", "10": "L26", "15": "270709",
    }


def test_parse_parenthesised():
    assert parse_gs1("(01)05909999000013(17)271231(10)ABC") == {
        "01": "05909999000013", "17": "271231", "10": "ABC",
    }


def test_invalid_gtin_in_gs1():
    with pytest.raises(GS1Error):
        parse_gs1("0105909999000014")


def test_unknown_ai():
    with pytest.raises(GS1Error):
        parse_gs1("99ABC")


def test_dates():
    assert gs1_date("270709") == "2027-07-09"
    assert gs1_date("270200") == "2027-02-28"
    assert gs1_date("991231") == "1999-12-31"


def test_invalid_day_of_month():
    with pytest.raises(GS1Error):
        gs1_date("270231")
    with pytest.raises(GS1Error):
        gs1_date("270199")


def test_invalid_month():
    with pytest.raises(GS1Error):
        gs1_date("271301")


def test_non_ascii_digits_rejected():
    assert not is_valid_gtin("²" * 8)
    with pytest.raises(GS1Error):
        gs1_date("²70709")
