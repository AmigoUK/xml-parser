"""Przetwarzanie dokumentu: odczyt → identyfikacja → szablon → walidacja → status → podpowiedzi."""
from __future__ import annotations

import copy
from dataclasses import dataclass

from flask import current_app
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.engine.canonical import LINE_KEYS, get_path
from app.engine.issues import BLOCKING, Issue, aggregate_line_issues, has_blocking
from app.engine.suggest import (FIELDS_BY_KEY, conversion_guess, decimal_sep_candidates, draft_rules, field_candidates, learned_pairs,
                                load_synonyms, product_candidates, suffix_match, supplier_candidates,
                                tax_ids_match, unit_candidates)
from app.engine.template import apply_template
from app.engine.tree import SourceTree, jaccard
from app.engine.validate import validate_invoice
from app.extensions import db
from app.ingest import ReaderError, read_document
from app.engine.keys import dedupe_scope, document_key
from app.models import (LIVE_STATUSES, STATUS_APPROVED, STATUS_DUPLICATE, STATUS_NEEDS_REVIEW, STATUS_RECEIVED,
                        STATUS_REJECTED, Document, Product, Supplier, Template, utcnow)
from app.services.audit import audit
from app.services.lookups_db import DbLookups
from app.services.storage import get_storage
from app.services.templates import active_rule_sets

FINGERPRINT_MIN = 0.6
FILE_MISSING_MSG = ("Brak pliku źródłowego dokumentu w magazynie plików — wgraj fakturę ponownie albo odtwórz "
                    "storage.")
STORAGE_UNAVAILABLE_MSG = ("Magazyn plików jest niedostępny (błąd zapisu) — spróbuj ponownie za chwilę albo "
                           "zgłoś problem administratorowi.")
DEFAULT_VALUES = {"currency": ["PLN", "GBP", "EUR"], "payment_method": ["przelew", "gotówka", "karta"]}


class DocumentTooLarge(ValueError):
    pass


class StorageUnavailable(RuntimeError):
    """Zapis pliku w magazynie nie powiódł się (pełny dysk, utracony wolumen, brak uprawnień) — API 503,
    panel: komunikat; szczegóły w logu."""


@dataclass
class Identification:
    supplier: Supplier | None = None
    template: Template | None = None
    clone_candidate: Template | None = None
    extracted_tax_id: str | None = None


def load_tree(doc: Document) -> SourceTree:
    return read_document(get_storage().load(doc.sha256), doc.filename)


def best_template_for(supplier_id: int | None, paths: set[str]) -> Template | None:
    q = Template.query
    q = q.filter_by(supplier_id=supplier_id) if supplier_id else q
    best, score = None, 0.0
    for t in q.all():
        j = jaccard(paths, set(t.paths or []))
        if j > score:
            best, score = t, j
    return best if score >= FINGERPRINT_MIN else None


def _tax_paths(tree: SourceTree, synonyms: dict) -> list[str]:
    paths = []
    for rules in active_rule_sets():
        p = (((rules.get("header") or {}).get("supplier.tax_id")) or {}).get("path")
        if p:
            paths.append(p)
    syns = synonyms["header"]["supplier.tax_id"]
    paths += [p for p in tree.leaf_paths() if any(suffix_match(p, s) for s in syns)]
    return paths


def identify(tree: SourceTree, doc: Document, synonyms: dict) -> Identification:
    ident = Identification()
    if doc.supplier_id:
        ident.supplier = db.session.get(Supplier, doc.supplier_id)
    else:
        suppliers = Supplier.query.filter(Supplier.tax_id.isnot(None)).order_by(Supplier.id).all()  # BE-11
        for p in _tax_paths(tree, synonyms):
            val = tree.first(p)
            if not val:
                continue
            ident.extracted_tax_id = ident.extracted_tax_id or val
            ident.supplier = next((s for s in suppliers if tax_ids_match(val, s.tax_id)), None)
            if ident.supplier:
                break
    paths = tree.path_set()
    if ident.supplier:
        ident.template = best_template_for(ident.supplier.id, paths)
    else:
        ident.clone_candidate = best_template_for(None, paths)
    return ident


def current_rules(doc: Document) -> dict:
    if doc.template_id:
        tpl = db.session.get(Template, doc.template_id)
        if tpl and tpl.active_version:
            return copy.deepcopy(tpl.active_version.rules)
    return copy.deepcopy(doc.draft_rules or {})


def next_product_code() -> str:
    n = Product.query.count() + 1
    while Product.query.filter_by(code=f"TOW-{n:04d}").first():
        n += 1
    return f"TOW-{n:04d}"


