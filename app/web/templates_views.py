import difflib
import json

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.engine.canonical import HEADER_FIELDS, LINE_FIELDS
from app.engine.suggest import field_candidates, learned_pairs, load_synonyms
from app.engine.template import apply_template
from app.engine.transforms import TRANSFORM_LABELS, validate_rules
from app.engine.validate import validate_invoice
from app.extensions import db
from app.ids import parse_id
from app.ingest import ReaderError
from app.models import Document, Template, TemplateVersion
from app.services.audit import audit
from app.services.dbutil import commit_with_retry
from app.services.lookups_db import DbLookups
from app.services.negotiation import CONFLICT_MSG, save_rules
from app.services.pipeline import current_rules, load_tree, process
from app.services.templates import active_rule_sets, locked_active_version_id, new_version

from .paging import cursor_arg, first_url, next_url, page_by_id

bp = Blueprint("templates_views", __name__, url_prefix="/szablony")
COMMENT_MAX = TemplateVersion.comment.type.length  # komentarz wersji obcinany do kolumny
EDITOR_CANDIDATES = 3  # podpowiedzi ścieżek na pole w edytorze
TEMPLATES_PAGE_SIZE = 100  # rozmiar strony listy szablonów (`?after=`)


def _tpl(tid: int) -> Template:
    t = db.session.get(Template, tid)
    if not t:
        abort(404)
    return t


def _doc(doc_id: int) -> Document:
    d = db.session.get(Document, doc_id)
    if not d:
        abort(404)
    return d


@bp.get("")
@login_required
def index():
    # rosnąco po id (jak dotąd), kolejna strona po `?after=`; stała liczba zapytań niezależnie od liczby szablonów
    templates, cursor = page_by_id(Template.query.options(selectinload(Template.supplier)), Template.id,
                                   TEMPLATES_PAGE_SIZE, after=cursor_arg("after") or 0)
    ids = [t.id for t in templates]
    counts = dict(db.session.query(Document.template_id, func.count(Document.id))
                  .filter(Document.template_id.in_(ids)).group_by(Document.template_id)) if ids else {}
    active_ids = [t.active_version_id for t in templates if t.active_version_id is not None]
    # jedno zapytanie wypełnia mapę tożsamości — t.active_version (session.get) nie pyta już bazy
    active = {v.id: v for v in TemplateVersion.query.filter(TemplateVersion.id.in_(active_ids))} if active_ids else {}
    rows = [{"t": t, "docs": counts.get(t.id, 0), "active": active.get(t.active_version_id)} for t in templates]
    return render_template("templates_list.html", rows=rows, shown=len(rows),
                           next_url=next_url("after", cursor) if cursor else None,
                           first_url=first_url("after") if cursor_arg("after") else None)


@bp.get("/<int:tid>")
@login_required
def detail(tid):
    t = _tpl(tid)
    diff = None
    a, b = parse_id(request.args.get("a")), parse_id(request.args.get("b"))
    if a and b:
        va, vb = db.session.get(TemplateVersion, a), db.session.get(TemplateVersion, b)
        if va and vb and va.template_id == vb.template_id == t.id:
            dump = lambda v: json.dumps(v.rules, indent=2, ensure_ascii=False, sort_keys=True).splitlines()  # noqa: E731
            diff = {"a": va, "b": vb, "lines": list(difflib.unified_diff(dump(va), dump(vb), f"v{va.version}",
                                                                          f"v{vb.version}", lineterm=""))}
    return render_template("template_detail.html", t=t, diff=diff)


@bp.post("/<int:tid>/przywroc/<int:vid>")
@login_required
def restore(tid, vid):
    t = _tpl(tid)
    v = db.session.get(TemplateVersion, vid)
    if not v or v.template_id != t.id:
        abort(404)
    rules, from_version = dict(v.rules), v.version

    def apply():
        nv = new_version(t, rules, current_user.email, f"Przywrócono wersję {from_version}")
        audit("restore", "template", t.id, {"from_version": from_version, "new_version": nv.version})
        return nv
    try:
        nv = commit_with_retry(apply)
    except IntegrityError:
        flash(CONFLICT_MSG, "error")
        return redirect(url_for("templates_views.detail", tid=tid))
    flash(f"Aktywna jest teraz wersja {nv.version} (kopia wersji {v.version}).", "success")
    return redirect(url_for("templates_views.detail", tid=t.id))


