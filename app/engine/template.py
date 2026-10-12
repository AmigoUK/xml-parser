"""Zastosowanie deklaratywnego szablonu (reguły: pole ← ścieżka → transformacje) do drzewa źródłowego.

Wynik to dokument kanoniczny (`Invoice`) i lista problemów (`Issue`): brakujące pola wymagane, błędy transformacji
i wartości, nieznane jednostki, nieprzypisane towary, brak przeliczników. Funkcja `apply_template` dzieli pracę na
nagłówek (`_apply_header`) i pozycje (`_apply_line`: pola, jednostka, towar, przelicznik, braki)."""
from __future__ import annotations

from dataclasses import dataclass, field

from .canonical import (
    DATE,
    DECIMAL,
    GTIN,
    HEADER_FIELDS,
    LINE_FIELDS,
    LIST,
    MONEY,
    PRICE,
    TEXT,
    UNIT,
    FieldDef,
    Invoice,
    InvoiceLine,
    empty_invoice,
    get_path,
    set_path,
)
from .issues import BLOCKING, WARNING, Issue
from .lookups import Lookups
from .transforms import TransformContext, TransformError, apply_chain
from .tree import Node, SourceTree
from .values import (
    AmbiguousNumberError,
    PlainNumber,
    fmt_money,
    fmt_price,
    fmt_qty,
    infer_decimal_sep,
    normalize_currency,
    normalize_gtin,
    parse_date,
    to_decimal,
    vat_code,
)

# typy dokumentów, które mogą nie mieć pozycji (EDGE-19); porównanie bez wielkości liter
ZERO_LINE_DOC_TYPES = {"correction", "advance", "korekta", "zaliczka", "zaliczkowa", "kor", "zal", "kor_zal"}
DEFAULT_DOC_TYPE = "invoice"
DEFAULT_CONVERSION_FACTOR = "1"


@dataclass
class ApplyResult:
    """Wynik zastosowania szablonu: dokument kanoniczny i problemy (bez walidacji sum — `validate_invoice`)."""
    invoice: Invoice
    issues: list[Issue] = field(default_factory=list)


def _ambiguous_issue(f: FieldDef, exc: Exception, line_no: int | None, src: str | None, raw) -> Issue:
    """Niejednoznaczna liczba zawsze blokuje — błąd o 3 rzędy wielkości nie może przejść po cichu (EDGE-11)."""
    return Issue("ambiguous_number", BLOCKING, f"{f.label}: {exc}", field=f.key, line_no=line_no,
                 source_path=src, source_value=None if raw is None else str(raw))


def document_decimal_sep(tree: SourceTree) -> str | None:
    """Separator dziesiętny jednoznacznie wynikający z wartości dokumentu (liczony raz na drzewo)."""
    if "decimal_sep" not in tree.cache:
        tree.cache["decimal_sep"] = infer_decimal_sep(n.text for n in tree.iter_nodes())
    return tree.cache["decimal_sep"]


def _eval_rule(tree: SourceTree, rule: dict | None, node: Node | None, f: FieldDef,
               issues: list[Issue], line_no: int | None, decimal_sep: str | None = None):
    """Zwraca (surowa_wartość, ścieżka_źródłowa). Dla LIST surowa wartość to lista."""
    if not rule:
        return None, None
    src = rule.get("path")
    if "constant" in rule:
        raw = None if rule["constant"] is None else str(rule["constant"])
    elif src:
        vals = tree.values(src, node) if node is not None else tree.values(src)
        if f.kind == LIST:
            return (vals or None), src
        raw = vals[0] if vals else None
    else:
        raw = None
    try:
        raw = apply_chain(raw, rule.get("transforms") or [], TransformContext(tree, node, decimal_sep))
    except TransformError as exc:
        if isinstance(exc.__cause__, AmbiguousNumberError):
            issues.append(_ambiguous_issue(f, exc, line_no, src, raw))
            return None, src
        issues.append(Issue("transform_error", BLOCKING if f.required else WARNING,
                            f"{f.label}: {exc}", field=f.key, line_no=line_no, source_path=src,
                            source_value=raw))
        return None, src
    return raw, src


