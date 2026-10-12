from functools import wraps

from flask import current_app, flash, g, jsonify, redirect, render_template, request, url_for
from flask_wtf.csrf import CSRFError
from sqlalchemy import and_, or_
from sqlalchemy.orm import defer
from werkzeug.exceptions import NotFound

from app.extensions import db
from app.models import STATUS_LABELS, Document, Supplier
from app.services.apikeys import verify_key
from app.services.pipeline import DocumentTooLarge, StorageUnavailable, ingest, process

from . import bp
from .cursor import decode_cursor, encode_cursor
from .serializers import API_SAFE_SUGGESTIONS, FOREIGN_DUPLICATE_MESSAGE, api_issues, doc_to_json  # noqa: F401 (re-eksport)
from .timeutil import parse_api_datetime


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


LIST_DEFAULT_LIMIT = 100  # GET /documents: domyślna i maksymalna liczba wyników (opis w Pomocy i openapi.yaml)
LIST_MAX_LIMIT = 500
# GET /documents nie zwraca wyniku ani danych roboczych — lista ich nie czyta z bazy. `issues` zostaje: z niego
# liczone jest `issues_count` (odroczone dawałoby osobne zapytanie na każdy dokument).
LIST_DEFERRED_COLUMNS = (Document.result, Document.overrides, Document.draft_rules, Document.error)


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
    except StorageUnavailable as exc:  # pełny dysk / utracony wolumen: klient ma ponowić później
        return api_error("storage_unavailable", str(exc), 503)
    return jsonify(doc_to_json(doc)), 201


def _bad_time_param(name: str):
    """400 dla parametru czasu (since, updated_since) w złym formacie — ta sama podpowiedź dla obu. Zdanie o dacie ze
    strefą jest dla poprawnie zakodowanego `2026-10-11%2B02:00`, któremu sama wskazówka o %2B nic nie mówi."""
    return api_error("bad_request", f"Parametr {name} musi być datą ISO 8601 (np. 2026-10-11 lub "
                                    "2026-10-11T06:00:00Z). Data ze strefą musi zawierać godzinę: "
                                    "2026-10-11T00:00:00+02:00. Znak „+” w adresie URL zapisz jako %2B.", 400)


@bp.get("/documents")
@require_api_key
def list_documents():
    q = (Document.query.filter_by(api_key_id=g.api_key.id)  # zakres zawsze z klucza w nagłówku, nigdy z kursora
         .options(*(defer(column) for column in LIST_DEFERRED_COLUMNS)))
    status = request.args.get("status")
    if status:
        if status not in STATUS_LABELS:
            return api_error("bad_request", f"Nieznany status „{status}”.", 400)
        q = q.filter_by(status=status)
    since = request.args.get("since")
    if since:
        try:
            since_utc = parse_api_datetime(since)  # strefa → UTC; bez strefy = UTC (jak czas w bazie)
        except ValueError:
            return _bad_time_param("since")
        q = q.filter(Document.created_at >= since_utc)
    try:
        limit = max(1, min(int(request.args.get("limit", LIST_DEFAULT_LIMIT)), LIST_MAX_LIMIT))
    except ValueError:
        return api_error("bad_request", "Parametr limit musi być liczbą całkowitą.", 400)
    updated_since, cursor = request.args.get("updated_since"), request.args.get("cursor")
    # pusta wartość to błąd, nie brak parametru: dałaby cicho tryb zwykły (jedna strona od najnowszych, bez
    # next_cursor), a klient przesunąłby last_sync i pominął starsze zmiany (pusty status= i since= — jak dotąd)
    if updated_since == "":
        return api_error("bad_request", "Parametr updated_since nie może być pusty — pełną synchronizację zacznij "
                                        "od updated_since=1970-01-01T00:00:00Z.", 400)
    if cursor == "":
        return api_error("bad_request", "Parametr cursor nie może być pusty — pomiń go na pierwszej stronie albo "
                                        "podaj next_cursor z poprzedniej odpowiedzi.", 400)
    if updated_since is not None or cursor is not None:
        return _sync_page(q, limit, updated_since, cursor)
    # tryb dotychczasowy: od najnowszych, bez next_cursor (zgodność z klientami sprzed v0.5.0)
    return jsonify(items=[doc_to_json(d, full=False) for d in q.order_by(Document.id.desc()).limit(limit)])


