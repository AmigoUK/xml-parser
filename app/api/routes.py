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


# Podpowiedzi zbudowane wyłącznie z treści samego dokumentu albo słowników globalnych (jednostki).
# Pozostałe (kandydaci-dostawcy, szablony do sklonowania, towary z kartoteki) ujawniałyby dane spoza
# klucza API, więc w API są wycinane (SEC-5). Nieznane rodzaje też — fail-closed.
API_SAFE_SUGGESTIONS = {"path", "line_path", "default", "unit", "conversion", "create_supplier", "create_product"}
FOREIGN_DUPLICATE_MESSAGE = "Ta faktura była już przetworzona (duplikat istniejącego dokumentu)."
LIST_DEFAULT_LIMIT = 100  # GET /documents: domyślna i maksymalna liczba wyników (opis w Pomocy i openapi.yaml)
LIST_MAX_LIMIT = 500


def _duplicate_owned_by_other_key(issue: dict, api_key_id: int | None) -> bool:
    ref = str(issue.get("source_value") or "")
    if not ref.isdigit():
        return True  # brak wskazania — traktuj ostrożnie
    other = db.session.get(Document, int(ref))
    return other is None or other.api_key_id != api_key_id


def api_issues(doc: Document) -> list[dict]:
    """Problemy dokumentu w wersji dla klienta API — bez danych innych kluczy i globalnej kartoteki."""
    out = []
    for issue in doc.issues or []:
        issue = dict(issue)
        if issue.get("code") == "duplicate" and _duplicate_owned_by_other_key(issue, doc.api_key_id):
            issue["message"], issue["source_value"] = FOREIGN_DUPLICATE_MESSAGE, None
        if issue.get("suggestions"):
            issue["suggestions"] = [s for s in issue["suggestions"]
                                    if isinstance(s, dict) and s.get("kind") in API_SAFE_SUGGESTIONS]
        out.append(issue)
    return out


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
        out["issues"] = api_issues(doc)
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
    q = Document.query.filter_by(api_key_id=g.api_key.id).order_by(Document.id.desc())
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
        limit = max(1, min(int(request.args.get("limit", LIST_DEFAULT_LIMIT)), LIST_MAX_LIMIT))
    except ValueError:
        return api_error("bad_request", "Parametr limit musi być liczbą całkowitą.", 400)
    return jsonify(items=[doc_to_json(d, full=False) for d in q.limit(limit)])


def _get_doc(doc_id: int):
    doc = db.session.get(Document, doc_id)
    return doc if doc is not None and doc.api_key_id == g.api_key.id else None


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
    if doc.is_manually_rejected:  # BE-2/EDGE-6: odrzucenie operatora cofa tylko „Przywróć” w panelu
        return api_error("rejected", "Dokument został odrzucony przez operatora — ponowne przetworzenie "
                                     "nie cofa odrzucenia.", 409)
    process(doc)
    db.session.commit()
    return jsonify(doc_to_json(doc))


@bp.get("/suppliers")
@require_api_key
def list_suppliers():
    # tylko dostawcy z dokumentów tego klucza — klucz nie widzi całej kartoteki (SEC-5)
    own = db.select(Document.supplier_id).where(Document.api_key_id == g.api_key.id,
                                                Document.supplier_id.isnot(None))
    q = Supplier.query.filter(Supplier.id.in_(own)).order_by(Supplier.name)
    return jsonify(items=[{"id": s.id, "name": s.name, "tax_id": s.tax_id} for s in q])


@bp.app_errorhandler(413)
def too_large(exc):
    if not request.path.startswith("/api/"):
        return exc
    limit = current_app.config["MAX_DOCUMENT_BYTES"] // (1024 * 1024)
    return api_error("too_large", f"Plik przekracza limit {limit} MB.", 413)


def _json_or_default(exc, code, message):
    if not request.path.startswith("/api/"):
        return exc
    return api_error(code, message, exc.code if hasattr(exc, "code") and exc.code else 500)


@bp.app_errorhandler(404)
def _not_found(exc):
    return _json_or_default(exc, "not_found", "Nie znaleziono zasobu.")


@bp.app_errorhandler(405)
def _method_not_allowed(exc):
    return _json_or_default(exc, "method_not_allowed", "Metoda niedozwolona dla tego adresu.")


@bp.app_errorhandler(500)
def _server_error(exc):
    if not request.path.startswith("/api/"):
        return exc
    return api_error("internal_error", "Wewnętrzny błąd serwera.", 500)
