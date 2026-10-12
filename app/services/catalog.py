"""Kartoteka (dostawcy, towary, jednostki, aliasy, przeliczniki, mapowania): reguły przed zapisem, blokady usuwania,
użycie kodów w dokumentach i import CSV towarów — logika domenowa i granice transakcji poza warstwą widoków."""
from __future__ import annotations

import csv
import io
import json
from decimal import Decimal

from sqlalchemy import Text, or_, type_coerce
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError

from app.engine.keys import alias_key
from app.engine.lookups import norm_alias, norm_product_name
from app.engine.suggest import norm_tax_id
from app.engine.values import normalize_gtin
from app.extensions import db
from app.models import Document, Product, ProductMapping, Supplier, Template, Unit, UnitAlias, UnitConversion
from app.services.audit import audit
from app.services.negotiation import conversion_for_key, find_supplier_by_tax_id

MAX_FACTOR = Decimal("1e12")  # przelicznik większy nie ma sensu w kartotece (i nie mieści się w NUMERIC kolumny)
MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ROWS = 20000
# nagłówek CSV: nazwy kolumn akceptowane dla każdego pola (bez wielkości liter)
COLS = {"code": ("indeks", "code", "kod"), "name": ("nazwa", "name"), "gtin": ("gtin", "ean"),
        "unit": ("jednostka", "jm", "unit")}
CODE_MAX = Product.code.type.length
NAME_MAX = Product.name.type.length


# --- użycie kodów w dokumentach ---------------------------------------------------------------------------------

def _like_json_string(value: str) -> str:
    """Wzorzec LIKE dla wartości zapisanej jako napis JSON (tak jak serializuje ją SQLAlchemy)."""
    core = json.dumps(value)
    return "%" + core.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


def documents_using(kind: str, code: str) -> int:
    """Liczba dokumentów, których wynik lub ręczne przypisania odwołują się do kodu towaru („product”)
    albo jednostki („unit”) — te odwołania są tekstowe, bez klucza obcego (BE-14)."""
    if not code:
        return 0
    pattern = _like_json_string(code)
    cond = or_(type_coerce(Document.result, Text).like(pattern, escape="!"),
               type_coerce(Document.overrides, Text).like(pattern, escape="!"))
    n = 0
    with db.session.no_autoflush:
        rows = db.session.query(Document.result, Document.overrides).filter(cond).all()
    for result, overrides in rows:
        lines = (result or {}).get("lines") or [] if isinstance(result, dict) else []
        ov = overrides if isinstance(overrides, dict) else {}
        if kind == "product":
            used = (any(isinstance(ln, dict) and ln.get("product_index") == code for ln in lines)
                    or code in (ov.get("products") or {}).values())
        else:
            used = (any(isinstance(ln, dict) and ln.get("unit") == code for ln in lines)
                    or code in (ov.get("units") or {}).values())
        n += bool(used)
    return n


def code_change_blocker(obj, kind: str, label: str) -> None:
    """Zmiana kodu używanego w dokumentach osierociłaby odwołania w ich wynikach — blokujemy (BE-14)."""
    hist = sa_inspect(obj).attrs.code.history
    old = hist.deleted[0] if hist.deleted else None
    if obj.id is None or not old or old == obj.code:
        return
    used = documents_using(kind, old)
    if used:
        raise ValueError(f"Nie można zmienić kodu „{old}”: {label} jest użyty w {used} dokument(ach). "
                         "Dodaj nowy rekord zamiast zmieniać kod.")


# --- reguły przed zapisem (rzucają ValueError z komunikatem po polsku) ------------------------------------------

def product_before_save(p: Product) -> None:
    if p.gtin:
        p.gtin = normalize_gtin(p.gtin)  # walidacja + zapis jako 14 cyfr
    code_change_blocker(p, "product", "towar")


def alias_before_save(a: UnitAlias) -> None:
    a.alias_norm = norm_alias(a.alias)
    # sprawdzamy jawnie wg klucza aliasu (unikat w bazie, FR-9) i wg kolumny (kolacja, uq_alias_supplier)
    q = UnitAlias.query.filter(or_(UnitAlias.alias_key == alias_key(a.supplier_id, a.alias_norm),
                                   UnitAlias.alias_norm == a.alias_norm))
    if a.supplier_id is None:
        q = q.filter(UnitAlias.supplier_id.is_(None))
    else:
        q = q.filter(UnitAlias.supplier_id == a.supplier_id)
    if a.id is not None:
        q = q.filter(UnitAlias.id != a.id)
    with db.session.no_autoflush:
        if q.first() is not None:
            raise ValueError(f"Alias „{a.alias}” już istnieje dla tego dostawcy (lub globalnie).")


def unit_before_save(u: Unit) -> None:
    u.code = (u.code or "").strip().lower()
    code_change_blocker(u, "unit", "jednostka")


def conversion_before_save(c: UnitConversion) -> None:
    if c.factor is None or c.factor <= 0:
        raise ValueError("Przelicznik musi być większy od zera.")
    if c.factor >= MAX_FACTOR:
        raise ValueError("Przelicznik jest zbyt duży.")
    if conversion_for_key(c.supplier_id, c.product_id, c.from_unit_id, exclude_id=c.id):  # BE-4
        raise ValueError("Przelicznik z tej jednostki dla tego dostawcy i towaru już istnieje — "
                         "edytuj istniejący zamiast dodawać kolejny.")


def supplier_before_save(s: Supplier) -> None:
    s.tax_id = norm_tax_id(s.tax_id)[:Supplier.tax_id.type.length] or None  # bez spacji/myślników (BE-11/EDGE-9)
    other = find_supplier_by_tax_id(s.tax_id, exclude_id=s.id)
    if other:
        raise ValueError(f"Dostawca z tym NIP/VAT już istnieje: „{other.name}”.")