def _stored_number(invoice: dict) -> str | None:
    """Numer w postaci zapisywanej w bazie (bez białych znaków na brzegach, obcięty do kolumny)."""
    raw = invoice.get("number")
    if raw is None:
        return None
    return _fit(Document.number, str(raw).strip()) or None


# Duplikat równoległego przyjęcia, którego oryginał nie był jeszcze widoczny (wyścig rozstrzygnięty przez UNIQUE)
_CONCURRENT = object()


def same_scope(doc: Document):
    """Warunek SQL: ten sam zakres duplikatów co `doc` (ten sam klucz API albo panel)."""
    return (Document.api_key_id.is_(None) if doc.api_key_id is None
            else Document.api_key_id == doc.api_key_id)


def _earlier_same_file(doc: Document) -> Document | None:
    """Wcześniej przyjęty (niższe id), żywy dokument z tym samym plikiem — w tym samym zakresie."""
    return (Document.query.filter(Document.id < doc.id, Document.status.in_(LIVE_STATUSES),
                                  Document.sha256 == doc.sha256, same_scope(doc)).order_by(Document.id).first())


def _key_holder(doc: Document, key: str, lock: bool = False) -> Document | None:
    """Żywy dokument trzymający klucz faktury. `lock` — odczyt blokujący: w MariaDB (REPEATABLE READ) widzi
    wiersz zatwierdzony przez równoległą transakcję po starcie naszej."""
    q = Document.query.filter(Document.dedupe_key == key, Document.id != doc.id)
    if lock:
        q = q.with_for_update(read=True)
    with db.session.no_autoflush:
        return q.first()


def _claim_key(doc: Document, key: str):
    """Przejmuje klucz faktury dla `doc` albo zwraca dokument, którego `doc` jest duplikatem (BE-1).

    Zwraca (oryginał | _CONCURRENT | None, zdegradowana_późniejsza_kopia | None). Oryginałem jest zawsze żywy
    dokument z niższym id (BE-5) — późniejsza żywa kopia oddaje klucz i jest przeliczana jako duplikat."""
    holder = _key_holder(doc, key)
    if holder is not None and holder.id < doc.id:
        return holder, None
    demoted = None
    if holder is not None:  # późniejsza kopia była żywa (np. oryginał przetworzony po niej) — oddaje klucz
        holder.dedupe_key = None
        db.session.flush()
        demoted = holder
    if doc.dedupe_key == key:
        return None, demoted
    try:
        with db.session.begin_nested():
            doc.dedupe_key = key
            db.session.flush()
    except IntegrityError:
        # równoległe przyjęcie tej samej faktury zdążyło przed nami — UNIQUE rozstrzyga wyścig (EDGE-17)
        return _key_holder(doc, key, lock=True) or _CONCURRENT, demoted
    return None, demoted


def _resolve_duplicate(doc: Document, invoice: dict):
    """Ustala oryginał (duplikat) i klucz faktury dokumentu. Zwraca (oryginał | _CONCURRENT | None, zdegradowany)."""
    # zakres = klucz API dokumentu albo panel: cudzy klucz nie może zablokować ani zdegradować dokumentu
    doc.dedupe_hash = document_key(doc.supplier_id, invoice.get("doc_type"), invoice.get("number"),
                                   dedupe_scope(doc.api_key_id))
    if (doc.overrides or {}).get("allow_duplicate"):  # jawna zgoda operatora — dokument nie trzyma klucza
        doc.dedupe_key = None
        return None, None
    same = _earlier_same_file(doc)
    if same is not None:
        return same, None
    if not doc.dedupe_hash:
        doc.dedupe_key = None
        return None, None
    return _claim_key(doc, doc.dedupe_hash)


