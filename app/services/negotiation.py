"""Akcje rozwiązywania problemów („negocjacja”) — jednorazowo albo z zapamiętaniem."""
from __future__ import annotations

import copy
from decimal import Decimal

from app.engine.canonical import FIELD_LABELS, LINE_KEYS
from app.engine.lookups import norm_alias
from app.engine.suggest import FIELDS_BY_KEY
from app.engine.tree import relative_path
from app.engine.values import normalize_gtin, to_decimal
from app.extensions import db
from app.models import (STATUS_REJECTED, Document, Product, ProductMapping, Supplier, Template, Unit,
                        UnitAlias, UnitConversion)
from app.services.audit import audit
from app.services.pipeline import best_template_for, current_rules, load_tree, next_product_code, process
from app.services.templates import create_template, new_version

NEED_SUPPLIER = "Najpierw rozpoznaj dostawcę — to pierwszy problem na liście."


class NegotiationError(ValueError):
    pass


def _set_override(doc: Document, section: str | None, key: str, value) -> None:
    ov = copy.deepcopy(doc.overrides or {})
    if section is None:
        ov[key] = value
    else:
        ov.setdefault(section, {})[key] = value
    doc.overrides = ov


def _save_rules(doc: Document, rules: dict, user: str | None, comment: str) -> None:
    if doc.template_id:
        new_version(db.session.get(Template, doc.template_id), rules, user, comment)
    else:
        doc.draft_rules = rules


def _require_supplier(doc: Document) -> None:
    if not doc.supplier_id:
        raise NegotiationError(NEED_SUPPLIER)


def _unit(code: str) -> Unit:
    u = Unit.query.filter_by(code=(code or "").strip().lower()).first()
    if not u:
        raise NegotiationError(f"Nieznana jednostka „{code}” — dodaj ją w Słownikach.")
    return u


def _line(doc: Document, line_no) -> dict:
    try:
        return (doc.result or {})["lines"][int(line_no) - 1]
    except (KeyError, IndexError, TypeError, ValueError):
        raise NegotiationError(f"Brak pozycji nr {line_no}.") from None


def _attach_supplier(doc: Document, supplier: Supplier, user: str | None) -> None:
    doc.supplier_id = supplier.id
    tree = load_tree(doc)
    if best_template_for(supplier.id, tree.path_set()) is None:
        rules = doc.draft_rules or current_rules(doc)
        tpl = create_template(supplier, tree.leaf_paths(), tree.fingerprint(), tree.fmt, rules, user)
        doc.template_id = tpl.id
        doc.draft_rules = None


def a_create_supplier(doc, data, remember, user):
    name = (data.get("name") or "").strip()
    if not name:
        raise NegotiationError("Podaj nazwę dostawcy.")
    s = Supplier(name=name, tax_id=(data.get("tax_id") or "").strip() or None)
    db.session.add(s)
    db.session.flush()
    _attach_supplier(doc, s, user)


def a_use_supplier(doc, data, remember, user):
    s = db.session.get(Supplier, int(data.get("supplier_id") or 0))
    if not s:
        raise NegotiationError("Nie znaleziono dostawcy.")
    inv_tax = ((doc.result or {}).get("supplier") or {}).get("tax_id")
    if not s.tax_id and inv_tax:
        s.tax_id = inv_tax
    _attach_supplier(doc, s, user)


def a_map_field(doc, data, remember, user):
    fld = data.get("field")
    if fld != "line_path" and fld not in FIELDS_BY_KEY:
        raise NegotiationError(f"Nieznane pole „{fld}”.")
    if not remember:
        if fld == "line_path" or fld in LINE_KEYS:
            raise NegotiationError("Dla pól pozycji wybierz „zapamiętaj w szablonie”.")
        if data.get("value") in (None, ""):
            raise NegotiationError("Podaj wartość.")
        _set_override(doc, "fields", fld, data["value"])
        return
    rules = current_rules(doc)
    if fld == "line_path":
        if not data.get("path"):
            raise NegotiationError("Wskaż element z pozycjami.")
        rules["line_path"] = data["path"]
    else:
        section = "lines" if fld in LINE_KEYS else "header"
        if data.get("path"):
            path = data["path"]
            if section == "lines" and rules.get("line_path"):
                path = relative_path(path, rules["line_path"]) or path
            rules.setdefault(section, {})[fld] = {"path": path, "transforms": data.get("transforms") or []}
        elif data.get("value") not in (None, ""):
            rules.setdefault("line_defaults" if section == "lines" else "defaults", {})[fld] = data["value"]
        else:
            raise NegotiationError("Wskaż ścieżkę w pliku albo wartość domyślną.")
    _save_rules(doc, rules, user, f"Mapowanie pola: {FIELD_LABELS.get(fld, fld)}")


