from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import ApiKey, Document
from app.services.apikeys import create_key
from app.services.audit import audit

bp = Blueprint("apikeys", __name__, url_prefix="/klucze-api")
NAME_MAX = ApiKey.name.type.length


@bp.get("")
@login_required
def index():
    return render_template("apikeys.html", keys=ApiKey.query.order_by(ApiKey.id).all(), new_key=None)


@bp.post("/nowy")
@login_required
def create():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Podaj nazwę klucza (np. nazwa systemu).", "error")
        return redirect(url_for("apikeys.index"))
    if len(name) > NAME_MAX:  # BE-8: bez DataError/500 w MariaDB
        flash(f"Nazwa klucza może mieć maks. {NAME_MAX} znaków.", "error")
        return redirect(url_for("apikeys.index"))
    key, plain = create_key(name)
    audit("create", "api_key", key.id, {"name": name, "prefix": key.prefix})
    db.session.commit()
    return render_template("apikeys.html", keys=ApiKey.query.order_by(ApiKey.id).all(), new_key=plain)


@bp.post("/<int:key_id>/przelacz")
@login_required
def toggle(key_id):
    key = db.session.get(ApiKey, key_id)
    if key:
        key.active = not key.active
        audit("toggle", "api_key", key.id, {"active": key.active})
        db.session.commit()
    return redirect(url_for("apikeys.index"))


@bp.post("/<int:key_id>/nazwa")
@login_required
def rename(key_id):
    key = db.session.get(ApiKey, key_id)
    name = (request.form.get("name") or "").strip()
    if len(name) > NAME_MAX:
        flash(f"Nazwa klucza może mieć maks. {NAME_MAX} znaków.", "error")
        return redirect(url_for("apikeys.index"))
    if key and name:
        key.name = name
        audit("update", "api_key", key.id, {"name": name})
        db.session.commit()
    return redirect(url_for("apikeys.index"))


@bp.post("/<int:key_id>/usun")
@login_required
def delete(key_id):
    key = db.session.get(ApiKey, key_id)
    if key:
        # dokumenty klucza zachowują atrybucję i zostają dostępne przez API — klucz z dokumentami
        # można tylko dezaktywować (BE-18)
        used = Document.query.filter_by(api_key_id=key.id).count()
        if used:
            flash(f"Nie można usunąć klucza „{key.name}”: ma {used} dokument(ów). Zamiast usuwać, dezaktywuj go "
                  "— przestanie działać, a dokumenty zachowają powiązanie.", "error")
            return redirect(url_for("apikeys.index"))
        try:
            audit("delete", "api_key", key.id, {"name": key.name})
            db.session.delete(key)
            db.session.commit()
        except IntegrityError:  # równoległy upload tym kluczem
            db.session.rollback()
            flash("Nie można usunąć klucza — właśnie przyjęto nim dokument. Dezaktywuj go.", "error")
    return redirect(url_for("apikeys.index"))
