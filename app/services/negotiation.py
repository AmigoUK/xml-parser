"""Akcje rozwiązywania problemów („negocjacja”) — jednorazowo albo z zapamiętaniem."""
from __future__ import annotations

import copy
from decimal import Decimal

from app.engine.canonical import FIELD_LABELS, LINE_KEYS
from app.engine.lookups import norm_alias, norm_product_name
from app.engine.suggest import FIELDS_BY_KEY, norm_tax_id, tax_ids_match
from app.engine.tree import relative_path
from app.engine.values import AmbiguousNumberError, normalize_gtin, to_decimal
from sqlalchemy.exc import DataError, IntegrityError

from app.extensions import db
from app.models import (STATUS_APPROVED, STATUS_DUPLICATE, STATUS_NEEDS_REVIEW, STATUS_RECEIVED,
                        STATUS_REJECTED, Document, Product, ProductMapping, Supplier, Template, Unit,
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


def ensure_template(doc: Document, rules: dict, user: str | None) -> Template:
    """Tworzy szablon dla rozpoznanego dostawcy z podanych reguł i podpina go do dokumentu."""
    supplier = db.session.get(Supplier, doc.supplier_id)
    tree = load_tree(doc)
    tpl = create_template(supplier, tree.leaf_paths(), tree.fingerprint(), tree.fmt, rules, user)
    doc.template_id = tpl.id
    doc.draft_rules = None
    return tpl


def save_rules(doc: Document, rules: dict, user: str | None, comment: str):
    """Zapisuje reguły: nowa wersja szablonu; bez szablonu — szablon (gdy dostawca znany) albo reguły robocze."""
    if doc.template_id:
        return new_version(db.session.get(Template, doc.template_id), rules, user, comment)
    if doc.supplier_id:
        return ensure_template(doc, rules, user).active_version
    doc.draft_rules = rules
    return None


_save_rules = save_rules


def _check_len(value, column, label: str, hint: str) -> None:
    """Wartość dłuższa niż kolumna → czytelny błąd zamiast DataError/500 w MariaDB (BE-8/EDGE-18)."""
    limit = column.type.length
    if value is not None and len(str(value)) > limit:
        raise NegotiationError(f"{label} ma ponad {limit} znaków — nie da się go zapamiętać; {hint}.")


def _require_supplier(doc: Document) -> None:
    if not doc.supplier_id:
        raise NegotiationError(NEED_SUPPLIER)


def _unit(code: str) -> Unit:
    u = Unit.query.filter_by(code=(code or "").strip().lower()).first()
    if not u:
        raise NegotiationError(f"Nieznana jednostka „{code}” — dodaj ją w Słownikach.")
    return u


def _line(doc: Document, line_no) -> dict:
    lines = (doc.result or {}).get("lines") or []
    try:
        n = int(line_no)
    except (TypeError, ValueError):
        n = 0
    if not 1 <= n <= len(lines):  # bez tego 0 / -1 trafiałyby w ostatnią pozycję (EDGE-25)
        raise NegotiationError(f"Brak pozycji nr {line_no}.")
    return lines[n - 1]


def parse_factor_input(raw) -> Decimal:
    """Przelicznik z formularza (negocjacja, CRUD): liczba > 0; „1,000” / „1.000” → błąd, nie 1,0."""
    try:
        factor = to_decimal(raw, reject_ambiguous=True)
    except AmbiguousNumberError:
        raise ValueError(f"Niejednoznaczna liczba „{raw}” — wpisz przelicznik bez separatora tysięcy, "
                         "np. 1000 albo 1,5.") from None
    if factor <= 0:
        raise ValueError("Przelicznik musi być większy od zera.")
    if factor >= Decimal(10) ** 12:
        raise ValueError("Przelicznik jest zbyt duży (maks. 12 cyfr całkowitych).")
    return factor


def find_supplier_by_tax_id(tax_id: str | None, exclude_id: int | None = None) -> Supplier | None:
    """Dostawca o tym samym NIP/VAT (po normalizacji, z regułą prefiksu kraju); najstarszy — deterministycznie."""
    if not norm_tax_id(tax_id):
        return None
    q = Supplier.query.filter(Supplier.tax_id.isnot(None)).order_by(Supplier.id)
    return next((s for s in q if s.id != exclude_id and tax_ids_match(tax_id, s.tax_id)), None)


def _attach_supplier(doc: Document, supplier: Supplier, user: str | None) -> None:
    doc.supplier_id = supplier.id
    tree = load_tree(doc)
    if best_template_for(supplier.id, tree.path_set()) is None:
        ensure_template(doc, doc.draft_rules or current_rules(doc), user)


def a_create_supplier(doc, data, remember, user):
    name = (data.get("name") or "").strip()
    if not name:
        raise NegotiationError("Podaj nazwę dostawcy.")
    tax_id = norm_tax_id(data.get("tax_id"))[:64] or None
    existing = find_supplier_by_tax_id(tax_id)
    if existing:  # ten sam NIP — podpinamy istniejącego zamiast tworzyć duplikat (BE-11/EDGE-9)
        _attach_supplier(doc, existing, user)
        return
    s = Supplier(name=name[:255], tax_id=tax_id)
    db.session.add(s)
    db.session.flush()
    _attach_supplier(doc, s, user)


def a_use_supplier(doc, data, remember, user):
    s = db.session.get(Supplier, int(data.get("supplier_id") or 0))
    if not s:
        raise NegotiationError("Nie znaleziono dostawcy.")
    inv_tax = norm_tax_id(((doc.result or {}).get("supplier") or {}).get("tax_id"))[:64]
    if not s.tax_id and inv_tax and not find_supplier_by_tax_id(inv_tax, exclude_id=s.id):
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
    _check_len(alias, UnitAlias.alias, "Jednostka z faktury", "przypisz ją tylko dla tej faktury")
    row = UnitAlias.query.filter_by(alias_norm=norm_alias(alias), supplier_id=doc.supplier_id).first()
    if row:
        row.unit_id = unit.id
    else:
        db.session.add(UnitAlias(alias=alias, unit_id=unit.id, supplier_id=doc.supplier_id))


def a_add_conversion(doc, data, remember, user):
    _require_supplier(doc)
    src, dst = _unit(data.get("from_unit")), _unit(data.get("to_unit"))
    try:
        factor = parse_factor_input(data.get("factor"))
    except ValueError as exc:
        raise NegotiationError(f"Przelicznik: {exc}") from None
    product_id = None
    if data.get("scope") == "product":
        code = _line(doc, data.get("line_no")).get("product_index")
        product = Product.query.filter_by(code=code).first() if code else None
        if not product:
            raise NegotiationError("Przelicznik dla towaru wymaga najpierw przypisania towaru do pozycji.")
        product_id = product.id
    # ta sama para (dostawca, towar, z jednostki) → aktualizacja zamiast duplikatu (BE-4)
    row = conversion_for_key(doc.supplier_id, product_id, src.id)
    try:
        if row:
            row.to_unit_id, row.factor = dst.id, factor
        else:
            db.session.add(UnitConversion(supplier_id=doc.supplier_id, product_id=product_id,
                                          from_unit_id=src.id, to_unit_id=dst.id, factor=factor))
    except ValueError as exc:
        raise NegotiationError(str(exc)) from None


def conversion_for_key(supplier_id, product_id, from_unit_id, exclude_id=None) -> UnitConversion | None:
    """Istniejący przelicznik dla klucza (dostawca, towar, z jednostki); NULL = „wszyscy”. Najnowszy."""
    q = UnitConversion.query.filter_by(from_unit_id=from_unit_id)
    q = q.filter(UnitConversion.supplier_id.is_(None)) if supplier_id is None else q.filter_by(supplier_id=supplier_id)
    q = q.filter(UnitConversion.product_id.is_(None)) if product_id is None else q.filter_by(product_id=product_id)
    if exclude_id is not None:
        q = q.filter(UnitConversion.id != exclude_id)
    with db.session.no_autoflush:
        return q.order_by(UnitConversion.id.desc()).first()


def _line_key(line: dict) -> tuple:
    return line.get("supplier_code"), line.get("gtin"), norm_product_name(line.get("name"))


def _map_line_to_product(doc, line_no, product: Product, remember: bool) -> None:
    line = _line(doc, line_no)
    if not remember:
        # problem zagregowany (ten sam towar w wielu pozycjach) — przypisanie dotyczy wszystkich jego pozycji
        key = _line_key(line)
        ov = copy.deepcopy(doc.overrides or {})
        products = ov.setdefault("products", {})
        for other in (doc.result or {}).get("lines") or []:
            if other is line or (not other.get("product_index") and _line_key(other) == key):
                products[str(other["line_no"])] = product.code
        doc.overrides = ov
        return
    _require_supplier(doc)
    code, gtin, name = line.get("supplier_code"), line.get("gtin"), norm_product_name(line.get("name"))
    hint = "przypisz towar tylko dla tej faktury (bez „zapamiętaj”)"
    _check_len(code, ProductMapping.supplier_code, "Kod towaru u dostawcy", hint)
    _check_len(gtin, ProductMapping.supplier_gtin, "GTIN pozycji", hint)
    q = ProductMapping.query.filter_by(supplier_id=doc.supplier_id)
    # szukamy wyłącznie po kolumnie, której używamy — nigdy po NULL (BE-3/EDGE-3)
    if code:
        row = q.filter_by(supplier_code=code).first()
    elif gtin:
        row = q.filter(ProductMapping.supplier_code.is_(None), ProductMapping.supplier_gtin == gtin).first()
    elif name:
        row = q.filter(ProductMapping.supplier_code.is_(None), ProductMapping.supplier_gtin.is_(None),
                       ProductMapping.supplier_name_norm == name).first()
    else:
        raise NegotiationError("Pozycja nie ma kodu, GTIN ani nazwy towaru — nie da się tego zapamiętać. "
                               "Przypisz towar tylko dla tej faktury (bez „zapamiętaj”).")
    if row:
        row.product_id = product.id
    else:
        db.session.add(ProductMapping(supplier_id=doc.supplier_id, supplier_code=code, supplier_gtin=gtin,
                                      supplier_name_norm=None if (code or gtin) else name,
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
    _check_len(code, Product.code, "Indeks towaru", "skróć go")
    name = name[:Product.name.type.length]  # nazwa z faktury bywa dłuższa niż kolumna (BE-8/EDGE-18)
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


def _copies(doc: Document):
    """Inne dokumenty tej samej faktury (ten sam plik albo dostawca + numer), od najstarszego."""
    cond = Document.sha256 == doc.sha256
    if doc.dedupe_hash:  # ten sam dostawca, rodzaj i znormalizowany pełny numer (BE-1)
        cond = cond | (Document.dedupe_hash == doc.dedupe_hash)
    return Document.query.filter(Document.id != doc.id, cond).order_by(Document.id).all()


def _points_to(other: Document, doc: Document) -> bool:
    return any(i.get("code") == "duplicate" and i.get("source_value") == str(doc.id) for i in other.issues or [])


def a_reject(doc, data, remember, user):
    doc.status = STATUS_REJECTED
    doc.rejected_by = (user or "operator")[:255]
    db.session.flush()
    # duplikaty odrzuconego dokumentu nie mogą wskazywać na odrzucony — przelicz je (EDGE-24)
    for other in _copies(doc):
        if other.status == STATUS_DUPLICATE and _points_to(other, doc):
            process(other)
            db.session.flush()


def restore(doc: Document, user: str | None = None) -> Document:
    """Jawne „Przywróć” operatora: cofa ręczne odrzucenie i przetwarza dokument ponownie (BE-2).

    Oryginałem jest zawsze najstarszy dokument — późniejsze kopie, które po odrzuceniu stały się
    aktywne, wracają do statusu duplikatu (nigdy dwie zatwierdzone kopie tej samej faktury)."""
    if not doc.is_manually_rejected:
        raise NegotiationError("Dokument nie jest odrzucony przez operatora.")
    try:
        doc.rejected_by = None
        doc.status = STATUS_RECEIVED
        audit("restore", "document", doc.id, {}, user)
        process(doc)
        db.session.flush()
        if doc.status != STATUS_DUPLICATE:
            for other in _copies(doc):
                if (other.id > doc.id and other.status in (STATUS_APPROVED, STATUS_NEEDS_REVIEW)
                        and not (other.overrides or {}).get("allow_duplicate")):
                    process(other)
                    db.session.flush()
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return doc


REJECTED_MSG = "Dokument został odrzucony przez operatora — najpierw użyj „Przywróć”."


ACTIONS = {
    "create_supplier": a_create_supplier, "use_supplier": a_use_supplier, "map_field": a_map_field,
    "map_unit": a_map_unit, "add_conversion": a_add_conversion, "map_product": a_map_product,
    "create_product": a_create_product, "allow_duplicate": a_allow_duplicate, "reject": a_reject,
}


RESOLVE_ATTEMPTS = 3
CONFLICT_MSG = ("Nie udało się zapisać — te same dane zmieniono równocześnie w innym oknie lub żądaniu. "
                "Odśwież stronę i spróbuj ponownie.")


def resolve(doc: Document, action: str, data: dict, remember: bool = True, user: str | None = None) -> Document:
    handler = ACTIONS.get(action)
    if handler is None:
        raise NegotiationError(f"Nieznana akcja „{action}”.")
    for attempt in range(1, RESOLVE_ATTEMPTS + 1):
        if doc.is_manually_rejected and action != "reject":  # BE-2: tylko jawne „Przywróć”
            raise NegotiationError(REJECTED_MSG)
        try:
            handler(doc, data or {}, remember, user)
            db.session.flush()
            audit(f"resolve:{action}", "document", doc.id, {"data": data or {}, "remember": remember}, user)
            if action != "reject":
                process(doc)
            db.session.commit()
            return doc
        except IntegrityError:
            # wyścig (np. ten sam NIP, kod TOW-nnnn, mapowanie, przelicznik) — ponów na świeżym stanie bazy;
            # druga próba znajduje rekord dodany równolegle i go używa (BE-7, BE-17)
            db.session.rollback()
            if attempt == RESOLVE_ATTEMPTS:
                raise NegotiationError(CONFLICT_MSG) from None
        except DataError:
            db.session.rollback()
            raise NegotiationError("Wartość jest zbyt długa lub ma niepoprawny format dla bazy danych.") from None
        except NegotiationError:
            db.session.rollback()
            raise
        except ValueError as exc:  # np. walidator modelu (przelicznik)
            db.session.rollback()
            raise NegotiationError(str(exc)) from None
        except Exception:
            db.session.rollback()
            raise
    return doc
