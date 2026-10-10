from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import ApiKey, Document
from app.services.apikeys import create_key
from app.services.audit import audit

bp = Blueprint("apikeys", __name__, url_prefix="/klucze-api")


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
        Document.query.filter_by(api_key_id=key.id).update({Document.api_key_id: None})
        audit("delete", "api_key", key.id, {"name": key.name})
        db.session.delete(key)
        db.session.commit()
    return redirect(url_for("apikeys.index"))
