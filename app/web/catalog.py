import csv
import io
import json
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import Text, or_, type_coerce
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError

from app.engine.lookups import norm_alias, norm_product_name
from app.engine.suggest import norm_tax_id
from app.engine.values import normalize_gtin
from app.extensions import db
from app.models import Document, Product, ProductMapping, Supplier, Template, Unit, UnitAlias, UnitConversion
from app.services.audit import audit
from app.services.negotiation import conversion_for_key, find_supplier_by_tax_id

from .crud import CrudField, CrudSpec, register_crud

bp = Blueprint("catalog", __name__)


def unit_choices():
    return [(u.id, f"{u.code} — {u.name}") for u in Unit.query.order_by(Unit.code)]


def supplier_choices():
    return [("", "— wszyscy dostawcy (globalnie) —")] + [(s.id, s.name) for s in Supplier.query.order_by(Supplier.name)]


def product_choices():
    return [("", "— wszystkie towary —")] + [(p.id, f"{p.code} — {p.name}") for p in Product.query.order_by(Product.code)]


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


def _code_change_blocker(obj, kind: str, label: str) -> None:
    """Zmiana kodu używanego w dokumentach osierociłaby odwołania w ich wynikach — blokujemy (BE-14)."""
    hist = sa_inspect(obj).attrs.code.history
    old = hist.deleted[0] if hist.deleted else None
    if obj.id is None or not old or old == obj.code:
        return
    used = documents_using(kind, old)
    if used:
        raise ValueError(f"Nie można zmienić kodu „{old}”: {label} jest użyty w {used} dokument(ach). "
                         "Dodaj nowy rekord zamiast zmieniać kod.")


def _product_before_save(p: Product):
    if p.gtin:
        p.gtin = normalize_gtin(p.gtin)  # walidacja + zapis jako 14 cyfr
    _code_change_blocker(p, "product", "towar")


def _alias_before_save(a: UnitAlias):
    a.alias_norm = norm_alias(a.alias)
    # UniqueConstraint nie chroni przy supplier_id NULL, więc sprawdzamy jawnie
    q = UnitAlias.query.filter(UnitAlias.alias_norm == a.alias_norm)
    q = q.filter(UnitAlias.supplier_id.is_(None)) if a.supplier_id is None else q.filter(UnitAlias.supplier_id == a.supplier_id)
    if a.id is not None:
        q = q.filter(UnitAlias.id != a.id)
    with db.session.no_autoflush:
        if q.first() is not None:
            raise ValueError(f"Alias „{a.alias}” już istnieje dla tego dostawcy (lub globalnie).")


def _unit_before_save(u: Unit):
    u.code = (u.code or "").strip().lower()
    _code_change_blocker(u, "unit", "jednostka")


def _conversion_before_save(c: UnitConversion):
    if c.factor is None or c.factor <= 0:
        raise ValueError("Przelicznik musi być większy od zera.")
    if c.factor >= Decimal("1e12"):
        raise ValueError("Przelicznik jest zbyt duży.")
    if conversion_for_key(c.supplier_id, c.product_id, c.from_unit_id, exclude_id=c.id):  # BE-4
        raise ValueError("Przelicznik z tej jednostki dla tego dostawcy i towaru już istnieje — "
                         "edytuj istniejący zamiast dodawać kolejny.")


def _supplier_before_save(s: Supplier):
    s.tax_id = norm_tax_id(s.tax_id)[:64] or None  # bez spacji, myślników i kropek (BE-11/EDGE-9)
    other = find_supplier_by_tax_id(s.tax_id, exclude_id=s.id)
    if other:
        raise ValueError(f"Dostawca z tym NIP/VAT już istnieje: „{other.name}”.")


def _mapping_before_save(m: ProductMapping):
    m.supplier_name_norm = norm_product_name(m.supplier_name_norm)
    if not m.supplier_code and not m.supplier_gtin and not m.supplier_name_norm:
        raise ValueError("Podaj kod, GTIN albo nazwę towaru u dostawcy.")
    if m.supplier_code or m.supplier_gtin:
        m.supplier_name_norm = None  # nazwa jest kluczem tylko dla pozycji bez kodu i GTIN (BE-3)
    if m.supplier_gtin:
        m.supplier_gtin = normalize_gtin(m.supplier_gtin)