def _coerce(f: FieldDef, raw, issues: list[Issue], line_no: int | None, src: str | None,
            decimal_sep: str | None = None):
    """Surowa wartość → wartość kanoniczna wg rodzaju pola (kwoty, daty, GTIN, waluta…); błąd → issue."""
    if raw is None or raw == "" or raw == []:
        return [] if f.kind == LIST else None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        raw = PlainNumber(raw)  # liczba z JSON-a szablonu (wartość domyślna) jest jednoznaczna

    def num():
        return to_decimal(raw, decimal_sep, reject_ambiguous=True)

    try:
        if f.key == "currency":
            return normalize_currency(raw)
        if f.key == "vat_rate":
            code = vat_code(raw)
            if code:
                return code
            rate = num()
            if 0 < rate < 1:
                issues.append(Issue("vat_rate_fraction", WARNING,
                                    f"{f.label}: wartość {fmt_qty(rate)} wygląda na ułamek, nie procent "
                                    f"(np. 0,23 zamiast 23) — sprawdź mapowanie pola.",
                                    field=f.key, line_no=line_no, source_path=src, source_value=str(raw)))
            return fmt_qty(rate)
        if f.kind == LIST:
            items = raw if isinstance(raw, list) else str(raw).split(",")
            return [str(x).strip() for x in items if str(x).strip()]
        if f.kind in (TEXT, UNIT):
            return str(raw).strip()
        if f.kind == DATE:
            return parse_date(str(raw))
        if f.kind == MONEY:
            return fmt_money(num())
        if f.kind == PRICE:
            return fmt_price(num())
        if f.kind == DECIMAL:
            return fmt_qty(num())
        if f.kind == GTIN:
            return normalize_gtin(str(raw))
    except AmbiguousNumberError as exc:
        issues.append(_ambiguous_issue(f, exc, line_no, src, raw))
        return None
    except (ValueError, ArithmeticError) as exc:
        issues.append(Issue("invalid_value", BLOCKING if f.required else WARNING,
                            f"{f.label}: {exc}", field=f.key, line_no=line_no, source_path=src,
                            source_value=str(raw)))
        return str(raw) if f.kind == GTIN else None
    return raw


@dataclass
class _Apply:
    """Stan jednego zastosowania szablonu: drzewo, reguły, słowniki, nadpisania operatora i zebrane problemy."""
    tree: SourceTree
    rules: dict
    lookups: Lookups
    supplier_id: int | None
    field_over: dict
    unit_over: dict
    product_over: dict
    dsep: str | None
    issues: list[Issue] = field(default_factory=list)
    seen_units: set[str] = field(default_factory=set)        # nieznane jednostki zgłoszone raz na dokument
    missing_reported: set[str] = field(default_factory=set)  # brak pola wymaganego pozycji zgłaszany raz

    def rule(self, section: str, key: str) -> dict | None:
        return (self.rules.get(section) or {}).get(key)


def _apply_header(ctx: _Apply, invoice: Invoice) -> None:
    """Pola nagłówka: reguła → wartość domyślna → nadpisanie operatora; braki pól wymaganych i danych dostawcy."""
    defaults = ctx.rules.get("defaults") or {}
    failed: set[str] = set()
    for f in HEADER_FIELDS:
        before = len(ctx.issues)
        raw, src = _eval_rule(ctx.tree, ctx.rule("header", f.key), None, f, ctx.issues, None, ctx.dsep)
        if raw in (None, "", []) and f.key in defaults:
            raw = defaults[f.key]
        if f.key in ctx.field_over:
            raw = ctx.field_over[f.key]
        value = _coerce(f, raw, ctx.issues, None, src, ctx.dsep)
        if len(ctx.issues) > before:
            failed.add(f.key)
        if f.key == "doc_type" and not value:
            value = DEFAULT_DOC_TYPE
        set_path(invoice, f.key, value)
    for f in HEADER_FIELDS:
        if f.required and get_path(invoice, f.key) in (None, "") and f.key not in failed:
            ctx.issues.append(Issue("unmapped_field", BLOCKING,
                                    f"Brak wymaganego pola „{f.label}” — wskaż je w pliku albo ustaw wartość domyślną.",
                                    field=f.key))
    if not get_path(invoice, "supplier.tax_id") and not get_path(invoice, "supplier.name"):
        ctx.issues.append(Issue("unmapped_field", BLOCKING,
                                "Brak danych dostawcy — wskaż pole z NIP/VAT albo nazwą dostawcy.",
                                field="supplier.tax_id"))


