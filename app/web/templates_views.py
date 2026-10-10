import difflib
import json

import regex

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.engine.canonical import HEADER_FIELDS, LINE_FIELDS
from app.engine.suggest import field_candidates, learned_pairs, load_synonyms
from app.engine.template import apply_template
from app.engine.transforms import MAX_PATTERN, REGISTRY, TRANSFORM_LABELS
from app.engine.validate import validate_invoice
from app.extensions import db
from app.ingest import ReaderError
from app.models import Document, Template, TemplateVersion
from app.services.audit import audit
from app.services.lookups_db import DbLookups
from app.services.pipeline import current_rules, load_tree, process
from app.services.templates import active_rule_sets, new_version

bp = Blueprint("templates_views", __name__, url_prefix="/szablony")


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
    rows = []
    for t in Template.query.order_by(Template.id).all():
        rows.append({"t": t, "docs": Document.query.filter_by(template_id=t.id).count(),
                     "active": t.active_version})
    return render_template("templates_list.html", rows=rows)


@bp.get("/<int:tid>")
@login_required
def detail(tid):
    t = _tpl(tid)
    diff = None
    a, b = request.args.get("a", type=int), request.args.get("b", type=int)
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
    nv = new_version(t, v.rules, current_user.email, f"Przywrócono wersję {v.version}")
    audit("restore", "template", t.id, {"from_version": v.version, "new_version": nv.version})
    db.session.commit()
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
    cands = {f.key: [c.to_dict() for c in field_candidates(tree, f.key, line_path, synonyms, learned, limit=3)]
             for f in HEADER_FIELDS + LINE_FIELDS if f.key != "doc_type"}
    config = {
        "docId": doc.id, "rules": rules, "rows": tree.display_rows(), "groups": tree.group_paths(),
        "header": [{"key": f.key, "label": f.label, "required": f.required} for f in HEADER_FIELDS if f.key != "doc_type"],
        "lines": [{"key": f.key, "label": f.label, "required": f.required} for f in LINE_FIELDS],
        "candidates": cands, "transforms": TRANSFORM_LABELS,
        "previewUrl": url_for("templates_views.preview", doc_id=doc.id),
        "saveUrl": url_for("templates_views.save", doc_id=doc.id),
        "backUrl": url_for("docs.detail", doc_id=doc.id),
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


def _is_number(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        try:
            float(v.replace(",", "."))
            return True
        except ValueError:
            return False
    return False


def _check_arg(name: str, arg, key: str) -> str | None:
    if name == "map" and not isinstance(arg, dict):
        return f"Transformacja 'map' w polu '{key}' wymaga słownika."
    if name == "convert" and not _is_number(arg):
        return f"Transformacja 'convert' w polu '{key}' wymaga liczby."
    if name == "date" and not (isinstance(arg, str) and arg):
        return f"Transformacja 'date' w polu '{key}' wymaga formatu daty (tekst)."
    if name == "split":
        if arg is not None and not isinstance(arg, dict):
            return f"Transformacja 'split' w polu '{key}' wymaga obiektu (sep, index)."
        arg = arg or {}
        if not isinstance(arg.get("sep", " "), str) or isinstance(arg.get("index", 0), bool) \
                or not isinstance(arg.get("index", 0), int):
            return f"Transformacja 'split' w polu '{key}': sep musi być tekstem, a index liczbą całkowitą."
    if name == "concat":
        if not isinstance(arg, dict) or not isinstance(arg.get("paths", []), list) \
                or not all(isinstance(x, str) for x in arg.get("paths", [])) \
                or not isinstance(arg.get("sep", " "), str):
            return f"Transformacja 'concat' w polu '{key}' wymaga obiektu z listą 'paths' i tekstem 'sep'."
    return None


def validate_rules(rules: dict) -> str | None:
    """Zwraca polski komunikat błędu albo None, gdy reguły są poprawne (biała lista transformacji, limity regex)."""
    if rules.get("line_path") is not None and not isinstance(rules["line_path"], str):
        return "Ścieżka elementu z pozycjami musi być tekstem."
    for bucket in ("header", "lines", "defaults", "line_defaults"):
        if not isinstance(rules.get(bucket, {}), dict):
            return f"Sekcja '{bucket}' musi być obiektem."
    for bucket in ("defaults", "line_defaults"):
        for k, v in rules.get(bucket, {}).items():
            if not isinstance(v, (str, int, float)) or isinstance(v, bool):
                return f"Wartość domyślna pola '{k}' musi być tekstem lub liczbą."
    for bucket in ("header", "lines"):
        for key, rule in rules.get(bucket, {}).items():
            if not isinstance(rule, dict):
                return f"Reguła pola '{key}' musi być obiektem."
            for attr in ("path", "constant"):
                if rule.get(attr) is not None and not isinstance(rule[attr], str):
                    return f"Pole '{attr}' w regule '{key}' musi być tekstem."
            chain = rule.get("transforms", [])
            if not isinstance(chain, list):
                return f"Transformacje pola '{key}' muszą być listą."
            for step in chain:
                if isinstance(step, str):
                    name, arg = step, None
                elif isinstance(step, dict) and len(step) == 1:
                    name, arg = next(iter(step.items()))
                else:
                    return f"Niepoprawny krok transformacji w polu '{key}'."
                if name not in REGISTRY:
                    return f"Nieznana transformacja '{name}' w polu '{key}'."
                msg = _check_arg(name, arg, key)
                if msg:
                    return msg
                if name == "regex_extract":
                    pattern = arg.get("pattern", "") if isinstance(arg, dict) else None
                    if not isinstance(pattern, str):
                        return f"Transformacja 'regex_extract' w polu '{key}' wymaga wzorca (pattern)."
                    if len(pattern) > MAX_PATTERN:
                        return f"Wyrażenie regularne w polu '{key}' jest za długie (max {MAX_PATTERN} znaków)."
                    try:
                        regex.compile(pattern)
                    except regex.error:
                        return f"Błędne wyrażenie regularne w polu '{key}'."
    return None


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
    raw_comment = payload.get("comment")
    comment = (raw_comment.strip() if isinstance(raw_comment, str) else "") or "Zmiana w edytorze mapowań"
    comment = comment[:500]
    try:  # próba na sucho: wyjątek = 400 i nic nie zapisujemy (błędy transformacji to zwykłe issues)
        apply_template(load_tree(doc), rules, DbLookups(), doc.supplier_id, doc.overrides or {})
    except (ReaderError, OSError):
        return jsonify(error="Nie można odczytać pliku źródłowego dokumentu."), 400
    except Exception:  # noqa: BLE001
        return jsonify(error="Reguły nie dają się zastosować do tego dokumentu."), 400
    if doc.template_id:
        v = new_version(db.session.get(Template, doc.template_id), rules, current_user.email, comment)
        audit("edit", "template", doc.template_id, {"version": v.version, "comment": comment})
    else:
        doc.draft_rules = rules
        audit("edit_draft", "document", doc.id, {"comment": comment})
    process(doc)
    db.session.commit()
    return jsonify(ok=True, status=doc.status, redirect=url_for("docs.detail", doc_id=doc.id))