def _supplier_blocker(s):
    if Document.query.filter_by(supplier_id=s.id).count():
        return "dostawca ma przypisane dokumenty."
    if Template.query.filter_by(supplier_id=s.id).count():
        return "dostawca ma szablony."
    if ProductMapping.query.filter_by(supplier_id=s.id).count():
        return "dostawca ma mapowania towarów."
    if UnitAlias.query.filter_by(supplier_id=s.id).count() or UnitConversion.query.filter_by(supplier_id=s.id).count():
        return "dostawca ma aliasy lub przeliczniki jednostek."
    return None


def _unit_blocker(u):
    docs = documents_using("unit", u.code)
    if docs:
        return f"jednostka jest użyta w {docs} dokument(ach)."
    used = (UnitAlias.query.filter_by(unit_id=u.id).count() + Product.query.filter_by(unit_id=u.id).count()
            + UnitConversion.query.filter((UnitConversion.from_unit_id == u.id) | (UnitConversion.to_unit_id == u.id)).count())
    return "jednostka jest używana (aliasy, towary lub przeliczniki)." if used else None


def _product_blocker(p):
    docs = documents_using("product", p.code)
    if docs:
        return f"towar jest użyty w {docs} dokument(ach)."
    if ProductMapping.query.filter_by(product_id=p.id).count():
        return "towar ma mapowania dostawców."
    if UnitConversion.query.filter_by(product_id=p.id).count():
        return "towar ma przeliczniki jednostek."
    return None


SPECS = [
    CrudSpec("suppliers", Supplier, "Dostawcy", "/dostawcy",
             [CrudField("name", "Nazwa", required=True), CrudField("tax_id", "NIP / VAT"),
              CrudField("notes", "Notatki", "textarea")],
             [("Nazwa", lambda s: s.name), ("NIP / VAT", lambda s: s.tax_id or "—"),
              ("Szablony", lambda s: len(s.templates))],
             lambda: Supplier.name, before_save=_supplier_before_save, delete_blocker=_supplier_blocker),
    CrudSpec("products", Product, "Kartoteka towarów", "/towary",
             [CrudField("code", "Indeks", required=True), CrudField("name", "Nazwa", required=True),
              CrudField("gtin", "GTIN / EAN"),
              CrudField("unit_id", "Jednostka", "select", choices=lambda: [("", "—")] + unit_choices())],
             [("Indeks", lambda p: p.code), ("Nazwa", lambda p: p.name), ("GTIN", lambda p: p.gtin or "—"),
              ("JM", lambda p: p.unit.code if p.unit else "—")],
             lambda: Product.code, before_save=_product_before_save, delete_blocker=_product_blocker,
             extra_actions=[("Import CSV", "catalog.import_products")]),
    CrudSpec("mappings", ProductMapping, "Mapowania towarów dostawców", "/mapowania-towarow",
             [CrudField("supplier_id", "Dostawca", "select", True,
                        lambda: [(s.id, s.name) for s in Supplier.query.order_by(Supplier.name)]),
              CrudField("supplier_code", "Kod u dostawcy"), CrudField("supplier_gtin", "GTIN u dostawcy"),
              CrudField("supplier_name_norm", "Nazwa towaru u dostawcy (tylko gdy brak kodu i GTIN)"),
              CrudField("product_id", "Nasz towar", "select", True,
                        lambda: [(p.id, f"{p.code} — {p.name}") for p in Product.query.order_by(Product.code)])],
             [("Dostawca", lambda m: m.supplier.name), ("Kod", lambda m: m.supplier_code or "—"),
              ("GTIN", lambda m: m.supplier_gtin or "—"), ("Nazwa", lambda m: m.supplier_name_norm or "—"),
              ("Nasz towar", lambda m: f"{m.product.code} — {m.product.name}")],
             lambda: ProductMapping.id, before_save=_mapping_before_save),
    CrudSpec("units", Unit, "Jednostki miary", "/jednostki",
             [CrudField("code", "Kod", required=True), CrudField("name", "Nazwa", required=True),
              CrudField("is_base", "Jednostka bazowa (bez przelicznika)", "checkbox")],
             [("Kod", lambda u: u.code), ("Nazwa", lambda u: u.name), ("Bazowa", lambda u: "tak" if u.is_base else "nie")],
             lambda: Unit.code, before_save=_unit_before_save, delete_blocker=_unit_blocker),
    CrudSpec("aliases", UnitAlias, "Aliasy jednostek", "/aliasy-jednostek",
             [CrudField("alias", "Jednostka w pliku dostawcy", required=True),
              CrudField("unit_id", "Nasza jednostka", "select", True, unit_choices),
              CrudField("supplier_id", "Dostawca", "select", choices=supplier_choices)],
             [("Alias", lambda a: a.alias), ("Jednostka", lambda a: a.unit.code),
              ("Dostawca", lambda a: a.supplier.name if a.supplier else "wszyscy")],
             lambda: UnitAlias.alias_norm, before_save=_alias_before_save),
    CrudSpec("conversions", UnitConversion, "Przeliczniki jednostek", "/przeliczniki",
             [CrudField("from_unit_id", "Z jednostki", "select", True, unit_choices),
              CrudField("factor", "Współczynnik (1 z = X do)", "number", True),
              CrudField("to_unit_id", "Na jednostkę", "select", True, unit_choices),
              CrudField("supplier_id", "Dostawca", "select", choices=supplier_choices),
              CrudField("product_id", "Towar", "select", choices=product_choices)],
             [("Przelicznik", lambda c: f"1 {c.from_unit.code} = {c.factor.normalize()} {c.to_unit.code}"),
              ("Dostawca", lambda c: c.supplier.name if c.supplier else "wszyscy"),
              ("Towar", lambda c: c.product.code if c.product else "wszystkie")],
             lambda: UnitConversion.id, before_save=_conversion_before_save),
]
for _spec in SPECS:
    register_crud(bp, _spec)

