"""Ogólny CRUD dla prostych tabel słownikowych (lista + formularz + edycja + usuwanie)."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy.exc import DataError, IntegrityError

from app.engine.values import parse_factor
from app.extensions import db
from app.ids import parse_id
from app.services.audit import audit


@dataclass
class CrudField:
    name: str
    label: str
    type: str = "text"
    required: bool = False
    choices: Callable[[], list[tuple[Any, str]]] | None = None


@dataclass
class CrudSpec:
    key: str
    model: type
    title: str
    url: str
    fields: list[CrudField]
    columns: list[tuple[str, Callable[[Any], Any]]]
    order_by: Callable[[], Any]
    before_save: Callable[[Any], None] | None = None      # rzuca ValueError z komunikatem PL
    delete_blocker: Callable[[Any], str | None] | None = None
    extra_actions: list[tuple[str, str]] = field(default_factory=list)  # (etykieta, endpoint)


def _max_length(model, name: str) -> int | None:
    col = model.__table__.columns.get(name)
    return getattr(col.type, "length", None) if col is not None else None


def _parse(f: CrudField, raw: str | None, model=None):
    raw = (raw or "").strip()
    if f.type == "checkbox":
        return raw in ("1", "on", "true")
    if raw == "":
        if f.required:
            raise ValueError(f"Pole „{f.label}” jest wymagane.")
        return None
    if f.type == "number":  # jedyne pole liczbowe to przelicznik — wspólna reguła (FR-2)
        try:
            return parse_factor(raw)
        except ValueError as exc:
            raise ValueError(f"Pole „{f.label}”: {exc}") from None
    if f.type == "select":
        value = parse_id(raw)  # id spoza zakresu kolumny = zła wartość, nie 500 (SQLite)
        if value is None:
            raise ValueError(f"Nieprawidłowa wartość pola „{f.label}”.")
        return value
    limit = _max_length(model, f.name) if model is not None else None
    if limit and len(raw) > limit:  # MariaDB strict odrzuciłaby to DataError → 500 (BE-8/EDGE-18)
        raise ValueError(f"Pole „{f.label}” może mieć maks. {limit} znaków (wpisano {len(raw)}).")
    return raw


def _snapshot(obj, spec: CrudSpec) -> dict:
    out = {}
    for f in spec.fields:
        v = getattr(obj, f.name)
        out[f.name] = str(v) if isinstance(v, Decimal) else v
    return out


def register_crud(bp, spec: CrudSpec) -> None:
    def list_view():
        rows = spec.model.query.order_by(spec.order_by()).all()
        return render_template("crud_list.html", spec=spec, rows=rows)

    def form_view(obj_id: int | None = None):
        obj = db.session.get(spec.model, obj_id) if obj_id else spec.model()
        if obj is None:
            flash("Nie znaleziono rekordu.", "error")
            return redirect(url_for(f"catalog.list_{spec.key}"))
        if request.method == "POST":
            try:
                for f in spec.fields:
                    setattr(obj, f.name, _parse(f, request.form.get(f.name), spec.model))
                if spec.before_save:
                    spec.before_save(obj)
                if obj_id is None:
                    db.session.add(obj)
                db.session.flush()
                audit("update" if obj_id else "create", spec.key, obj.id, _snapshot(obj, spec))
                db.session.commit()
                flash("Zapisano.", "success")
                return redirect(url_for(f"catalog.list_{spec.key}"))
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "error")
            except IntegrityError:  # np. naruszenie unikalności (także w wyścigu) lub klucza obcego
                db.session.rollback()
                flash("Nie udało się zapisać — sprawdź, czy wartość nie jest zduplikowana "
                      "i czy wskazane powiązania istnieją.", "error")
            except DataError:  # wartość niemieszcząca się w kolumnie — ostatnia linia obrony (BE-8)
                db.session.rollback()
                flash("Nie udało się zapisać — wartość jest zbyt długa lub ma niepoprawny format.", "error")
            # po błędzie pokazujemy wpisane wartości (obiekt po rollbacku ma stan z bazy)
            form = request.form
        else:
            form = None
        return render_template("crud_form.html", spec=spec, obj=obj, is_new=obj_id is None, form=form)

    def delete_view(obj_id: int):
        obj = db.session.get(spec.model, obj_id)
        if obj is not None:
            reason = spec.delete_blocker(obj) if spec.delete_blocker else None
            if reason:
                flash(f"Nie można usunąć: {reason}", "error")
            else:
                try:
                    audit("delete", spec.key, obj.id, _snapshot(obj, spec))
                    db.session.delete(obj)
                    db.session.commit()
                    flash("Usunięto.", "success")
                except IntegrityError:
                    db.session.rollback()
                    flash("Nie można usunąć: rekord jest powiązany z innymi danymi.", "error")
        return redirect(url_for(f"catalog.list_{spec.key}"))

    bp.add_url_rule(spec.url, f"list_{spec.key}", login_required(list_view))
    bp.add_url_rule(f"{spec.url}/nowy", f"new_{spec.key}", login_required(form_view), methods=["GET", "POST"])
    bp.add_url_rule(f"{spec.url}/<int:obj_id>/edycja", f"edit_{spec.key}", login_required(form_view),
                    methods=["GET", "POST"])
    bp.add_url_rule(f"{spec.url}/<int:obj_id>/usun", f"delete_{spec.key}", login_required(delete_view),
                    methods=["POST"])
