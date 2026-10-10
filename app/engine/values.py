import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .gs1 import is_valid_gtin

_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y", "%Y.%m.%d")


MAX_INTEGER_DIGITS = 18


def to_decimal(raw) -> Decimal:
    if raw is None:
        raise ValueError("Brak wartości liczbowej.")
    s = str(raw).strip().replace(" ", "").replace(" ", "")
    s = re.sub(r"[^\d,.\-+]", "", s)
    if not re.search(r"\d", s):
        raise ValueError(f"Nieprawidłowa liczba: {raw!r}")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif s.count(",") == 1:
        s = s.replace(",", ".")
    elif s.count(",") > 1:
        s = s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"Nieprawidłowa liczba: {raw!r}") from None
    if not d.is_finite() or (d != 0 and d.adjusted() >= MAX_INTEGER_DIGITS):
        raise ValueError(f"Liczba poza dopuszczalnym zakresem (maks. {MAX_INTEGER_DIGITS} cyfr całkowitych).")
    return d


def fmt_money(d: Decimal) -> str:
    return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def fmt_price(d: Decimal) -> str:
    q = d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize()
    s = format(q, "f")
    whole, _, frac = s.partition(".")
    return f"{whole}.{frac.ljust(2, '0')}"


def fmt_qty(d: Decimal) -> str:
    s = format(d.normalize(), "f")
    return s


def parse_date(raw: str) -> str:
    s = (raw or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}T", s):
        s = s[:10]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Nierozpoznany format daty: {raw!r}")


def normalize_gtin(raw: str) -> str:
    s = re.sub(r"\s", "", raw or "")
    if not is_valid_gtin(s):
        raise ValueError(f"Niepoprawny GTIN/EAN (cyfra kontrolna lub długość): {raw!r}")
    return s.zfill(14)