COLS = {"code": ("indeks", "code", "kod"), "name": ("nazwa", "name"), "gtin": ("gtin", "ean"),
        "unit": ("jednostka", "jm", "unit")}


MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ROWS = 20000


@bp.route("/towary/import", methods=["GET", "POST"])
@login_required
def import_products():
    report = None
    if request.method == "POST":
        f = request.files.get("file")
        raw = f.read(MAX_IMPORT_BYTES + 1) if f else b""
        if not raw:
            flash("Wybierz niepusty plik CSV.", "error")
            return render_template("products_import.html", report=None)
        if len(raw) > MAX_IMPORT_BYTES:
            flash(f"Plik jest za duży (maks. {MAX_IMPORT_BYTES // (1024 * 1024)} MB).", "error")
            return render_template("products_import.html", report=None)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1250", errors="replace")
        text = text.replace("\x00", "")
        try:
            delim = csv.Sniffer().sniff(text[:2048], delimiters=";,\t").delimiter
        except csv.Error:
            delim = ";"
        report = {"added": 0, "updated": 0, "errors": []}
        try:
            reader = csv.DictReader(io.StringIO(text), delimiter=delim)
            heads = {(h or "").strip().lower(): h for h in (reader.fieldnames or [])}
            col = {k: next((heads[a] for a in aliases if a in heads), None) for k, aliases in COLS.items()}
            if not col["code"] or not col["name"]:
                report["errors"].append("Brak kolumn „indeks” i „nazwa” w nagłówku.")
            else:
                _import_rows(reader, col, report)
        except csv.Error as exc:
            db.session.rollback()
            report["errors"].append(f"Nieprawidłowy plik CSV: {exc}")
        except IntegrityError:
            db.session.rollback()
            report["added"] = report["updated"] = 0
            report["errors"].append("Import przerwany: konflikt danych (duplikat). Nic nie zapisano.")
        flash(f"Dodano: {report['added']} · Zaktualizowano: {report['updated']} · Błędy: {len(report['errors'])}",
              "info")
    return render_template("products_import.html", report=report)


def _import_rows(reader, col, report):
    units = {u.code: u for u in Unit.query.all()}
    for n, row in enumerate(reader, start=2):
        if n > MAX_IMPORT_ROWS + 1:
            report["errors"].append(f"Przekroczono limit {MAX_IMPORT_ROWS} wierszy — reszta pominięta.")
            break
        code, name = (row.get(col["code"]) or "").strip(), (row.get(col["name"]) or "").strip()
        if not code or not name:
            continue
        if len(code) > 64 or len(name) > 255:
            report["errors"].append(f"Wiersz {n}: indeks (maks. 64) lub nazwa (maks. 255 znaków) za długie.")
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
    audit("import", "products", None, {"added": report["added"], "updated": report["updated"]})
    db.session.commit()