def a_map_unit(doc, data, remember, user):
    alias = (data.get("alias") or "").strip()
    unit = _unit(data.get("unit"))
    if not alias:
        raise NegotiationError("Brak jednostki z faktury.")
    if not remember:
        _set_override(doc, "units", alias, unit.code)
        return
    _require_supplier(doc)
    row = UnitAlias.query.filter_by(alias_norm=norm_alias(alias), supplier_id=doc.supplier_id).first()
    if row:
        row.unit_id = unit.id
    else:
        db.session.add(UnitAlias(alias=alias, unit_id=unit.id, supplier_id=doc.supplier_id))


def a_add_conversion(doc, data, remember, user):
    _require_supplier(doc)
    src, dst = _unit(data.get("from_unit")), _unit(data.get("to_unit"))
    try:
        factor = to_decimal(data.get("factor"))
    except ValueError as exc:
        raise NegotiationError(f"Przelicznik: {exc}") from None
    if factor <= 0:
        raise NegotiationError("Przelicznik musi być większy od zera.")
    product_id = None
    if data.get("scope") == "product":
        code = _line(doc, data.get("line_no")).get("product_index")
        product = Product.query.filter_by(code=code).first() if code else None
        if not product:
            raise NegotiationError("Przelicznik dla towaru wymaga najpierw przypisania towaru do pozycji.")
        product_id = product.id
    try:
        db.session.add(UnitConversion(supplier_id=doc.supplier_id, product_id=product_id, from_unit_id=src.id,
                                      to_unit_id=dst.id, factor=factor))
    except ValueError as exc:
        raise NegotiationError(str(exc)) from None


def _map_line_to_product(doc, line_no, product: Product, remember: bool) -> None:
    if not remember:
        _set_override(doc, "products", str(int(line_no)), product.code)
        return
    _require_supplier(doc)
    line = _line(doc, line_no)
    code, gtin = line.get("supplier_code"), line.get("gtin")
    q = ProductMapping.query.filter_by(supplier_id=doc.supplier_id)
    row = q.filter_by(supplier_code=code).first() if code else q.filter_by(supplier_gtin=gtin).first()
    if row:
        row.product_id = product.id
    else:
        db.session.add(ProductMapping(supplier_id=doc.supplier_id, supplier_code=code, supplier_gtin=gtin,
                                      product_id=product.id))


def a_map_product(doc, data, remember, user):
    product = Product.query.filter_by(code=data.get("product_code")).first()
    if not product:
        raise NegotiationError("Nie znaleziono towaru w kartotece.")
    _map_line_to_product(doc, data.get("line_no"), product, remember)


def a_create_product(doc, data, remember, user):
    code, name = (data.get("code") or "").strip(), (data.get("name") or "").strip()
    if not code or not name:
        raise NegotiationError("Podaj indeks i nazwę towaru.")
    if Product.query.filter_by(code=code).first():
        # Podpowiedzi dla kilku pozycji jednej faktury mają ten sam kod — przydziel wolny.
        code = next_product_code()
    if remember:
        _require_supplier(doc)
    line = _line(doc, data.get("line_no"))
    gtin = None
    if line.get("gtin"):
        try:
            gtin = normalize_gtin(line["gtin"])
        except ValueError:
            gtin = None
    product = Product(code=code, name=name, gtin=gtin, unit_id=_unit(data.get("unit") or "szt").id)
    db.session.add(product)
    db.session.flush()
    _map_line_to_product(doc, data.get("line_no"), product, remember)


def a_allow_duplicate(doc, data, remember, user):
    _set_override(doc, None, "allow_duplicate", True)


def a_reject(doc, data, remember, user):
    doc.status = STATUS_REJECTED


ACTIONS = {
    "create_supplier": a_create_supplier, "use_supplier": a_use_supplier, "map_field": a_map_field,
    "map_unit": a_map_unit, "add_conversion": a_add_conversion, "map_product": a_map_product,
    "create_product": a_create_product, "allow_duplicate": a_allow_duplicate, "reject": a_reject,
}


def resolve(doc: Document, action: str, data: dict, remember: bool = True, user: str | None = None) -> Document:
    handler = ACTIONS.get(action)
    if handler is None:
        raise NegotiationError(f"Nieznana akcja „{action}”.")
    try:
        handler(doc, data or {}, remember, user)
        db.session.flush()
        audit(f"resolve:{action}", "document", doc.id, {"data": data or {}, "remember": remember}, user)
        if action != "reject":
            process(doc)
        db.session.commit()
    except NegotiationError:
        db.session.rollback()
        raise
    except ValueError as exc:  # np. walidator modelu (przelicznik)
        db.session.rollback()
        raise NegotiationError(str(exc)) from None
    return doc
