"""Minimalny parser GS1-128 (AI najczęstsze w logistyce spożywczej)."""
import calendar
import re

FIXED = {"00": 18, "01": 14, "02": 14, "11": 6, "12": 6, "13": 6, "15": 6, "16": 6, "17": 6, "20": 2}
VARIABLE = {"10": 20, "21": 20, "22": 20, "30": 8, "37": 8, "240": 30, "241": 30}
DATE_AIS = {"11", "12", "13", "15", "16", "17"}
GS = "\x1d"
_PAREN = re.compile(r"\(([0-9]{2,4})\)([^(]*)")


class GS1Error(ValueError):
    pass


def gtin_check_digit(body: str) -> str:
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return str((10 - total % 10) % 10)


def is_valid_gtin(code: str) -> bool:
    code = (code or "").strip()
    if not (code.isascii() and code.isdigit()) or len(code) not in (8, 12, 13, 14):
        return False
    return gtin_check_digit(code[:-1]) == code[-1]


def _validate(out: dict[str, str]) -> dict[str, str]:
    if "01" in out and not is_valid_gtin(out["01"]):
        raise GS1Error(f"Błędna cyfra kontrolna GTIN w kodzie GS1: {out['01']}")
    return out


def parse_gs1(code: str) -> dict[str, str]:
    s = (code or "").strip()
    if not s:
        raise GS1Error("Pusty kod GS1.")
    out: dict[str, str] = {}
    if "(" in s:
        out = {ai: val for ai, val in _PAREN.findall(s)}
        if not out:
            raise GS1Error(f"Nie rozpoznano kodu GS1: {code}")
        return _validate(out)
    i = 0
    while i < len(s):
        if s[i] == GS:
            i += 1
            continue
        ai2, ai3 = s[i:i + 2], s[i:i + 3]
        if ai2 in FIXED:
            n = FIXED[ai2]
            val = s[i + 2:i + 2 + n]
            if len(val) < n:
                raise GS1Error(f"Za krótka wartość dla AI {ai2}.")
            out[ai2] = val
            i += 2 + n
            continue
        ai, max_len = (ai2, VARIABLE[ai2]) if ai2 in VARIABLE else (ai3, VARIABLE.get(ai3))
        if max_len is None:
            raise GS1Error(f"Nieznany identyfikator AI '{ai2}' na pozycji {i} w kodzie GS1.")
        start = i + len(ai)
        end = s.find(GS, start)
        if end == -1:
            end = len(s)
        val = s[start:min(end, start + max_len)]
        out[ai] = val
        i = start + len(val)
    return _validate(out)


def gs1_date(yymmdd: str) -> str:
    if not re.fullmatch(r"[0-9]{6}", yymmdd or ""):
        raise GS1Error(f"Niepoprawna data GS1: {yymmdd}")
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:])
    year = 2000 + yy if yy <= 49 else 1900 + yy
    if not 1 <= mm <= 12:
        raise GS1Error(f"Niepoprawny miesiąc w dacie GS1: {yymmdd}")
    last = calendar.monthrange(year, mm)[1]
    if dd == 0:
        dd = last
    elif dd > last:
        raise GS1Error(f"Niepoprawny dzień w dacie GS1: {yymmdd}")
    return f"{year:04d}-{mm:02d}-{dd:02d}"
