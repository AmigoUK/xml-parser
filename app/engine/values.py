import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .gs1 import is_valid_gtin

_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y", "%Y.%m.%d")


MAX_INTEGER_DIGITS = 18
MAX_FRACTION_DIGITS = 30  # dla zapisu wykładniczego (1e-400 dałoby setki zer po przecinku)
DECIMAL_SEPARATORS = (",", ".")


class AmbiguousNumberError(ValueError):
    """Liczba typu „1,234” / „1.234” — separator może być dziesiętny albo tysięcy (EDGE-11)."""


class PlainNumber(str):
    """Tekst liczby o jednoznacznym zapisie (kropka dziesiętna, bez separatorów tysięcy) — np. liczba JSON.

    Nie podlega regule niejednoznaczności; zwykły ``str`` po każdej transformacji tekstowej traci ten status."""


# minus typograficzny (U+2212), półpauza/pauza i podobne → zwykły „-” (EDGE-2)
_MINUS_TRANS = str.maketrans({"−": "-", "–": "-", "‒": "-", "—": "-", "﹣": "-",
                              "－": "-"})
# spacje (w tym twarda, wąska twarda, cienka) i apostrofy jako separatory tysięcy
_GROUPING_CHARS = re.compile(r"[\s   '’]")
# dopuszczalne dopiski przed/po liczbie: litery (waluta, „zł”, „PLN”, jednostka) i symbole walut/procentu
_AFFIX = r"(?:[^\W\d_]|[%$€£¥₤])*"
_SPLIT_AFFIXES = re.compile(rf"({_AFFIX})(.*?)({_AFFIX})", re.DOTALL)
_EXPONENT = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)[eE][+-]?\d{1,4}")
_PLAIN = re.compile(r"[\d.,]+")
_AMBIGUOUS = re.compile(r"[1-9]\d{0,2}([.,])\d{3}")


def _strip_affixes(s: str) -> str:
    m = _SPLIT_AFFIXES.fullmatch(s)
    if not m:
        return s
    if "e" in (m.group(1).lower(), m.group(3).lower()):
        raise ValueError(f"Nieprawidłowa liczba: {s!r}")  # urwany zapis wykładniczy („1e”, „e5”)
    return m.group(2)


def _invalid(raw) -> ValueError:
    return ValueError(f"Nieprawidłowa liczba: {raw!r}")


def _split_sign(s: str, raw) -> tuple[bool, str]:
    """Zwraca (ujemna, część_bez_znaku). Nawiasy, minus z przodu lub z tyłu; dwa znaki naraz → błąd."""
    s = _strip_affixes(s)
    negs = 0
    if s.startswith("(") or s.endswith(")"):
        if not (s.startswith("(") and s.endswith(")")):
            raise _invalid(raw)
        s = _strip_affixes(s[1:-1])
        negs += 1
    if s[:1] in "+-" and s:
        negs += s[0] == "-"
        sign_front = True
        s = s[1:]
    else:
        sign_front = False
    if s.endswith("-"):
        if sign_front:
            raise _invalid(raw)
        negs += 1
        s = s[:-1]
    if negs > 1 or (negs and "(" in s) or "(" in s or ")" in s:
        raise _invalid(raw)
    return bool(negs), s


def _normalize_separators(s: str, raw, decimal_sep: str | None, reject_ambiguous: bool) -> str:
    if decimal_sep == ",":
        if s.count(",") > 1 or ("," in s and "." in s and s.rfind(".") > s.rfind(",")):
            raise ValueError(f"Liczba {raw!r} nie pasuje do separatora dziesiętnego „,”.")
        return s.replace(".", "").replace(",", ".")
    if decimal_sep == ".":
        if s.count(".") > 1 or ("," in s and "." in s and s.rfind(",") > s.rfind(".")):
            raise ValueError(f"Liczba {raw!r} nie pasuje do separatora dziesiętnego „.”.")
        return s.replace(",", "")
    m = _AMBIGUOUS.fullmatch(s)
    if m and reject_ambiguous:
        sep = m.group(1)
        raise AmbiguousNumberError(
            f"Niejednoznaczna liczba {raw!r} — „{sep}” może być separatorem dziesiętnym albo tysięcy. "
            f"Ustaw separator dziesiętny w transformacji „decimal” szablonu, np. {{\"decimal\": \",\"}} "
            f"albo {{\"decimal\": \".\"}}.")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            return s.replace(".", "").replace(",", ".")
        return s.replace(",", "")
    if s.count(",") == 1:
        return s.replace(",", ".")
    if s.count(",") > 1:
        return s.replace(",", "")
    if s.count(".") > 1:
        return s.replace(".", "")
    return s