def _enrich(issues: list[Issue], tree: SourceTree, rules: dict, inv: dict, synonyms: dict,
            ident: Identification, lookups: DbLookups) -> None:
    learned = learned_pairs(active_rule_sets())
    line_path = rules.get("line_path")
    products = None
    new_code = None  # wolny indeks liczony raz, nie dla każdej pozycji (EDGE-5)
    for issue in issues:
        code = issue.code
        if code == "unknown_supplier":
            name, tax = get_path(inv, "supplier.name"), get_path(inv, "supplier.tax_id") or ident.extracted_tax_id
            sug = []
            if name or tax:
                sug.append({"kind": "create_supplier", "name": name or tax, "tax_id": tax, "confidence": 0.9,
                            "reason": "dane odczytane z faktury"})
            sug += supplier_candidates(name, tax, lookups.suppliers_brief())
            if ident.clone_candidate:
                sug.append({"kind": "clone_template", "template_id": ident.clone_candidate.id,
                            "name": ident.clone_candidate.name, "confidence": 0.8,
                            "reason": "zgodna struktura pliku — reguły zostaną skopiowane"})
            issue.suggestions = sug
        elif code in ("unmapped_field", "transform_error", "invalid_value") and issue.field:
            if issue.field == "line_path":
                issue.suggestions = [{"kind": "line_path", "path": p, "confidence": 0.5,
                                      "reason": "element z elementami podrzędnymi"} for p in tree.group_paths()[:15]]
            elif issue.field in FIELDS_BY_KEY:
                cands = [c.to_dict() for c in field_candidates(tree, issue.field, line_path, synonyms, learned)]
                issue.suggestions = cands + [{"kind": "default", "value": v, "confidence": 0.5,
                                              "reason": "typowa wartość"} for v in DEFAULT_VALUES.get(issue.field, [])]
        elif code == "ambiguous_number" and issue.field:
            rule = (rules.get("lines" if issue.field in LINE_KEYS else "header") or {}).get(issue.field)
            issue.suggestions = decimal_sep_candidates(rule, issue.source_path, issue.source_value)
        elif code == "unknown_unit":
            issue.suggestions = unit_candidates(issue.source_value or "", lookups.unit_codes(), synonyms)
        elif code == "unmapped_product" and issue.line_no:
            line = inv["lines"][issue.line_no - 1]
            products = products if products is not None else lookups.products_brief()
            new_code = new_code or next_product_code()
            issue.suggestions = product_candidates(line, products) + [{
                "kind": "create_product", "code": new_code, "name": line.get("name"),
                "unit": line.get("unit"), "confidence": 0.3, "reason": "nowy towar w kartotece"}]
        elif code == "missing_conversion" and issue.line_no:
            line = inv["lines"][issue.line_no - 1]
            issue.suggestions = [conversion_guess(line.get("name"), issue.source_value or "")]


def _fit(column, value):
    """Obcina wartość do długości kolumny (MariaDB w trybie strict odrzuca dłuższe)."""
    if value is None:
        return None
    return str(value)[:column.type.length]


def _too_many_lines(tree: SourceTree, rules: dict | None) -> str | None:
    """Limit liczby pozycji (SEC-1) — komunikat odrzucenia albo None."""
    line_path = (rules or {}).get("line_path")
    limit = int(current_app.config.get("MAX_LINES", 5000))
    if not line_path:
        return None
    count = len(tree.nodes_at(line_path))
    if count <= limit:
        return None
    return (f"Faktura ma zbyt wiele pozycji ({count}, limit {limit}) — podziel ją na mniejsze pliki "
            "albo poproś administratora o podniesienie limitu MAX_LINES.")


def _error_status(doc: Document) -> str:
    """Status po błędzie przetwarzania: duplikat zostaje duplikatem (nie staje się „żywy” bez klucza)."""
    return STATUS_DUPLICATE if doc.status == STATUS_DUPLICATE else STATUS_NEEDS_REVIEW


def touch(doc: Document) -> Document:
    """Jawnie odświeża `updated_at` — `onupdate` nie widzi mutacji JSON w miejscu ani zmian bez flush."""
    doc.updated_at = utcnow()
    return doc


def process(doc: Document) -> Document:
    """Przetwarza dokument. Jedyny punkt wejścia — każda ścieżka (API, panel, negocjacja, edytor) przechodzi
    przez straż ręcznego odrzucenia (BE-2) i obsługę błędów (BE-9/BE-10). Każde przetworzenie odświeża
    `updated_at` (`touch`), także gdy wynik jest identyczny; ręcznie odrzucony dokument zostaje nietknięty."""
    if doc.is_manually_rejected:  # cofa je tylko jawne „Przywróć” (negotiation.restore)
        return doc
    try:
        return touch(_process(doc))
    except SQLAlchemyError:
        raise  # błąd bazy — transakcja do wycofania przez wywołującego
    except Exception as exc:  # noqa: BLE001 - np. zepsuta reguła szablonu; dokument nie może zginąć (BE-10)
        current_app.logger.exception("Błąd przetwarzania dokumentu #%s", doc.id)
        msg = (f"Wewnętrzny błąd przetwarzania ({type(exc).__name__}) — dokument zapisano do wyjaśnienia; "
               "sprawdź reguły szablonu albo zgłoś problem administratorowi.")
        doc.status, doc.error = _error_status(doc), msg
        doc.issues = [Issue("internal_error", BLOCKING, msg).to_dict()]
        return touch(doc)