def mapping_before_save(m: ProductMapping) -> None:
    m.supplier_name_norm = norm_product_name(m.supplier_name_norm)
    if not m.supplier_code and not m.supplier_gtin and not m.supplier_name_norm:
        raise ValueError("Podaj kod, GTIN albo nazwę towaru u dostawcy.")
    if m.supplier_code or m.supplier_gtin:
        m.supplier_name_norm = None  # nazwa jest kluczem tylko dla pozycji bez kodu i GTIN (BE-3)
    if m.supplier_gtin:
        m.supplier_gtin = normalize_gtin(m.supplier_gtin)


# --- blokady usuwania (zwracają powód albo None) ----------------------------------------------------------------

def supplier_delete_blocker(s: Supplier) -> str | None:
    if Document.query.filter_by(supplier_id=s.id).count():
        return "dostawca ma przypisane dokumenty."
    if Template.query.filter_by(supplier_id=s.id).count():
        return "dostawca ma szablony."
    if ProductMapping.query.filter_by(supplier_id=s.id).count():
        return "dostawca ma mapowania towarów."
    if UnitAlias.query.filter_by(supplier_id=s.id).count() or UnitConversion.query.filter_by(supplier_id=s.id).count():
        return "dostawca ma aliasy lub przeliczniki jednostek."
    return None


def unit_delete_blocker(u: Unit) -> str | None:
    docs = documents_using("unit", u.code)
    if docs:
        return f"jednostka jest użyta w {docs} dokument(ach)."
    used = (UnitAlias.query.filter_by(unit_id=u.id).count() + Product.query.filter_by(unit_id=u.id).count()
            + UnitConversion.query.filter((UnitConversion.from_unit_id == u.id)
                                          | (UnitConversion.to_unit_id == u.id)).count())
    return "jednostka jest używana (aliasy, towary lub przeliczniki)." if used else None


def product_delete_blocker(p: Product) -> str | None:
    docs = documents_using("product", p.code)
    if docs:
        return f"towar jest użyty w {docs} dokument(ach)."
    if ProductMapping.query.filter_by(product_id=p.id).count():
        return "towar ma mapowania dostawców."
    if UnitConversion.query.filter_by(product_id=p.id).count():
        return "towar ma przeliczniki jednostek."
    return None


# --- import CSV kartoteki ---------------------------------------------------------------------------------------

def _decode_csv(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1250", errors="replace")
    return text.replace("\x00", "")


def import_products_csv(raw: bytes) -> dict:
    """Import kartoteki z CSV (nagłówek: indeks;nazwa[;gtin;jednostka]; separator wykrywany). Istniejący indeks
    aktualizuje nazwę, GTIN i jednostkę. Zwraca raport {added, updated, errors}; wiersze z błędem są pomijane,
    a konflikt danych (duplikat) wycofuje cały import. Zatwierdza transakcję."""
    report = {"added": 0, "updated": 0, "errors": []}
    text = _decode_csv(raw)
    try:
        delim = csv.Sniffer().sniff(text[:2048], delimiters=";,\t").delimiter
    except csv.Error:
        delim = ";"
    try:
        reader = csv.DictReader(io.StringIO(text), delimiter=delim)
        heads = {(h or "").strip().lower(): h for h in (reader.fieldnames or [])}
        col = {k: next((heads[a] for a in aliases if a in heads), None) for k, aliases in COLS.items()}
        if not col["code"] or not col["name"]:
            report["errors"].append("Brak kolumn „indeks” i „nazwa” w nagłówku.")
        else:
            _import_rows(reader, col, report)
            audit("import", "products", None, {"added": report["added"], "updated": report["updated"]})
            db.session.commit()
    except csv.Error as exc:
        db.session.rollback()
        report["errors"].append(f"Nieprawidłowy plik CSV: {exc}")
    except IntegrityError:
        db.session.rollback()
        report["added"] = report["updated"] = 0
        report["errors"].append("Import przerwany: konflikt danych (duplikat). Nic nie zapisano.")
    return report


def _import_rows(reader, col, report) -> None:
    units = {u.code: u for u in Unit.query.all()}
    for n, row in enumerate(reader, start=2):
        if n > MAX_IMPORT_ROWS + 1:
            report["errors"].append(f"Przekroczono limit {MAX_IMPORT_ROWS} wierszy — reszta pominięta.")
            break
        code, name = (row.get(col["code"]) or "").strip(), (row.get(col["name"]) or "").strip()
        if not code or not name:
            continue
        if len(code) > CODE_MAX or len(name) > NAME_MAX:
            report["errors"].append(f"Wiersz {n}: indeks (maks. {CODE_MAX}) lub nazwa (maks. {NAME_MAX} znaków) "
                                    "za długie.")
            continue
        gtin = (row.get(col["gtin"]) or "").strip() if col["gtin"] else ""
        if gtin:
            try:
                gtin = normalize_gtin(gtin)
            except ValueError as exc:
                report["errors"].append(f"Wiersz {n}: {exc}")
                continue
        unit_raw = ((row.get(col["unit"]) or "").strip().lower()) if col["unit"] else ""
        unit = units.get(unit_raw)
        if unit_raw and unit is None:
            report["errors"].append(f"Wiersz {n}: nieznana jednostka „{unit_raw}” — pominięto jednostkę.")
        p = Product.query.filter_by(code=code).first()
        if p:
            p.name, p.gtin = name, gtin or p.gtin
            p.unit_id = unit.id if unit else p.unit_id
            report["updated"] += 1
        else:
            db.session.add(Product(code=code, name=name, gtin=gtin or None, unit_id=unit.id if unit else None))
            report["added"] += 1