def _sync_page(q, limit: int, updated_since: str | None, cursor: str | None):
    """Tryb synchronizacji listy: rosnąco po (updated_at, id) od pozycji kursora; `next_cursor` wskazuje ostatni
    element strony, gdy są dalsze (inaczej null). Dostawa „co najmniej raz”: dokument zmieniony w trakcie
    stronicowania wraca na dalszej stronie z nowym updated_at. Dokumenty bez updated_at (tylko dane wstawione
    ręcznie) nie spełniają żadnego z warunków, więc tu nie występują."""
    if updated_since is not None:
        try:
            updated_since_utc = parse_api_datetime(updated_since)
        except ValueError:
            return _bad_time_param("updated_since")
        q = q.filter(Document.updated_at >= updated_since_utc)
    if cursor is not None:
        try:
            after_at, after_id = decode_cursor(cursor)
        except ValueError:
            return api_error("bad_request", "Nieprawidłowy kursor — użyj wartości next_cursor z poprzedniej "
                                            "odpowiedzi.", 400)
        # warunek keyset jawnie, bez porównania krotek — tak samo na SQLite i MariaDB
        q = q.filter(or_(Document.updated_at > after_at,
                         and_(Document.updated_at == after_at, Document.id > after_id)))
    rows = q.order_by(Document.updated_at.asc(), Document.id.asc()).limit(limit + 1).all()
    page = rows[:limit]
    next_cursor = encode_cursor(page[-1].updated_at, page[-1].id) if len(rows) > limit else None
    return jsonify(items=[doc_to_json(d, full=False) for d in page], next_cursor=next_cursor)


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


def _is_api() -> bool:
    return request.path.startswith("/api/")


def _panel_error(code: int, title: str, message: str):
    """Polska strona błędu panelu (rozszerza base.html, więc z nawigacją i stopką). Nigdy nie ujawnia treści wyjątku;
    gdy sam render zawiedzie (np. zepsuta sesja bazy), zwraca prosty tekst."""
    try:
        return render_template("errors/error.html", code=code, title=title, message=message), code
    except Exception:  # noqa: BLE001 — ostatnia deska ratunku, nie wolno zgłosić kolejnego 500
        current_app.logger.exception("Nie udało się wyrenderować strony błędu %s — zwracam zwykły tekst.", code)
        return f"{title}\n{message}\n", code, {"Content-Type": "text/plain; charset=utf-8"}


@bp.app_errorhandler(400)
def _bad_request(exc):
    if _is_api():
        return exc  # zachowanie API bez zmian
    return _panel_error(400, "Nieprawidłowe żądanie",
                        "Nie udało się odczytać żądania. Odśwież stronę i spróbuj ponownie.")


@bp.app_errorhandler(CSRFError)
def _csrf_error(exc):
    """Token formularza wygasa po godzinie (WTF_CSRF_TIME_LIMIT), krócej niż sesja — zamiast angielskiej strony 400."""
    if _is_api():
        return exc
    return _panel_error(400, "Formularz wygasł lub jest nieprawidłowy", "Odśwież stronę i spróbuj ponownie.")


@bp.app_errorhandler(403)
def _forbidden(exc):
    if _is_api():
        return exc  # zachowanie API bez zmian
    return _panel_error(403, "Brak uprawnień", "Ta akcja jest dostępna tylko dla administratora.")


@bp.app_errorhandler(413)
def too_large(exc):
    limit = current_app.config["MAX_DOCUMENT_BYTES"] // (1024 * 1024)
    if _is_api():
        return api_error("too_large", f"Plik przekracza limit {limit} MiB.", 413)
    message = f"Plik jest za duży (maks. {limit} MiB)."
    if request.endpoint in ("docs.upload", "catalog.import_products"):
        flash(message, "error")
        return redirect(url_for(request.endpoint))
    return _panel_error(413, "Plik jest za duży", message)


@bp.app_errorhandler(404)
def _not_found(exc):
    if _is_api():
        return api_error("not_found", "Nie znaleziono zasobu.", 404)
    return _panel_error(404, "Nie znaleziono strony", "Adres jest nieprawidłowy albo zasób już nie istnieje.")


@bp.app_errorhandler(405)
def _method_not_allowed(exc):
    if _is_api():
        return api_error("method_not_allowed", "Metoda niedozwolona dla tego adresu.", 405)
    return _panel_error(405, "Metoda niedozwolona", "Ten adres nie obsługuje tej metody żądania.")


@bp.app_errorhandler(OverflowError)
def _overflow(exc):
    """Siatka bezpieczeństwa: liczba ponad zakres kolumny związana w zapytaniu (SQLite rzuca surowy
    OverflowError, nieopakowany przez SQLAlchemy) to błąd wejścia, nie awaria — 400 w API, 404 w panelu."""
    if _is_api():
        return api_error("bad_request", "Identyfikator poza dopuszczalnym zakresem.", 400)
    return _not_found(NotFound())


@bp.app_errorhandler(500)
def _server_error(exc):
    if _is_api():
        return api_error("internal_error", "Wewnętrzny błąd serwera.", 500)
    try:
        db.session.rollback()  # sesja po wyjątku bywa w stanie przerwanej transakcji
    except Exception:  # noqa: BLE001
        current_app.logger.warning("Nie udało się wycofać transakcji po błędzie 500.", exc_info=True)
    return _panel_error(500, "Błąd serwera", "Coś poszło nie tak po naszej stronie. Spróbuj ponownie za chwilę.")