def _line_nodes(ctx: _Apply, invoice: Invoice) -> list[Node]:
    """Węzły pozycji wg `line_path`; brak ścieżki albo pozycji to problem (dla korekt i zaliczek tylko
    ostrzeżenie — EDGE-19)."""
    line_path = ctx.rules.get("line_path")
    no_lines_ok = str(invoice.get("doc_type") or "").strip().lower() in ZERO_LINE_DOC_TYPES
    severity = WARNING if no_lines_ok else BLOCKING
    if not line_path:
        ctx.issues.append(Issue("unmapped_field", severity, "Nie wskazano elementu zawierającego pozycje faktury.",
                                field="line_path"))
        return []
    nodes = ctx.tree.nodes_at(line_path)
    if not nodes:
        ctx.issues.append(Issue("unmapped_field", severity, f"Nie znaleziono pozycji pod ścieżką „{line_path}”.",
                                field="line_path"))
    return nodes


def _resolve_unit(ctx: _Apply, line: InvoiceLine, raw, src: str | None, line_no: int, failed: set[str]) -> None:
    """Jednostka pozycji: alias z pliku → nadpisanie operatora albo słownik aliasów; nieznana — problem raz na alias."""
    alias = str(raw).strip() if raw not in (None, "") else None
    line["unit_source"] = alias
    unit = None
    if alias:
        over = ctx.unit_over.get(alias.lower())
        if over and not ctx.lookups.unit_exists(over):
            over = None  # jednostka z ręcznego przypisania usunięta ze słownika (EDGE-7)
        unit = over or ctx.lookups.unit_for_alias(alias, ctx.supplier_id)
        if unit is None and alias.lower() not in ctx.seen_units:
            ctx.seen_units.add(alias.lower())
            ctx.issues.append(Issue("unknown_unit", BLOCKING,
                                    f"Nieznana jednostka miary „{alias}” — wskaż odpowiadającą jej naszą jednostkę.",
                                    field="unit", line_no=line_no, source_path=src, source_value=alias))
        if unit is None:
            failed.add("unit")
    line["unit"] = unit


def _resolve_product(ctx: _Apply, line: InvoiceLine, line_no: int) -> str | None:
    """Indeks towaru z kartoteki: nadpisanie operatora (musi nadal istnieć) albo mapowanie po kodzie/GTIN/nazwie."""
    over = ctx.product_over.get(str(line_no))
    if over and not ctx.lookups.product_exists(over):
        # ręcznie przypisany towar usunięto z kartoteki — nie zatwierdzamy po cichu (EDGE-7)
        ctx.issues.append(Issue("unmapped_product", BLOCKING,
                                f"Pozycja {line_no}: ręcznie przypisany towar „{over}” nie istnieje już w kartotece "
                                "— przypisz towar ponownie.",
                                field="product_index", line_no=line_no, source_value=over))
        return None
    code = over or ctx.lookups.product_for(ctx.supplier_id, line.get("supplier_code"), line.get("gtin"),
                                           line.get("name"))
    if not code and not over:
        label = " ".join(x for x in (line.get("supplier_code"), line.get("name")) if x)
        ctx.issues.append(Issue("unmapped_product", BLOCKING,
                                f"Pozycja {line_no}: nie przypisano towaru z naszej kartoteki ({label}).",
                                field="product_index", line_no=line_no, source_value=label or None))
    return code