@bp.post("/<int:tid>/usun")
@login_required
def delete(tid):
    t = _tpl(tid)
    if Document.query.filter_by(template_id=t.id).count():
        flash("Nie można usunąć: szablon jest użyty w dokumentach.", "error")
        return redirect(url_for("templates_views.detail", tid=t.id))
    audit("delete", "template", t.id, {"name": t.name})
    db.session.delete(t)
    db.session.commit()
    flash("Usunięto szablon.", "success")
    return redirect(url_for("templates_views.index"))


def _render_editor(doc: Document, rules: dict, title: str):
    try:
        tree = load_tree(doc)
    except (ReaderError, OSError):
        flash("Nie można odczytać pliku źródłowego dokumentu.", "error")
        return redirect(url_for("docs.detail", doc_id=doc.id))
    synonyms, learned = load_synonyms(), learned_pairs(active_rule_sets())
    line_path = rules.get("line_path")
    cands = {f.key: [c.to_dict() for c in field_candidates(tree, f.key, line_path, synonyms, learned,
                                                             limit=EDITOR_CANDIDATES)]
             for f in HEADER_FIELDS + LINE_FIELDS if f.key != "doc_type"}
    config = {
        "docId": doc.id, "rules": rules, "rows": tree.display_rows(), "groups": tree.group_paths(),
        "header": [{"key": f.key, "label": f.label, "required": f.required}
                   for f in HEADER_FIELDS if f.key != "doc_type"],
        "lines": [{"key": f.key, "label": f.label, "required": f.required} for f in LINE_FIELDS],
        "candidates": cands, "transforms": TRANSFORM_LABELS,
        "previewUrl": url_for("templates_views.preview", doc_id=doc.id),
        "saveUrl": url_for("templates_views.save", doc_id=doc.id),
        "backUrl": url_for("docs.detail", doc_id=doc.id),
        # blokada optymistyczna: zapis porównuje tę wersję z aktywną (BE-7)
        "baseVersionId": _active_version_id(doc),
    }
    return render_template("editor.html", full_screen=True, config=config, title=title, doc=doc)


@bp.get("/<int:tid>/edytor")
@login_required
def editor_for_template(tid):
    t = _tpl(tid)
    doc = Document.query.filter_by(template_id=t.id).order_by(Document.id.desc()).first()
    if not doc:
        flash("Edytor potrzebuje przykładowej faktury — ten szablon nie ma jeszcze dokumentów.", "error")
        return redirect(url_for("templates_views.detail", tid=t.id))
    return _render_editor(doc, current_rules(doc), f"Edytor mapowań — {t.name}")


@bp.get("/dokument/<int:doc_id>/edytor")
@login_required
def editor_for_document(doc_id):
    doc = _doc(doc_id)
    return _render_editor(doc, current_rules(doc), f"Edytor mapowań — dokument #{doc.id}")


def _active_version_id(doc: Document) -> int | None:
    tpl = db.session.get(Template, doc.template_id) if doc.template_id else None
    return tpl.active_version_id if tpl else None


STALE_BASE_MSG = ("Szablon zmienił się w międzyczasie (ktoś zapisał nowszą wersję) — odśwież edytor "
                  "i nanieś zmiany ponownie, żeby nie nadpisać cudzej pracy.")


class _StaleBaseVersion(Exception):
    """Aktywna wersja szablonu różni się od wersji bazowej edytora — 409, bez ponawiania."""


def _mapped(rules: dict, section: str, key: str) -> bool:
    rule = (rules.get(section) or {}).get(key)
    has_rule = isinstance(rule, dict) and bool(rule.get("path") or "constant" in rule)
    defaults = rules.get("line_defaults" if section == "lines" else "defaults") or {}
    return has_rule or defaults.get(key) not in (None, "")


