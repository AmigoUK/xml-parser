from flask import Blueprint, abort, current_app, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import EVENT_TEST, WEBHOOK_FAILED, ApiKey, Document, WebhookDelivery
from app.services.apikeys import clear_webhook, create_key, rotate_webhook_secret, set_webhook_url
from app.services.audit import audit
from app.services.webhook_outbox import enqueue_test
from app.services.webhook_security import MAX_URL_LENGTH, TargetError, parse_allowed_hosts, validate_target
from app.services.webhooks import retry, send_now

bp = Blueprint("apikeys", __name__, url_prefix="/klucze-api")
NAME_MAX = ApiKey.name.type.length
DELIVERIES_LIMIT = 50  # najnowsze dostawy pokazywane przy kluczu


def _is_admin():
    return current_user.role == "admin"


def _admin_or_403():
    """Ustawienia webhooka (adres, sekret, dostawy) zmienia tylko administrator (jak reset demo)."""
    if not _is_admin():
        abort(403)


def _deliveries(keys):
    # osobne zapytanie na klucz (indeks (api_key_id, created_at, id)); kluczy jest kilka, a LIMIT na grupę
    # w jednym zapytaniu wymagałby funkcji okna
    return {k.id: (WebhookDelivery.query.filter_by(api_key_id=k.id)
                   .order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc())
                   .limit(DELIVERIES_LIMIT).all()) for k in keys}


def _render(new_key, webhook_secret=None):
    """`webhook_secret` = (klucz, sekret) — sekret webhooka pokazywany jednorazowo, jak nowy klucz."""
    keys = ApiKey.query.order_by(ApiKey.id).all()
    is_admin = _is_admin()
    return render_template("apikeys.html", keys=keys, new_key=new_key, name_max=NAME_MAX, is_admin=is_admin,
                           deliveries=_deliveries(keys) if is_admin else {}, webhook_secret=webhook_secret,
                           url_max=MAX_URL_LENGTH, failed=WEBHOOK_FAILED,
                           deliveries_limit=DELIVERIES_LIMIT)


def _no_store(html):
    """Odpowiedź z jednorazowym sekretem nie może wrócić z pamięci podręcznej (wstecz/dalej, proxy)."""
    response = make_response(html)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def _key_or_flash(key_id):
    key = db.session.get(ApiKey, key_id)
    if not key:
        flash("Nie znaleziono klucza.", "error")
    return key


@bp.get("")
@login_required
def index():
    return _render(None)


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
    return _render(plain)


@bp.post("/<int:key_id>/przelacz")
@login_required
def toggle(key_id):
    key = db.session.get(ApiKey, key_id)
    if not key:
        flash("Nie znaleziono klucza.", "error")
        return redirect(url_for("apikeys.index"))
    key.active = not key.active
    audit("toggle", "api_key", key.id, {"active": key.active})
    db.session.commit()
    flash(f"Klucz „{key.name}” {'włączony' if key.active else 'wyłączony'}.", "success")
    return redirect(url_for("apikeys.index"))


@bp.post("/<int:key_id>/nazwa")
@login_required
def rename(key_id):
    key = db.session.get(ApiKey, key_id)
    name = (request.form.get("name") or "").strip()
    if not key:
        flash("Nie znaleziono klucza.", "error")
        return redirect(url_for("apikeys.index"))
    if not name:
        flash("Podaj nową nazwę klucza.", "error")
        return redirect(url_for("apikeys.index"))
    if len(name) > NAME_MAX:
        flash(f"Nazwa klucza może mieć maks. {NAME_MAX} znaków.", "error")
        return redirect(url_for("apikeys.index"))
    key.name = name
    audit("update", "api_key", key.id, {"name": name})
    db.session.commit()
    flash(f"Zmieniono nazwę klucza na „{name}”.", "success")
    return redirect(url_for("apikeys.index"))


@bp.post("/<int:key_id>/usun")
@login_required
def delete(key_id):
    key = db.session.get(ApiKey, key_id)
    if not key:
        flash("Nie znaleziono klucza.", "error")
    else:
        # dokumenty klucza zachowują atrybucję i zostają dostępne przez API — klucz z dokumentami
        # można tylko dezaktywować (BE-18)
        used = Document.query.filter_by(api_key_id=key.id).count()
        if used:
            flash(f"Nie można usunąć klucza „{key.name}”: ma {used} dokument(ów). Zamiast usuwać, dezaktywuj go "
                  "— przestanie działać, a dokumenty zachowają powiązanie.", "error")
            return redirect(url_for("apikeys.index"))
        name = key.name
        try:
            audit("delete", "api_key", key.id, {"name": key.name})
            db.session.delete(key)
            db.session.commit()
            flash(f"Usunięto klucz „{name}”.", "success")
        except IntegrityError:  # równoległy upload tym kluczem
            db.session.rollback()
            flash("Nie można usunąć klucza — właśnie przyjęto nim dokument. Dezaktywuj go.", "error")
    return redirect(url_for("apikeys.index"))