def _apply_conversion(ctx: _Apply, line: InvoiceLine, code: str | None, line_no: int) -> None:
    """Jednostka niebazowa: przelicznik (dostawca/towar/globalny) przelicza ilość i cenę na jednostkę bazową."""
    unit = line.get("unit")
    if not unit or ctx.lookups.is_base_unit(unit):
        return
    conv = ctx.lookups.conversion(ctx.supplier_id, code, unit)
    if conv is None:
        ctx.issues.append(Issue("missing_conversion", BLOCKING,
                                f"Pozycja {line_no}: brak przelicznika dla jednostki „{unit}” na jednostkę bazową.",
                                field="unit", line_no=line_no, source_value=unit))
        return
    to_unit, factor = conv
    if line.get("qty"):
        line["qty"] = fmt_qty(to_decimal(line["qty"]) * factor)
    if line.get("unit_price_net"):
        line["unit_price_net"] = fmt_price(to_decimal(line["unit_price_net"]) / factor)
    line["unit"] = to_unit
    line["conversion_factor"] = fmt_qty(factor)


def _report_missing_line_fields(ctx: _Apply, line: InvoiceLine, line_no: int, failed: set[str]) -> None:
    """Brak pola wymaganego pozycji (bez innego problemu z tym polem) — zgłaszany raz na dokument."""
    for f in LINE_FIELDS:
        if (f.required and line.get(f.key) in (None, "") and f.key not in failed
                and f.key not in ctx.missing_reported):
            ctx.missing_reported.add(f.key)
            ctx.issues.append(Issue("unmapped_field", BLOCKING,
                                    f"Brak wymaganego pola pozycji „{f.label}” — wskaż je w pliku.",
                                    field=f.key, line_no=line_no))


def _apply_line(ctx: _Apply, node: Node, line_no: int) -> InvoiceLine:
    """Jedna pozycja: pola wg reguł i wartości domyślnych, jednostka, towar, przelicznik, raport braków."""
    line_defaults = ctx.rules.get("line_defaults") or {}
    line: InvoiceLine = {"line_no": line_no, "unit_source": None, "product_index": None,
                         "conversion_factor": DEFAULT_CONVERSION_FACTOR}
    failed: set[str] = set()
    for f in LINE_FIELDS:
        before = len(ctx.issues)
        raw, src = _eval_rule(ctx.tree, ctx.rule("lines", f.key), node, f, ctx.issues, line_no, ctx.dsep)
        if raw in (None, "") and f.key in line_defaults:
            raw = line_defaults[f.key]
        if len(ctx.issues) > before:
            failed.add(f.key)
        if f.kind == UNIT:
            _resolve_unit(ctx, line, raw, src, line_no, failed)
            continue
        line[f.key] = _coerce(f, raw, ctx.issues, line_no, src, ctx.dsep)
        if len(ctx.issues) > before:
            failed.add(f.key)
    code = _resolve_product(ctx, line, line_no)
    line["product_index"] = code
    _apply_conversion(ctx, line, code, line_no)
    _report_missing_line_fields(ctx, line, line_no, failed)
    return line


def apply_template(tree: SourceTree, rules: dict, lookups: Lookups, supplier_id: int | None = None,
                   overrides: dict | None = None) -> ApplyResult:
    """Stosuje reguły szablonu do drzewa: nagłówek, potem każda pozycja. `overrides` to ręczne przypisania operatora
    (`fields`, `units`, `products`) dla tego dokumentu. Nie rzuca wyjątków dla złych wartości — każdy problem
    trafia na listę `issues` (wyjątkiem są błędne reguły, np. niepoprawny kształt kroku transformacji)."""
    rules = rules or {}
    overrides = overrides or {}
    ctx = _Apply(tree, rules, lookups, supplier_id,
                 field_over=overrides.get("fields") or {},
                 unit_over={k.strip().lower(): v for k, v in (overrides.get("units") or {}).items()},
                 product_over=overrides.get("products") or {},
                 dsep=document_decimal_sep(tree))
    invoice = empty_invoice()
    _apply_header(ctx, invoice)
    for line_no, node in enumerate(_line_nodes(ctx, invoice), start=1):
        invoice["lines"].append(_apply_line(ctx, node, line_no))
    return ApplyResult(invoice, ctx.issues)