def _lost_required(old: dict, new: dict) -> list[str]:
    """Etykiety pól wymaganych zmapowanych w poprzednich regułach, a brakujących w nowych (EDGE-15)."""
    out = []
    for section, fields in (("header", HEADER_FIELDS), ("lines", LINE_FIELDS)):
        out += [f.label for f in fields
                if f.required and _mapped(old or {}, section, f.key) and not _mapped(new, section, f.key)]
    return out


def _rules_from_request():
    """Zwraca (rules, payload, error_response)."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    rules = payload.get("rules")
    if not isinstance(rules, dict):
        return None, payload, (jsonify(error="Niepoprawne reguły (oczekiwano obiektu JSON)."), 400)
    err = validate_rules(rules)
    if err:
        return None, payload, (jsonify(error=err), 400)
    return rules, payload, None


@bp.post("/dokument/<int:doc_id>/podglad")
@login_required
def preview(doc_id):
    doc = _doc(doc_id)
    rules, _, err = _rules_from_request()
    if err:
        return err
    try:
        tree = load_tree(doc)
        res = apply_template(tree, rules, DbLookups(), doc.supplier_id, doc.overrides or {})
    except (ReaderError, OSError):
        return jsonify(error="Nie można odczytać pliku źródłowego dokumentu."), 400
    except Exception:  # noqa: BLE001 - niepoprawne reguły z edytora nie mogą dawać 500
        return jsonify(error="Reguły nie dają się zastosować do tego dokumentu."), 400
    issues = res.issues + validate_invoice(res.invoice)
    return jsonify(invoice=res.invoice, issues=[i.to_dict() for i in issues])


@bp.post("/dokument/<int:doc_id>/zapisz")
@login_required
def save(doc_id):
    doc = _doc(doc_id)
    rules, payload, err = _rules_from_request()
    if err:
        return err
    if not (isinstance(rules.get("line_path"), str) and rules["line_path"].strip()):  # EDGE-15
        return jsonify(error="Wskaż element z pozycjami faktury (line_path) — bez niego szablon "
                             "nie odczyta żadnej pozycji."), 400
    lost = _lost_required(current_rules(doc), rules)
    if lost and payload.get("confirm_incomplete") is not True:
        return jsonify(error="Nowa wersja usuwa mapowanie pól wymaganych: " + ", ".join(lost)
                             + ". Kolejne faktury dostawcy trafią do wyjaśnienia. Zapisać mimo to?",
                       needs_confirm=True), 400
    raw_comment = payload.get("comment")
    comment = (raw_comment.strip() if isinstance(raw_comment, str) else "") or "Zmiana w edytorze mapowań"
    comment = comment[:COMMENT_MAX]
    try:  # próba na sucho: wyjątek = 400 i nic nie zapisujemy (błędy transformacji to zwykłe issues)
        apply_template(load_tree(doc), rules, DbLookups(), doc.supplier_id, doc.overrides or {})
    except (ReaderError, OSError):
        return jsonify(error="Nie można odczytać pliku źródłowego dokumentu."), 400
    except Exception:  # noqa: BLE001
        return jsonify(error="Reguły nie dają się zastosować do tego dokumentu."), 400
    check_base = "base_version_id" in payload
    base = payload.get("base_version_id")

    def apply():
        # FR-5: kontrola wersji bazowej w każdej próbie, pod blokadą wiersza szablonu — zapis innego
        # operatora między kontrolą a commitem (albo przed ponowieniem po IntegrityError) daje 409
        if check_base and base != locked_active_version_id(doc):
            raise _StaleBaseVersion()
        if doc.template_id or doc.supplier_id:
            v = save_rules(doc, rules, current_user.email, comment)
            audit("edit", "template", doc.template_id, {"version": v.version, "comment": comment})
        else:
            doc.draft_rules = rules
            audit("edit_draft", "document", doc.id, {"comment": comment})
        process(doc)  # process() sam pomija dokument odrzucony ręcznie (BE-2)
    try:
        commit_with_retry(apply)
    except _StaleBaseVersion:
        return jsonify(error=STALE_BASE_MSG, conflict=True), 409
    except IntegrityError:
        return jsonify(error=CONFLICT_MSG, conflict=True), 409
    return jsonify(ok=True, status=doc.status, redirect=url_for("docs.detail", doc_id=doc.id))