def _process(doc: Document) -> Document:
    synonyms = load_synonyms()
    try:
        tree = load_tree(doc)
    except ReaderError as exc:
        doc.status, doc.error, doc.result = STATUS_REJECTED, str(exc), None
        doc.issues = [Issue("unreadable", BLOCKING, str(exc)).to_dict()]
        return doc
    except OSError:  # brak pliku w storage (utracony wolumen, zła ścieżka) — czytelny problem, nie 500 (BE-9)
        doc.status, doc.error = _error_status(doc), FILE_MISSING_MSG
        doc.issues = [Issue("file_missing", BLOCKING, FILE_MISSING_MSG).to_dict()]
        return doc
    doc.fmt, doc.error = tree.fmt, None
    ident = identify(tree, doc, synonyms)
    version = ident.template.active_version if ident.template else None
    if version:
        rules = version.rules
        doc.template_id, doc.template_version_id, doc.draft_rules = ident.template.id, version.id, None
    else:
        doc.template_id = doc.template_version_id = None
        if not doc.draft_rules:
            base = ident.clone_candidate.active_version if ident.clone_candidate else None
            doc.draft_rules = (copy.deepcopy(base.rules) if base
                               else draft_rules(tree, synonyms, learned_pairs(active_rule_sets())))
        rules = doc.draft_rules
    if ident.supplier:
        doc.supplier_id = ident.supplier.id
    too_many = _too_many_lines(tree, rules)
    if too_many:
        doc.status, doc.error, doc.result = STATUS_REJECTED, too_many, None
        doc.issues = [Issue("too_many_lines", BLOCKING, too_many, field="line_path").to_dict()]
        return doc
    lookups = DbLookups()
    result = apply_template(tree, rules, lookups, doc.supplier_id, doc.overrides or {})
    inv = result.invoice
    issues = aggregate_line_issues(list(result.issues) + validate_invoice(inv))
    if ident.supplier is None:
        issues.insert(0, Issue("unknown_supplier", BLOCKING,
                               "Nie rozpoznano dostawcy — utwórz nowego z danych faktury albo wskaż istniejącego.",
                               field="supplier",
                               source_value=" / ".join(x for x in (get_path(inv, "supplier.name"),
                                                                   get_path(inv, "supplier.tax_id")) if x) or None))
    _enrich(issues, tree, rules, inv, synonyms, ident, lookups)
    # duplikat ustalany na końcu: po nim są już tylko zapisy (przejęcie klucza nie zostanie w połowie)
    dup, demoted = _resolve_duplicate(doc, inv)
    if dup is _CONCURRENT:
        issues.insert(0, Issue("duplicate", BLOCKING, "Ta faktura została właśnie przyjęta w równoległym "
                                                      "żądaniu (duplikat istniejącego dokumentu)."))
    elif dup is not None:
        issues.insert(0, Issue("duplicate", BLOCKING,
                               f"Ta faktura była już przetworzona (dokument #{dup.id}).", source_value=str(dup.id)))
    doc.result = inv
    doc.issues = [i.to_dict() for i in issues]
    doc.number = _stored_number(inv)
    doc.issue_date = _fit(Document.issue_date, inv.get("issue_date"))
    doc.doc_type = _fit(Document.doc_type, inv.get("doc_type"))
    doc.status = STATUS_DUPLICATE if dup else (STATUS_NEEDS_REVIEW if has_blocking(issues) else STATUS_APPROVED)
    if demoted is not None:
        db.session.flush()
        process(demoted)  # późniejsza kopia — teraz duplikat tego (wcześniejszego) dokumentu
    return doc


def ingest(data: bytes, filename: str | None, source: str = "upload", api_key_id: int | None = None) -> Document:
    limit = current_app.config["MAX_DOCUMENT_BYTES"]
    if len(data) > limit:
        raise DocumentTooLarge(f"Plik przekracza limit {limit // (1024 * 1024)} MB.")
    storage = get_storage()
    try:
        sha, created = storage.store(data)
    except OSError as exc:  # pełny dysk / utracony wolumen w trakcie pracy — 503 albo komunikat, nie 500
        current_app.logger.exception("Nie udało się zapisać pliku w magazynie %s", storage.base)
        raise StorageUnavailable(STORAGE_UNAVAILABLE_MSG) from exc
    try:
        doc = Document(source=_fit(Document.source, source), filename=_fit(Document.filename, filename or "dokument"),
                       sha256=sha, status=STATUS_RECEIVED,
                       overrides={}, issues=[], api_key_id=api_key_id)
        db.session.add(doc)
        db.session.flush()
        process(doc)
        audit("ingest", "document", doc.id, {"status": doc.status, "source": source, "filename": doc.filename})
        db.session.commit()
    except BaseException:
        # rekord nie powstał — nie zostawiamy osieroconego pliku, który zapisaliśmy (BE-9)
        db.session.rollback()
        if created:
            try:
                if not Document.query.filter_by(sha256=sha).first():
                    storage.delete(sha)
            except Exception:  # noqa: BLE001 - sprzątanie nie może przesłonić pierwotnego błędu
                current_app.logger.exception("Nie udało się usunąć osieroconego pliku %s", sha)
        raise
    return doc
