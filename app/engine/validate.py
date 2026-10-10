from decimal import ROUND_HALF_UP, Decimal

from .issues import BLOCKING, WARNING, Issue
from .values import to_decimal

TOL = Decimal("0.01")


def _d(v):
    if v in (None, ""):
        return None
    try:
        return to_decimal(v)
    except (ValueError, ArithmeticError):
        return None


def _r(d: Decimal) -> Decimal:
    try:
        return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except ArithmeticError:  # wynik przekracza precyzję kontekstu — porównujemy bez zaokrąglenia
        return d


def validate_invoice(invoice: dict) -> list[Issue]:
    issues: list[Issue] = []
    lines = invoice.get("lines") or []
    for ln in lines:
        no = ln.get("line_no")
        qty, price, net = _d(ln.get("qty")), _d(ln.get("unit_price_net")), _d(ln.get("net"))
        vat, gross = _d(ln.get("vat")), _d(ln.get("gross"))
        if qty is not None and price is not None and net is not None and abs(_r(qty * price) - net) > TOL:
            issues.append(Issue("sum_mismatch_line", WARNING,
                                f"Pozycja {no}: ilość × cena = {_r(qty * price)}, a wartość netto = {net}.",
                                field="net", line_no=no))
        elif net is not None and vat is not None and gross is not None and abs(net + vat - gross) > TOL:
            issues.append(Issue("sum_mismatch_line", WARNING,
                                f"Pozycja {no}: netto + VAT = {net + vat}, a brutto = {gross}.",
                                field="gross", line_no=no))
    t = invoice.get("totals") or {}
    t_net, t_vat, t_gross = _d(t.get("net")), _d(t.get("vat")), _d(t.get("gross"))
    nets = [_d(ln.get("net")) for ln in lines]
    if t_net is not None and lines and all(n is not None for n in nets):
        s = sum(nets, Decimal("0"))
        if abs(s - t_net) > TOL:
            issues.append(Issue("sum_mismatch_total", BLOCKING,
                                f"Suma netto pozycji ({s}) różni się od sumy netto faktury ({t_net}).",
                                field="totals.net"))
    if t_net is not None and t_vat is not None and t_gross is not None and abs(t_net + t_vat - t_gross) > TOL:
        issues.append(Issue("sum_mismatch_total", BLOCKING,
                            f"Netto + VAT faktury ({t_net + t_vat}) różni się od brutto ({t_gross}).",
                            field="totals.gross"))
    return issues
