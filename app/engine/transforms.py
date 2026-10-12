"""Biała lista transformacji wartości. Każda: (value, arg, ctx) -> str | None."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import regex

from .gs1 import DATE_AIS, GS1Error, gs1_date, parse_gs1
from .tree import Node, SourceTree
from .values import DECIMAL_SEPARATORS, PlainNumber, fmt_qty, to_decimal
from .values import parse_factor as parse_conversion_factor

MAX_PATTERN = 200
MAX_INPUT = 1000
REGEX_TIMEOUT = 0.2


class TransformError(ValueError):
    """Błąd kroku transformacji (zły argument, wartość nie pasuje) — trafia do problemów dokumentu, nie do 500."""
    pass


@dataclass
class TransformContext:
    """Kontekst transformacji: drzewo i węzeł pozycji (dla `concat`) oraz separator dziesiętny dokumentu."""
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
    """Współczynnik transformacji 'convert' — wspólna reguła przelicznika (EDGE-16, FR-2);
    do zmiany znaku służy 'negate'."""
    return parse_conversion_factor(arg)


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
    """Stosuje łańcuch transformacji do wartości; nieznany krok albo zły argument → TransformError."""
    for step in chain or []:
        parsed = parse_step(step)
        if parsed is None:
            raise TransformError(f"Niepoprawny krok transformacji: {step!r}")
        name, arg = parsed
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


# ----------------------------------------------------------------------------------------------
# Walidacja kontraktu reguł (edytor, negocjacja, API szablonów) — polskie komunikaty, None = poprawne
# ----------------------------------------------------------------------------------------------

def _check_map(arg, key):
    if not isinstance(arg, dict):
        return f"Transformacja 'map' w polu '{key}' wymaga słownika."
    return None


def _check_convert(arg, key):
    try:
        parse_factor(arg)  # liczba > 0, spójnie z CRUD i negocjacją (EDGE-16)
    except ValueError as exc:
        return f"Transformacja 'convert' w polu '{key}': {exc}"
    return None


def _check_decimal(arg, key):
    if arg not in (None, "", *DECIMAL_SEPARATORS):
        return f"Transformacja 'decimal' w polu '{key}': separator dziesiętny musi być „,” albo „.”."
    return None


def _check_date(arg, key):
    if not (isinstance(arg, str) and arg):
        return f"Transformacja 'date' w polu '{key}' wymaga formatu daty (tekst)."
    return None


def _check_split(arg, key):
    if arg is not None and not isinstance(arg, dict):
        return f"Transformacja 'split' w polu '{key}' wymaga obiektu (sep, index)."
    arg = arg or {}
    if not isinstance(arg.get("sep", " "), str) or isinstance(arg.get("index", 0), bool) \
            or not isinstance(arg.get("index", 0), int):
        return f"Transformacja 'split' w polu '{key}': sep musi być tekstem, a index liczbą całkowitą."
    return None


def _check_concat(arg, key):
    if not isinstance(arg, dict) or not isinstance(arg.get("paths", []), list) \
            or not all(isinstance(x, str) for x in arg.get("paths", [])) \
            or not isinstance(arg.get("sep", " "), str):
        return f"Transformacja 'concat' w polu '{key}' wymaga obiektu z listą 'paths' i tekstem 'sep'."
    return None


def _check_regex(arg, key):
    pattern = arg.get("pattern", "") if isinstance(arg, dict) else None
    if not isinstance(pattern, str):
        return f"Transformacja 'regex_extract' w polu '{key}' wymaga wzorca (pattern)."
    if len(pattern) > MAX_PATTERN:
        return f"Wyrażenie regularne w polu '{key}' jest za długie (max {MAX_PATTERN} znaków)."
    try:
        regex.compile(pattern)
    except regex.error:
        return f"Błędne wyrażenie regularne w polu '{key}'."
    return None


# walidator argumentu per transformacja; brak wpisu = argument dowolny (trim, upper, gs1, constant, …)
ARG_VALIDATORS: dict[str, Callable[[Any, str], str | None]] = {
    "map": _check_map, "convert": _check_convert, "decimal": _check_decimal, "date": _check_date,
    "split": _check_split, "concat": _check_concat, "regex_extract": _check_regex,
}


def parse_step(step) -> tuple[str, Any] | None:
    """Krok łańcucha: ``"nazwa"`` albo ``{"nazwa": argument}`` → (nazwa, argument); inny kształt → None."""
    if isinstance(step, str):
        return step, None
    if isinstance(step, dict) and len(step) == 1:
        return next(iter(step.items()))
    return None


def validate_chain(chain, key: str) -> str | None:
    """Sprawdza łańcuch transformacji pola `key`: lista kroków z białej listy REGISTRY i poprawnymi argumentami.
    Zwraca polski komunikat błędu albo None."""
    if not isinstance(chain, list):
        return f"Transformacje pola '{key}' muszą być listą."
    for step in chain:
        parsed = parse_step(step)
        if parsed is None:
            return f"Niepoprawny krok transformacji w polu '{key}'."
        name, arg = parsed
        if name not in REGISTRY:
            return f"Nieznana transformacja '{name}' w polu '{key}'."
        check = ARG_VALIDATORS.get(name)
        msg = check(arg, key) if check else None
        if msg:
            return msg
    return None


def validate_rules(rules: dict) -> str | None:
    """Sprawdza reguły szablonu (sekcje, ścieżki, wartości domyślne, łańcuchy transformacji) — polski komunikat
    błędu albo None, gdy reguły są poprawne. Jedna reguła dla edytora, negocjacji i każdego innego klienta."""
    if rules.get("line_path") is not None and not isinstance(rules["line_path"], str):
        return "Ścieżka elementu z pozycjami musi być tekstem."
    for bucket in ("header", "lines", "defaults", "line_defaults"):
        if not isinstance(rules.get(bucket, {}), dict):
            return f"Sekcja '{bucket}' musi być obiektem."
    for bucket in ("defaults", "line_defaults"):
        for k, v in rules.get(bucket, {}).items():
            if not isinstance(v, (str, int, float)) or isinstance(v, bool):
                return f"Wartość domyślna pola '{k}' musi być tekstem lub liczbą."
    for bucket in ("header", "lines"):
        for key, rule in rules.get(bucket, {}).items():
            if not isinstance(rule, dict):
                return f"Reguła pola '{key}' musi być obiektem."
            for attr in ("path", "constant"):
                if rule.get(attr) is not None and not isinstance(rule[attr], str):
                    return f"Pole '{attr}' w regule '{key}' musi być tekstem."
            msg = validate_chain(rule.get("transforms", []), key)
            if msg:
                return msg
    return None
