"""Przetwarzanie dokumentu: odczyt → identyfikacja → szablon → walidacja → status → podpowiedzi."""
from __future__ import annotations

import copy
from dataclasses import dataclass

from flask import current_app

from app.engine.canonical import get_path
from app.engine.issues import BLOCKING, Issue, has_blocking
from app.engine.suggest import (FIELDS_BY_KEY, conversion_guess, draft_rules, field_candidates, learned_pairs,
                                load_synonyms, product_candidates, suffix_match, supplier_candidates,
                                tax_ids_match, unit_candidates)
from app.engine.template import apply_template
from app.engine.tree import SourceTree, jaccard
from app.engine.validate import validate_invoice
from app.extensions import db
from app.ingest import ReaderError, read_document
from app.models import (STATUS_APPROVED, STATUS_DUPLICATE, STATUS_NEEDS_REVIEW, STATUS_RECEIVED,
                        STATUS_REJECTED, Document, Product, Supplier, Template)
from app.services.audit import audit
from app.services.lookups_db import DbLookups
from app.services.storage import get_storage
from app.services.templates import active_rule_sets

FINGERPRINT_MIN = 0.6
DEFAULT_VALUES = {"currency": ["PLN", "GBP", "EUR"], "payment_method": ["przelew", "gotówka", "karta"]}


class DocumentTooLarge(ValueError):
    pass


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
        suppliers = Supplier.query.filter(Supplier.tax_id.isnot(None)).all()
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


def _find_duplicate(doc: Document, invoice: dict) -> Document | None:
    q = Document.query.filter(Document.id != doc.id,
                              Document.status.in_([STATUS_APPROVED, STATUS_NEEDS_REVIEW]))
    same = q.filter(Document.sha256 == doc.sha256).order_by(Document.id).first()
    if same:
        return same
    if doc.supplier_id and invoice.get("number"):
        return q.filter(Document.supplier_id == doc.supplier_id,
                        Document.number == invoice["number"]).order_by(Document.id).first()
    return None


def _enrich(issues: list[Issue], tree: SourceTree, rules: dict, inv: dict, synonyms: dict,
            ident: Identification, lookups: DbLookups) -> None:
    learned = learned_pairs(active_rule_sets())
    line_path = rules.get("line_path")
    products = None
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
        elif code == "unknown_unit":
            issue.suggestions = unit_candidates(issue.source_value or "", lookups.unit_codes(), synonyms)
        elif code == "unmapped_product" and issue.line_no:
            line = inv["lines"][issue.line_no - 1]
            products = products if products is not None else lookups.products_brief()
            issue.suggestions = product_candidates(line, products) + [{
                "kind": "create_product", "code": next_product_code(), "name": line.get("name"),
                "unit": line.get("unit"), "confidence": 0.3, "reason": "nowy towar w kartotece"}]
        elif code == "missing_conversion" and issue.line_no:
            line = inv["lines"][issue.line_no - 1]
            issue.suggestions = [conversion_guess(line.get("name"), issue.source_value or "")]


def _fit(column, value):
    """Obcina wartość do długości kolumny (MariaDB w trybie strict odrzuca dłuższe)."""
    if value is None:
        return None
    return str(value)[:column.type.length]


def process(doc: Document) -> Document:
    synonyms = load_synonyms()
    try:
        tree = load_tree(doc)
    except ReaderError as exc:
        doc.status, doc.error, doc.result = STATUS_REJECTED, str(exc), None
        doc.issues = [Issue("unreadable", BLOCKING, str(exc)).to_dict()]
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
    lookups = DbLookups()
    result = apply_template(tree, rules, lookups, doc.supplier_id, doc.overrides or {})
    inv = result.invoice
    issues = list(result.issues) + validate_invoice(inv)
    if ident.supplier is None:
        issues.insert(0, Issue("unknown_supplier", BLOCKING,
                               "Nie rozpoznano dostawcy — utwórz nowego z danych faktury albo wskaż istniejącego.",
                               field="supplier",
                               source_value=" / ".join(x for x in (get_path(inv, "supplier.name"),
                                                                   get_path(inv, "supplier.tax_id")) if x) or None))
    dup = None if (doc.overrides or {}).get("allow_duplicate") else _find_duplicate(doc, inv)
    if dup:
        issues.insert(0, Issue("duplicate", BLOCKING,
                               f"Ta faktura była już przetworzona (dokument #{dup.id}).", source_value=str(dup.id)))
    _enrich(issues, tree, rules, inv, synonyms, ident, lookups)
    doc.result = inv
    doc.issues = [i.to_dict() for i in issues]
    doc.number = _fit(Document.number, inv.get("number"))
    doc.issue_date = _fit(Document.issue_date, inv.get("issue_date"))
    doc.doc_type = _fit(Document.doc_type, inv.get("doc_type"))
    doc.status = STATUS_DUPLICATE if dup else (STATUS_NEEDS_REVIEW if has_blocking(issues) else STATUS_APPROVED)
    return doc


def ingest(data: bytes, filename: str | None, source: str = "upload", api_key_id: int | None = None) -> Document:
    limit = current_app.config["MAX_DOCUMENT_BYTES"]
    if len(data) > limit:
        raise DocumentTooLarge(f"Plik przekracza limit {limit // (1024 * 1024)} MB.")
    sha = get_storage().save(data)
    doc = Document(source=_fit(Document.source, source), filename=_fit(Document.filename, filename or "dokument"),
                   sha256=sha, status=STATUS_RECEIVED,
                   overrides={}, issues=[], api_key_id=api_key_id)
    db.session.add(doc)
    db.session.flush()
    process(doc)
    audit("ingest", "document", doc.id, {"status": doc.status, "source": source, "filename": doc.filename})
    db.session.commit()
    return doc
