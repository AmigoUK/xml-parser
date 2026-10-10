from datetime import datetime
from functools import wraps

from flask import current_app, g, jsonify, request

from app.extensions import db
from app.models import STATUS_LABELS, Document, Supplier
from app.services.apikeys import verify_key
from app.services.pipeline import DocumentTooLarge, ingest, process

from . import bp


def api_error(code: str, message: str, status: int):
    return jsonify(error={"code": code, "message": message}), status


def require_api_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        key = verify_key(request.headers.get("X-API-Key"))
        if key is None:
            return api_error("unauthorized", "Brak lub nieprawidłowy klucz API (nagłówek X-API-Key).", 401)
        g.api_key = key
        db.session.commit()
        return fn(*args, **kwargs)
    return wrapper


def doc_to_json(doc: Document, full: bool = True) -> dict:
    out = {
        "id": doc.id, "status": doc.status, "status_label": doc.status_label, "format": doc.fmt,
        "filename": doc.filename, "number": doc.number, "issue_date": doc.issue_date, "doc_type": doc.doc_type,
        "supplier": {"id": doc.supplier.id, "name": doc.supplier.name} if doc.supplier else None,
        "template_version": doc.template_version.version if doc.template_version else None,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "issues_count": len(doc.issues or []),
    }
    if full:
        out["invoice"] = doc.result
        out["issues"] = doc.issues or []
    return out


@bp.post("/documents")
@require_api_key
def create_document():
    if "file" in request.files:
        f = request.files["file"]
        data, filename = f.read(), f.filename
    else:
        data, filename = request.get_data(), request.headers.get("X-Filename", "dokument")
    if not data or not data.strip():
        return api_error("empty_body", "Pusty plik — wyślij fakturę jako multipart 'file' lub surowe body.", 400)
    try:
        doc = ingest(data, filename, source="api", api_key_id=g.api_key.id)
    except DocumentTooLarge as exc:
        return api_error("too_large", str(exc), 413)
    return jsonify(doc_to_json(doc)), 201


@bp.get("/documents")
@require_api_key
def list_documents():
    q = Document.query.order_by(Document.id.desc())
    status = request.args.get("status")
    if status:
        if status not in STATUS_LABELS:
            return api_error("bad_request", f"Nieznany status „{status}”.", 400)
        q = q.filter_by(status=status)
    since = request.args.get("since")
    if since:
        try:
            q = q.filter(Document.created_at >= datetime.fromisoformat(since))
        except ValueError:
            return api_error("bad_request", "Parametr since musi być datą ISO 8601.", 400)
    try:
        limit = max(1, min(int(request.args.get("limit", 100)), 500))
    except ValueError:
        return api_error("bad_request", "Parametr limit musi być liczbą całkowitą.", 400)
    return jsonify(items=[doc_to_json(d, full=False) for d in q.limit(limit)])


def _get_doc(doc_id: int):
    return db.session.get(Document, doc_id)


@bp.get("/documents/<int:doc_id>")
@require_api_key
def get_document(doc_id):
    doc = _get_doc(doc_id)
    if not doc:
        return api_error("not_found", "Nie znaleziono dokumentu.", 404)
    return jsonify(doc_to_json(doc))


@bp.post("/documents/<int:doc_id>/reprocess")
@require_api_key
def reprocess_document(doc_id):
    doc = _get_doc(doc_id)
    if not doc:
        return api_error("not_found", "Nie znaleziono dokumentu.", 404)
    process(doc)
    db.session.commit()
    return jsonify(doc_to_json(doc))


@bp.get("/suppliers")
@require_api_key
def list_suppliers():
    return jsonify(items=[{"id": s.id, "name": s.name, "tax_id": s.tax_id}
                          for s in Supplier.query.order_by(Supplier.name)])


@bp.app_errorhandler(413)
def too_large(exc):
    if not request.path.startswith("/api/"):
        return exc
    limit = current_app.config["MAX_DOCUMENT_BYTES"] // (1024 * 1024)
    return api_error("too_large", f"Plik przekracza limit {limit} MB.", 413)
