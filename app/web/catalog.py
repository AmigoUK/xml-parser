"""Panel: kartoteka (CRUD słowników) i import CSV towarów — tylko widoki; reguły w app/services/catalog.py."""
from flask import Blueprint, flash, render_template, request
from flask_login import login_required

from app.engine.values import fmt_qty
from app.formatting import mib
from app.models import Product, ProductMapping, Supplier, Unit, UnitAlias, UnitConversion
from app.services.catalog import (  # noqa: F401 (MAX_* — re-eksport)
    MAX_IMPORT_BYTES,
    MAX_IMPORT_ROWS,
    alias_before_save,
    conversion_before_save,
    import_products_csv,
    mapping_before_save,
    product_before_save,
    product_delete_blocker,
    supplier_before_save,
    supplier_delete_blocker,
    unit_before_save,
    unit_delete_blocker,
)

from .crud import CrudField, CrudSpec, register_crud

bp = Blueprint("catalog", __name__)


def unit_choices():
    return [(u.id, f"{u.code} — {u.name}") for u in Unit.query.order_by(Unit.code)]


def supplier_choices():
    return [("", "— wszyscy dostawcy (globalnie) —")] + [(s.id, s.name) for s in Supplier.query.order_by(Supplier.name)]


def product_choices():
    products = Product.query.order_by(Product.code)
    return [("", "— wszystkie towary —")] + [(p.id, f"{p.code} — {p.name}") for p in products]


SPECS = [
    CrudSpec("suppliers", Supplier, "Dostawcy", "/dostawcy",
             [CrudField("name", "Nazwa", required=True), CrudField("tax_id", "NIP / VAT"),
              CrudField("notes", "Notatki", "textarea")],
             [("Nazwa", lambda s: s.name), ("NIP / VAT", lambda s: s.tax_id or "—"),
              ("Szablony", lambda s: len(s.templates))],
             lambda: Supplier.name, before_save=supplier_before_save, delete_blocker=supplier_delete_blocker),
    CrudSpec("products", Product, "Kartoteka towarów", "/towary",
             [CrudField("code", "Indeks", required=True), CrudField("name", "Nazwa", required=True),
              CrudField("gtin", "GTIN / EAN"),
              CrudField("unit_id", "Jednostka", "select", choices=lambda: [("", "—")] + unit_choices())],
             [("Indeks", lambda p: p.code), ("Nazwa", lambda p: p.name), ("GTIN", lambda p: p.gtin or "—"),
              ("JM", lambda p: p.unit.code if p.unit else "—")],
             lambda: Product.code, before_save=product_before_save, delete_blocker=product_delete_blocker,
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
             lambda: ProductMapping.id, before_save=mapping_before_save),
    CrudSpec("units", Unit, "Jednostki miary", "/jednostki",
             [CrudField("code", "Kod", required=True), CrudField("name", "Nazwa", required=True),
              CrudField("is_base", "Jednostka bazowa (bez przelicznika)", "checkbox")],
             [("Kod", lambda u: u.code), ("Nazwa", lambda u: u.name),
              ("Bazowa", lambda u: "tak" if u.is_base else "nie")],
             lambda: Unit.code, before_save=unit_before_save, delete_blocker=unit_delete_blocker),
    CrudSpec("aliases", UnitAlias, "Aliasy jednostek", "/aliasy-jednostek",
             [CrudField("alias", "Jednostka w pliku dostawcy", required=True),
              CrudField("unit_id", "Nasza jednostka", "select", True, unit_choices),
              CrudField("supplier_id", "Dostawca", "select", choices=supplier_choices)],
             [("Alias", lambda a: a.alias), ("Jednostka", lambda a: a.unit.code),
              ("Dostawca", lambda a: a.supplier.name if a.supplier else "wszyscy")],
             lambda: UnitAlias.alias_norm, before_save=alias_before_save),
    CrudSpec("conversions", UnitConversion, "Przeliczniki jednostek", "/przeliczniki",
             [CrudField("from_unit_id", "Z jednostki", "select", True, unit_choices),
              CrudField("factor", "Współczynnik (1 z = X do)", "number", True),
              CrudField("to_unit_id", "Na jednostkę", "select", True, unit_choices),
              CrudField("supplier_id", "Dostawca", "select", choices=supplier_choices),
              CrudField("product_id", "Towar", "select", choices=product_choices)],
             [("Przelicznik", lambda c: f"1 {c.from_unit.code} = {fmt_qty(c.factor)} {c.to_unit.code}"),
              ("Dostawca", lambda c: c.supplier.name if c.supplier else "wszyscy"),
              ("Towar", lambda c: c.product.code if c.product else "wszystkie")],
             lambda: UnitConversion.id, before_save=conversion_before_save),
]
for _spec in SPECS:
    register_crud(bp, _spec)


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
            flash(f"Plik jest za duży (maks. {mib(MAX_IMPORT_BYTES)} MB).", "error")
            return render_template("products_import.html", report=None)
        report = import_products_csv(raw)
        flash(f"Dodano: {report['added']} · Zaktualizowano: {report['updated']} · Błędy: {len(report['errors'])}",
              "info")
    return render_template("products_import.html", report=report)
