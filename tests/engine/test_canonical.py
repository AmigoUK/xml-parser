from decimal import Decimal

from app.engine.canonical import HEADER_KEYS, LINE_KEYS, empty_invoice, get_path, set_path
from app.engine.issues import BLOCKING, WARNING, Issue, has_blocking
from app.engine.lookups import MemoryLookups


def test_paths():
    inv = empty_invoice()
    set_path(inv, "supplier.address.city", "Przykładowo")
    assert get_path(inv, "supplier.address.city") == "Przykładowo"
    assert get_path(inv, "buyer.tax_id") is None
    assert inv["lines"] == []
    assert {"number", "supplier.tax_id", "totals.gross"} <= HEADER_KEYS
    assert {"qty", "unit", "gtin"} <= LINE_KEYS


def test_issue_helpers():
    issues = [Issue("x", WARNING, "uwaga"), Issue("y", BLOCKING, "stop").to_dict()]
    assert has_blocking(issues)
    assert not has_blocking([Issue("x", WARNING, "uwaga")])
    assert Issue("a", BLOCKING, "m").to_dict()["suggestions"] == []


def test_memory_lookups():
    lk = MemoryLookups(
        units={"szt": True, "karton": False},
        aliases={("pcs", 1): "szt", ("kart.", None): "karton"},
        conversions={(1, None, "karton"): ("szt", Decimal("12"))},
        product_by_code={(1, "A-1"): "TOW-1"},
        product_by_gtin={"05909999000013": "TOW-2"},
    )
    assert lk.unit_for_alias("PCS", 1) == "szt"
    assert lk.unit_for_alias("pcs", 2) is None
    assert lk.unit_for_alias("Kart.", 7) == "karton"
    assert lk.unit_for_alias("SZT", None) == "szt"
    assert not lk.is_base_unit("karton") and lk.is_base_unit("szt")
    assert lk.conversion(1, "TOW-9", "karton") == ("szt", Decimal("12"))
    assert lk.conversion(2, None, "karton") is None
    assert lk.product_for(1, "A-1", None) == "TOW-1"
    assert lk.product_for(5, "zzz", "05909999000013") == "TOW-2"
    assert lk.product_for(5, None, None) is None
