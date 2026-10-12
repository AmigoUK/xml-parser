"""Serializacja dokumentu do JSON dla klientów API i panelu („Pokaż JSON”) — bez danych innych kluczy API ani
globalnej kartoteki (SEC-5)."""
from __future__ import annotations

from app.extensions import db
from app.ids import parse_id
from app.models import Document

from .timeutil import format_api_datetime

# Podpowiedzi zbudowane wyłącznie z treści samego dokumentu albo słowników globalnych (jednostki).
# Pozostałe (kandydaci-dostawcy, szablony do sklonowania, towary z kartoteki) ujawniałyby dane spoza
# klucza API, więc w API są wycinane (SEC-5). Nieznane rodzaje też — fail-closed.
API_SAFE_SUGGESTIONS = {"path", "line_path", "default", "unit", "conversion", "create_supplier", "create_product"}
FOREIGN_DUPLICATE_MESSAGE = "Ta faktura była już przetworzona (duplikat istniejącego dokumentu)."


def _duplicate_owned_by_other_key(issue: dict, api_key_id: int | None) -> bool:
    ref = parse_id(issue.get("source_value"))
    if ref is None:
        return True  # brak wskazania — traktuj ostrożnie
    other = db.session.get(Document, ref)
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
    """Dokument jako JSON API: nagłówek (`full=False` — pozycja listy) albo z wynikiem kanonicznym i problemami."""
    out = {
        "id": doc.id, "status": doc.status, "status_label": doc.status_label, "format": doc.fmt,
        "filename": doc.filename, "number": doc.number, "issue_date": doc.issue_date, "doc_type": doc.doc_type,
        "supplier": {"id": doc.supplier.id, "name": doc.supplier.name} if doc.supplier else None,
        "template_version": doc.template_version.version if doc.template_version else None,
        "created_at": format_api_datetime(doc.created_at),
        "updated_at": format_api_datetime(doc.updated_at),
        "issues_count": len(doc.issues or []),
    }
    if full:
        out["invoice"] = doc.result
        out["issues"] = api_issues(doc)
    return out
