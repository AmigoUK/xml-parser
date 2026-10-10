import io
import re

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request,
                   send_file, url_for)
from flask_login import current_user, login_required

from app.engine.canonical import FIELD_LABELS, HEADER_FIELDS, LINE_FIELDS
from app.extensions import db
from app.ingest import ReaderError
from app.models import STATUS_LABELS, STATUS_NEEDS_REVIEW, Document, Product, Supplier, Unit
from app.services.negotiation import NegotiationError, resolve
from app.services.pipeline import DocumentTooLarge, ingest, load_tree, process
from app.services.storage import get_storage

bp = Blueprint("docs", __name__)

ALWAYS_REMEMBER = {"create_supplier", "use_supplier", "add_conversion", "allow_duplicate", "reject"}
FORM_FIELDS = ("name", "tax_id", "supplier_id", "alias", "unit", "from_unit", "to_unit", "factor", "scope",
               "line_no", "product_code", "code")


def form_to_action(doc: Document, form) -> tuple[str, dict, bool]:
    action = form.get("action", "")
    remember = action in ALWAYS_REMEMBER or form.get("remember") == "1"
    if action == "map_field":
        issue = (doc.issues or [])[int(form.get("issue", 0))]
        fld, choice = issue["field"], form.get("choice", "")
        if choice.startswith("s"):
            s = issue["suggestions"][int(choice[1:])]
            data = ({"field": fld, "path": s["path"], "transforms": s.get("transforms") or []}
                    if s["kind"] in ("path", "line_path") else {"field": fld, "value": s["value"]})
        elif choice == "manual_path":
            data = {"field": fld, "path": form.get("manual_path")}
        else:
            data = {"field": fld, "value": form.get("value")}
        return action, data, remember
    return action, {k: form.get(k) for k in FORM_FIELDS if form.get(k) not in (None, "")}, remember


def _get(doc_id: int) -> Document:
    doc = db.session.get(Document, doc_id)
    if not doc:
        abort(404)
    return doc


@bp.get("/")
def index():
    if current_app.config["DEMO_MODE"] and "demo" in current_app.blueprints:
        return redirect(url_for("demo.index"))
    return redirect(url_for("docs.dashboard"))


@bp.get("/pulpit")
@login_required
def dashboard():
    counts = {s: Document.query.filter_by(status=s).count() for s in STATUS_LABELS}
    recent = Document.query.order_by(Document.id.desc()).limit(10).all()
    return render_template("dashboard.html", counts=counts, docs=recent, labels=STATUS_LABELS)


@bp.route("/wgraj", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        f = request.files.get("file")
        data = f.read() if f else b""
        if not data.strip():
            flash("Wybierz niepusty plik faktury (XML, JSON lub CSV).", "error")
            return redirect(url_for("docs.upload"))
        try:
            doc = ingest(data, f.filename, source="upload")
        except DocumentTooLarge as exc:
            flash(str(exc), "error")
            return redirect(url_for("docs.upload"))
        return redirect(url_for("docs.detail", doc_id=doc.id))
    return render_template("upload.html")


@bp.get("/kolejka")
@login_required
def queue():
    docs = Document.query.filter_by(status=STATUS_NEEDS_REVIEW).order_by(Document.id).all()
    return render_template("documents.html", docs=docs, title="Kolejka do wyjaśnienia", queue=True)


@bp.get("/dokumenty")
@login_required
def documents():
    q = Document.query.order_by(Document.id.desc())
    status = request.args.get("status")
    if status in STATUS_LABELS:
        q = q.filter_by(status=status)
    return render_template("documents.html", docs=q.limit(200).all(), title="Dokumenty", queue=False,
                           labels=STATUS_LABELS, current=status)


@bp.get("/dokumenty/<int:doc_id>")
@login_required
def detail(doc_id):
    doc = _get(doc_id)
    try:
        rows = load_tree(doc).display_rows()
    except (ReaderError, OSError):
        rows = []
    return render_template(
        "document.html", doc=doc, rows=rows, field_labels=FIELD_LABELS,
        header_fields=HEADER_FIELDS, line_fields=LINE_FIELDS,
        leaf_paths=[r["path"] for r in rows if r["value"]],
        units=Unit.query.order_by(Unit.code).all(),
        products=Product.query.order_by(Product.code).all(),
        suppliers=Supplier.query.order_by(Supplier.name).all())


@bp.post("/dokumenty/<int:doc_id>/rozwiaz")
@login_required
def resolve_issue(doc_id):
    doc = _get(doc_id)
    try:
        action, data, remember = form_to_action(doc, request.form)
    except (ValueError, IndexError, KeyError):
        flash("Nieprawidłowe dane formularza.", "error")
        return redirect(url_for("docs.detail", doc_id=doc_id))
    code_taken = (action == "create_product" and data.get("code")
                  and Product.query.filter_by(code=data["code"]).first() is not None)
    try:
        resolve(doc, action, data, remember, current_user.email)
    except NegotiationError as exc:
        flash(str(exc) or "Nie udało się zastosować zmiany.", "error")
    else:
        flash("Zapisano. Dokument przetworzono ponownie.", "success")
        if code_taken:
            flash(f"Indeks „{data['code']}” był już zajęty — nowemu towarowi nadano kolejny wolny indeks.", "info")
    return redirect(url_for("docs.detail", doc_id=doc_id))


@bp.post("/dokumenty/<int:doc_id>/ponownie")
@login_required
def reprocess(doc_id):
    doc = _get(doc_id)
    process(doc)
    db.session.commit()
    flash("Przetworzono ponownie aktywną wersją szablonu.", "success")
    return redirect(url_for("docs.detail", doc_id=doc_id))


@bp.get("/dokumenty/<int:doc_id>/plik")
@login_required
def raw(doc_id):
    doc = _get(doc_id)
    mime = {"xml": "application/xml", "json": "application/json", "csv": "text/csv"}.get(doc.fmt,
                                                                                          "application/octet-stream")
    resp = send_file(io.BytesIO(get_storage().load(doc.sha256)), mimetype=mime, as_attachment=True,
                     download_name=re.sub(r"[\x00-\x1f\x7f]", "", doc.filename or "") or "dokument")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@bp.get("/dokumenty/<int:doc_id>/json")
@login_required
def as_json(doc_id):
    from app.api.routes import doc_to_json
    return jsonify(doc_to_json(_get(doc_id)))
