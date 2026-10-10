"""Biała lista transformacji wartości. Każda: (value, arg, ctx) -> str | None."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable

import regex

from .gs1 import DATE_AIS, GS1Error, gs1_date, parse_gs1
from .tree import Node, SourceTree
from .values import DECIMAL_SEPARATORS, PlainNumber, fmt_qty, to_decimal

MAX_PATTERN = 200
MAX_INPUT = 1000
REGEX_TIMEOUT = 0.2


class TransformError(ValueError):
    pass


@dataclass
class TransformContext:
    tree: SourceTree | None = None
    node: Node | None = None
    decimal_sep: str | None = None  # separator dziesiętny wywnioskowany z dokumentu (EDGE-11)


def _num(v, ctx, sep: str | None = None) -> Decimal:
    """Wartość źródłowa → Decimal; forma niejednoznaczna bez znanego separatora → błąd (EDGE-11).

    Wynik kroków liczbowych to ``PlainNumber`` (kanoniczny zapis z kropką), więc kolejny krok go nie odrzuca."""
    if sep is None and ctx is not None:
        sep = ctx.decimal_sep
    return to_decimal(v, sep, reject_ambiguous=True)


def parse_factor(arg) -> Decimal:
    """Współczynnik transformacji 'convert' — liczba dodatnia (EDGE-16; do zmiany znaku służy 'negate')."""
    if isinstance(arg, bool) or arg is None:
        raise ValueError("Współczynnik przeliczenia musi być liczbą.")
    if isinstance(arg, (int, float, Decimal)):
        arg = PlainNumber(arg)  # liczba JSON w szablonie jest jednoznaczna
    elif not isinstance(arg, str):
        raise ValueError("Współczynnik przeliczenia musi być liczbą.")
    factor = to_decimal(arg, reject_ambiguous=True)
    if factor <= 0:
        raise ValueError("Współczynnik przeliczenia musi być większy od zera (do zmiany znaku służy 'negate').")
    return factor


def _decimal(v, arg, ctx):
    if v is None:
        return None
    if arg not in (None, "", *DECIMAL_SEPARATORS):
        raise TransformError("Argument transformacji 'decimal' to separator dziesiętny: „,” albo „.”.")
    try:
        return PlainNumber(fmt_qty(_num(v, ctx, arg or None)))
    except ValueError as exc:
        raise TransformError(str(exc)) from exc


def _date(v, arg, ctx):
    if v is None:
        return None
    try:
        return datetime.strptime(v.strip(), arg).date().isoformat()
    except (ValueError, TypeError) as exc:
        raise TransformError(f"Data {v!r} nie pasuje do formatu {arg!r}.") from exc


def _regex(v, arg, ctx):
    if v is None:
        return None
    if not isinstance(arg, dict):
        raise TransformError("Argument 'regex_extract' musi być słownikiem (pattern, group).")
    pattern = arg.get("pattern", "")
    if not isinstance(pattern, str):
        raise TransformError("Wzorzec wyrażenia regularnego musi być tekstem.")
    try:
        group = int(arg.get("group", 0))
    except (TypeError, ValueError):
        raise TransformError("Numer grupy wyrażenia regularnego musi być liczbą.") from None
    if len(pattern) > MAX_PATTERN:
        raise TransformError("Wyrażenie regularne jest za długie (max 200 znaków).")
    try:
        m = regex.search(pattern, v[:MAX_INPUT], timeout=REGEX_TIMEOUT)
    except regex.error as exc:
        raise TransformError(f"Błędne wyrażenie regularne: {exc}.") from exc
    except TimeoutError:
        raise TransformError("Wyrażenie regularne działa zbyt długo (przekroczono limit czasu).") from None
    if not m:
        raise TransformError(f"Wartość {v!r} nie pasuje do wzorca.")
    try:
        result = m.group(group)
    except (IndexError, regex.error):
        raise TransformError(f"Wzorzec nie ma grupy nr {group}.") from None
    if result is None:
        raise TransformError(f"Wartość {v!r} nie pasuje do wzorca.")
    return result


def _convert(v, arg, ctx):
    if v is None:
        return None
    try:
        return PlainNumber(fmt_qty(_num(v, ctx) * parse_factor(arg)))
    except ValueError as exc:
        raise TransformError(str(exc)) from exc


def _negate(v, arg, ctx):
    if v is None:
        return None
    try:
        return PlainNumber(fmt_qty(-_num(v, ctx)))
    except ValueError as exc:
        raise TransformError(str(exc)) from exc


def _concat(v, arg, ctx):
    if not ctx or not ctx.tree:
        raise TransformError("Brak kontekstu dokumentu dla 'concat'.")
    parts = []
    for p in (arg or {}).get("paths", []):
        val = ctx.tree.first(p, ctx.node) if ctx.node is not None else ctx.tree.first(p)
        if val:
            parts.append(val)
    return (arg or {}).get("sep", " ").join(parts) or None


def _split(v, arg, ctx):
    if v is None:
        return None
    pieces = v.split((arg or {}).get("sep", " "))
    idx = int((arg or {}).get("index", 0))
    try:
        return pieces[idx].strip()
    except IndexError:
        raise TransformError(f"Brak części nr {idx} po podziale {v!r}.") from None


def _gs1(v, arg, ctx):
    if v is None:
        return None
    try:
        parsed = parse_gs1(v)
        ai = str(arg)
        if ai not in parsed:
            raise TransformError(f"Kod GS1 nie zawiera AI ({ai}).")
        return gs1_date(parsed[ai]) if ai in DATE_AIS else parsed[ai]
    except GS1Error as exc:
        raise TransformError(str(exc)) from exc


def _strip_ai_prefix(v, arg, ctx):
    if v and len(v) == 16 and v.startswith("01") and v.isascii() and v.isdigit():
        return v[2:]
    return v


REGISTRY: dict[str, Callable[[Any, Any, TransformContext | None], str | None]] = {
    "trim": lambda v, a, c: v.strip() if v is not None else None,
    "upper": lambda v, a, c: v.upper() if v is not None else None,
    "lower": lambda v, a, c: v.lower() if v is not None else None,
    "decimal": _decimal,
    "strip_percent": lambda v, a, c: v.replace("%", "").strip() if v is not None else None,
    "date": _date,
    "regex_extract": _regex,
    "map": lambda v, a, c: (a or {}).get(v, v) if v is not None else None,
    "convert": _convert,
    "constant": lambda v, a, c: None if a is None else str(a),
    "concat": _concat,
    "split": _split,
    "negate": _negate,
    "gs1": _gs1,
    "strip_ai_prefix": _strip_ai_prefix,
}

TRANSFORM_LABELS = {
    "trim": "Usuń spacje z brzegów",
    "upper": "Wielkie litery",
    "lower": "Małe litery",
    "decimal": "Liczba; separator dziesiętny jako argument, np. {\"decimal\": \",\"}",
    "strip_percent": "Usuń znak %",
    "date": "Data wg formatu (np. %d.%m.%Y)",
    "regex_extract": "Wytnij wyrażeniem regularnym",
    "map": "Zamień wartości wg słownika",
    "convert": "Pomnóż przez współczynnik",
    "constant": "Stała wartość",
    "concat": "Połącz kilka pól",
    "split": "Podziel i weź część",
    "negate": "Zmień znak (korekty)",
    "gs1": "Wyciągnij AI z kodu GS1-128",
    "strip_ai_prefix": "Usuń prefiks AI 01 z EAN",
}


def apply_chain(value: str | None, chain: list, ctx: TransformContext | None = None) -> str | None:
    for step in chain or []:
        if isinstance(step, str):
            name, arg = step, None
        elif isinstance(step, dict) and len(step) == 1:
            name, arg = next(iter(step.items()))
        else:
            raise TransformError(f"Niepoprawny krok transformacji: {step!r}")
        fn = REGISTRY.get(name)
        if fn is None:
            raise TransformError(f"Nieznana transformacja: {name!r}")
        try:
            value = fn(value, arg, ctx)
        except TransformError:
            raise
        except (ValueError, AttributeError, TypeError, IndexError, KeyError, ArithmeticError) as exc:
            raise TransformError(f"Niepoprawny argument transformacji {name!r}.") from exc
    return value