# --- webhook przy kluczu (v0.9.0) — tylko administrator; sekret wyłącznie w jednorazowym alercie --------------------

@bp.post("/<int:key_id>/webhook")
@login_required
def webhook_set(key_id):
    _admin_or_403()
    key = _key_or_flash(key_id)
    if not key:
        return redirect(url_for("apikeys.index"))
    url = (request.form.get("url") or "").strip()
    if not url:
        flash("Podaj adres webhooka.", "error")
        return redirect(url_for("apikeys.index"))
    cfg = current_app.config
    try:
        target = validate_target(url, allow_http=bool(cfg.get("WEBHOOK_ALLOW_HTTP")),
                                 allowed_hosts=parse_allowed_hosts(cfg.get("WEBHOOK_ALLOWED_HOSTS") or ""),
                                 resolve=True)
    except TargetError as exc:
        flash(str(exc), "error")
        return redirect(url_for("apikeys.index"))
    secret = set_webhook_url(key, target.url)
    audit("update", "api_key", key.id, {"webhook_url": target.url})
    db.session.commit()
    flash(f"Zapisano adres webhooka klucza „{key.name}”.", "success")
    if not secret:
        return _render(None)
    return _no_store(_render(None, (key, secret)))


@bp.post("/<int:key_id>/webhook/wyczysc")
@login_required
def webhook_clear(key_id):
    _admin_or_403()
    key = _key_or_flash(key_id)
    if key:
        clear_webhook(key)
        audit("update", "api_key", key.id, {"webhook_url": None, "webhook_secret": "cleared"})
        db.session.commit()
        flash(f"Wyczyszczono webhook klucza „{key.name}”.", "success")
    return redirect(url_for("apikeys.index"))


@bp.post("/<int:key_id>/webhook/sekret")
@login_required
def webhook_rotate(key_id):
    _admin_or_403()
    key = _key_or_flash(key_id)
    if not key:
        return redirect(url_for("apikeys.index"))
    if not key.webhook_url:
        flash("Najpierw ustaw adres webhooka.", "error")
        return redirect(url_for("apikeys.index"))
    secret = rotate_webhook_secret(key)
    audit("update", "api_key", key.id, {"webhook_secret": "rotated"})  # sam fakt — nigdy wartość
    db.session.commit()
    flash(f"Wygenerowano nowy sekret webhooka klucza „{key.name}”.", "success")
    return _no_store(_render(None, (key, secret)))


@bp.post("/<int:key_id>/webhook/test")
@login_required
def webhook_test(key_id):
    _admin_or_403()
    key = _key_or_flash(key_id)
    if not key:
        return redirect(url_for("apikeys.index"))
    if not key.webhook_url:
        flash("Najpierw ustaw adres webhooka.", "error")
        return redirect(url_for("apikeys.index"))
    delivery = enqueue_test(key)
    db.session.flush()
    audit("create", "webhook_delivery", delivery.id, {"api_key_id": key.id, "event": EVENT_TEST})
    db.session.commit()  # send_now wymaga zacommitowanego wiersza
    result = send_now(delivery)
    if result.ok:
        flash(f"Zdarzenie testowe wysłane (HTTP {result.status_code}).", "success")
    else:
        flash(f"Zdarzenie testowe nieudane: {result.error}", "error")
    return redirect(url_for("apikeys.index"))


@bp.post("/dostawy/<int:delivery_id>/ponow")
@login_required
def delivery_retry(delivery_id):
    _admin_or_403()
    delivery = db.session.get(WebhookDelivery, delivery_id)
    if not delivery:
        flash("Nie znaleziono dostawy.", "error")
    elif delivery.status != WEBHOOK_FAILED:  # oczekującej (może właśnie się wysyła) ani wysłanej nie resetujemy
        flash("Ponowić można tylko nieudaną dostawę.", "error")
    else:
        audit("update", "webhook_delivery", delivery.id, {"api_key_id": delivery.api_key_id, "retry": True})
        retry(delivery)  # commituje razem z wpisem w historii; wyśle worker
        flash("Dostawa zaplanowana ponownie.", "success")
    return redirect(url_for("apikeys.index"))
