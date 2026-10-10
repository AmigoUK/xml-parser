"""Zastosowanie deklaratywnego szablonu do drzewa źródłowego."""
from __future__ import annotations

from dataclasses import dataclass, field

from .canonical import (DATE, DECIMAL, GTIN, HEADER_FIELDS, LINE_FIELDS, LIST, MONEY, PRICE, TEXT,
                        UNIT, FieldDef, empty_invoice, get_path, set_path)
from .issues import BLOCKING, WARNING, Issue
from .lookups import Lookups
from .transforms import TransformContext, TransformError, apply_chain
from .tree import Node, SourceTree
from .values import (AmbiguousNumberError, PlainNumber, fmt_money, fmt_price, fmt_qty, infer_decimal_sep,
                     normalize_currency, normalize_gtin, parse_date, to_decimal, vat_code)


@dataclass
class ApplyResult:
    invoice: dict
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


def apply_template(tree: SourceTree, rules: dict, lookups: Lookups, supplier_id: int | None = None,
                   overrides: dict | None = None) -> ApplyResult:
    rules = rules or {}
    overrides = overrides or {}
    field_over = overrides.get("fields") or {}
    unit_over = {k.strip().lower(): v for k, v in (overrides.get("units") or {}).items()}
    product_over = overrides.get("products") or {}
    defaults = rules.get("defaults") or {}
    line_defaults = rules.get("line_defaults") or {}
    invoice = empty_invoice()
    issues: list[Issue] = []
    dsep = document_decimal_sep(tree)

    # --- nagłówek ---
    failed: set[str] = set()
    for f in HEADER_FIELDS:
        before = len(issues)
        raw, src = _eval_rule(tree, (rules.get("header") or {}).get(f.key), None, f, issues, None, dsep)
        if raw in (None, "", []) and f.key in defaults:
            raw = defaults[f.key]
        if f.key in field_over:
            raw = field_over[f.key]
        value = _coerce(f, raw, issues, None, src, dsep)
        if len(issues) > before:
            failed.add(f.key)
        if f.key == "doc_type" and not value:
            value = "invoice"
        set_path(invoice, f.key, value)
    for f in HEADER_FIELDS:
        if f.required and get_path(invoice, f.key) in (None, "") and f.key not in failed:
            issues.append(Issue("unmapped_field", BLOCKING,
                                f"Brak wymaganego pola „{f.label}” — wskaż je w pliku albo ustaw wartość domyślną.",
                                field=f.key))
    if not get_path(invoice, "supplier.tax_id") and not get_path(invoice, "supplier.name"):
        issues.append(Issue("unmapped_field", BLOCKING,
                            "Brak danych dostawcy — wskaż pole z NIP/VAT albo nazwą dostawcy.",
                            field="supplier.tax_id"))

    # --- pozycje ---
    line_path = rules.get("line_path")
    nodes: list[Node] = []
    if not line_path:
        issues.append(Issue("unmapped_field", BLOCKING, "Nie wskazano elementu zawierającego pozycje faktury.",
                            field="line_path"))
    else:
        nodes = tree.nodes_at(line_path)
        if not nodes:
            issues.append(Issue("unmapped_field", BLOCKING,
                                f"Nie znaleziono pozycji pod ścieżką „{line_path}”.", field="line_path"))

    seen_units: set[str] = set()
    missing_reported: set[str] = set()
    for line_no, node in enumerate(nodes, start=1):
        line = {"line_no": line_no, "unit_source": None, "product_index": None, "conversion_factor": "1"}
        failed_line: set[str] = set()
        for f in LINE_FIELDS:
            before = len(issues)
            raw, src = _eval_rule(tree, (rules.get("lines") or {}).get(f.key), node, f, issues, line_no, dsep)
            if raw in (None, "") and f.key in line_defaults:
                raw = line_defaults[f.key]
            if len(issues) > before:
                failed_line.add(f.key)
            if f.kind == UNIT:
                alias = str(raw).strip() if raw not in (None, "") else None
                line["unit_source"] = alias
                unit = None
                if alias:
                    unit = unit_over.get(alias.lower()) or lookups.unit_for_alias(alias, supplier_id)
                    if unit is None and alias.lower() not in seen_units:
                        seen_units.add(alias.lower())
                        issues.append(Issue("unknown_unit", BLOCKING,
                                            f"Nieznana jednostka miary „{alias}” — wskaż odpowiadającą jej naszą jednostkę.",
                                            field="unit", line_no=line_no, source_path=src, source_value=alias))
                    if unit is None:
                        failed_line.add("unit")
                line["unit"] = unit
                continue
            line[f.key] = _coerce(f, raw, issues, line_no, src, dsep)
            if len(issues) > before:
                failed_line.add(f.key)

        # towar
        code = product_over.get(str(line_no)) or lookups.product_for(supplier_id, line.get("supplier_code"),
                                                                     line.get("gtin"))
        line["product_index"] = code
        if not code:
            label = " ".join(x for x in (line.get("supplier_code"), line.get("name")) if x)
            issues.append(Issue("unmapped_product", BLOCKING,
                                f"Pozycja {line_no}: nie przypisano towaru z naszej kartoteki ({label}).",
                                field="product_index", line_no=line_no, source_value=label or None))

        # przelicznik
        unit = line.get("unit")
        if unit and not lookups.is_base_unit(unit):
            conv = lookups.conversion(supplier_id, code, unit)
            if conv is None:
                issues.append(Issue("missing_conversion", BLOCKING,
                                    f"Pozycja {line_no}: brak przelicznika dla jednostki „{unit}” na jednostkę bazową.",
                                    field="unit", line_no=line_no, source_value=unit))
            else:
                to_unit, factor = conv
                if line.get("qty"):
                    line["qty"] = fmt_qty(to_decimal(line["qty"]) * factor)
                if line.get("unit_price_net"):
                    line["unit_price_net"] = fmt_price(to_decimal(line["unit_price_net"]) / factor)
                line["unit"] = to_unit
                line["conversion_factor"] = fmt_qty(factor)

        for f in LINE_FIELDS:
            if (f.required and line.get(f.key) in (None, "") and f.key not in failed_line
                    and f.key not in missing_reported):
                missing_reported.add(f.key)
                issues.append(Issue("unmapped_field", BLOCKING,
                                    f"Brak wymaganego pola pozycji „{f.label}” — wskaż je w pliku.",
                                    field=f.key, line_no=line_no))
        invoice["lines"].append(line)

    return ApplyResult(invoice, issues)