def to_decimal(raw, decimal_sep: str | None = None, *, reject_ambiguous: bool = False) -> Decimal:
    """Tekst → Decimal. Akceptuje separatory tysięcy, dopiski waluty/procentu, nawiasy i minus z tyłu
    jako liczby ujemne (EDGE-2), zapis wykładniczy (EDGE-1). Litery wewnątrz liczby → błąd.

    ``decimal_sep`` („,” albo „.”) wymusza separator dziesiętny; bez niego forma niejednoznaczna
    („1,234”) jest odrzucana ``AmbiguousNumberError`` tylko przy ``reject_ambiguous`` (EDGE-11) —
    wartości kanoniczne czytane wewnętrznie zawsze mają kropkę dziesiętną."""
    if raw is None:
        raise ValueError("Brak wartości liczbowej.")
    if decimal_sep not in (None, *DECIMAL_SEPARATORS):
        raise ValueError(f"Nieznany separator dziesiętny {decimal_sep!r} (dozwolone „,” lub „.”).")
    if isinstance(raw, PlainNumber):
        decimal_sep = "."
    s = _GROUPING_CHARS.sub("", str(raw).translate(_MINUS_TRANS))
    if not re.search(r"\d", s):
        raise _invalid(raw)
    neg, s = _split_sign(s, raw)
    if _EXPONENT.fullmatch(s):
        exponent = True
    elif _PLAIN.fullmatch(s) and re.search(r"\d", s):
        exponent = False
        s = _normalize_separators(s, raw, decimal_sep, reject_ambiguous)
    else:
        raise _invalid(raw)
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise _invalid(raw) from None
    if not d.is_finite() or (d != 0 and d.adjusted() >= MAX_INTEGER_DIGITS) \
            or (exponent and d != 0 and d.adjusted() < -MAX_FRACTION_DIGITS):
        raise ValueError(f"Liczba poza dopuszczalnym zakresem (maks. {MAX_INTEGER_DIGITS} cyfr całkowitych).")
    if exponent:
        d = Decimal(format(d, "f"))
    if neg:
        d = -d
    return _no_negative_zero(d)


# Wnioskowanie separatora dziesiętnego z innych wartości dokumentu (EDGE-11): pojedynczy separator
# z liczbą cyfr po nim różną od 3 albo poprzedzony „0”/ponad 3 cyframi jest na pewno dziesiętny;
# zapis mieszany („1.234,56”) wskazuje separator ostatni. Sprzeczne wskazania → brak wniosku.
_EVIDENCE = (
    (re.compile(r"-?(?:\d+\.\d{1,2}|\d+\.\d{4,}|0\.\d+|\d{4,}\.\d+|\d{1,3}(?:,\d{3})+\.\d+)"), "."),
    (re.compile(r"-?(?:\d+,\d{1,2}|\d+,\d{4,}|0,\d+|\d{4,},\d+|\d{1,3}(?:\.\d{3})+,\d+)"), ","),
)


def infer_decimal_sep(texts) -> str | None:
    """Separator dziesiętny jednoznacznie wskazany przez wartości dokumentu albo None."""
    found: set[str] = set()
    for text in texts:
        if not text or isinstance(text, PlainNumber) or len(text) > 40:
            continue
        t = text.strip()
        for pattern, sep in _EVIDENCE:
            if sep not in found and pattern.fullmatch(t):
                found.add(sep)
                if len(found) > 1:
                    return None
    return found.pop() if found else None


def _no_negative_zero(d: Decimal) -> Decimal:
    return abs(d) if d == 0 else d  # EDGE-28: „-0” → „0”


def fmt_money(d: Decimal) -> str:
    return str(_no_negative_zero(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)))


def fmt_price(d: Decimal) -> str:
    q = _no_negative_zero(d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize())
    s = format(q, "f")
    whole, _, frac = s.partition(".")
    return f"{whole}.{frac.ljust(2, '0')}"


def fmt_qty(d: Decimal) -> str:
    s = format(_no_negative_zero(d.normalize()), "f")
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


# Stawki VAT bez wartości liczbowej (EDGE-10): zwolnione, „nie podlega” (KSeF: np I / np II), odwrotne obciążenie.
VAT_CODES = {"zw": "zw", "np": "np", "np i": "np I", "np ii": "np II", "oo": "oo"}


def vat_code(raw) -> str | None:
    """Kod stawki VAT („zw”, „np”, „oo”…) albo None, gdy wartość nie jest kodem."""
    key = " ".join(str(raw).split()).lower().rstrip(".")
    return VAT_CODES.get(key)


# Aktywne kody ISO 4217 (EDGE-21) + typowe zapisy spotykane na fakturach.
ISO_4217 = frozenset("""
AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD BTN BWP BYN BZD CAD CDF
CHF CLP CNY COP CRC CUC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD
HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL
LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR
PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SLL SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND
TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VED VES VND VUV WST XAF XCD XCG XOF XPF YER ZAR ZMW ZWG ZWL
""".split())
CURRENCY_ALIASES = {"ZŁ": "PLN", "ZL": "PLN", "ZŁOTY": "PLN", "ZLOTY": "PLN", "€": "EUR", "EURO": "EUR",
                    "£": "GBP", "$": "USD", "US$": "USD"}


def normalize_currency(raw) -> str:
    s = " ".join(str(raw).split()).upper()
    s = CURRENCY_ALIASES.get(s, s)
    if s not in ISO_4217:
        raise ValueError(f"Nieznana waluta {str(raw).strip()!r} — oczekiwano 3-literowego kodu ISO 4217 "
                         f"(np. PLN, EUR, GBP).")
    return s
