from app.engine.canonical import empty_invoice
from app.engine.issues import BLOCKING, WARNING
from app.engine.validate import validate_invoice


def inv(lines, net=None, vat=None, gross=None):
    i = empty_invoice()
    i["lines"] = lines
    i["totals"] = {"net": net, "vat": vat, "gross": gross}
    return i


def line(qty, price, net, vat=None, gross=None):
    return {"line_no": 1, "qty": qty, "unit_price_net": price, "net": net, "vat": vat, "gross": gross}


def test_consistent_invoice_has_no_issues():
    i = inv([line("4", "12.50", "50.00", "0.00", "50.00"), line("10", "4.20", "42.00")], "92.00", "0.00", "92.00")
    assert validate_invoice(i) == []


def test_rounding_within_tolerance():
    assert validate_invoice(inv([line("3", "3.333", "10.00")], "10.00")) == []


def test_line_mismatch_is_warning():
    issues = validate_invoice(inv([line("4", "12.50", "51.00")], "51.00"))
    assert [(x.code, x.severity) for x in issues] == [("sum_mismatch_line", WARNING)]


def test_line_net_vat_gross_mismatch_is_warning():
    issues = validate_invoice(inv([line("1", "10.00", "10.00", "2.30", "12.00")], "10.00"))
    assert [(x.code, x.severity) for x in issues] == [("sum_mismatch_line", WARNING)]


def test_totals_mismatch_blocking():
    issues = validate_invoice(inv([line("1", "10.00", "10.00")], "11.00", "0.00", "11.00"))
    assert [(x.code, x.severity) for x in issues] == [("sum_mismatch_total", BLOCKING)]
    issues = validate_invoice(inv([line("1", "10.00", "10.00")], "10.00", "2.30", "12.00"))
    assert [(x.code, x.severity) for x in issues] == [("sum_mismatch_total", BLOCKING)]


def test_missing_values_are_skipped():
    assert validate_invoice(inv([line(None, None, "10.00")], None, None, "10.00")) == []
