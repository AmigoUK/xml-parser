from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db
from app.models import User
from app.services.audit import audit
from app.services.login_guard import clear_failures, lockout_remaining, record_failure

bp = Blueprint("auth", __name__)


def _safe_next(target: str | None) -> str | None:
    """Zwraca lokalną ścieżkę albo None (ochrona przed open redirect, także `/\\evil.com`)."""
    if not target:
        return None
    target = target.replace("\\", "/")
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        ip = request.remote_addr
        minutes = lockout_remaining(email, ip)
        if minutes:
            audit("login_blocked", "user", None, {"email": email[:255], "ip": ip}, user="anonim")
            db.session.commit()
            flash(f"Zbyt wiele nieudanych prób logowania. Spróbuj ponownie za {minutes} min.", "error")
            return render_template("login.html"), 429
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(request.form.get("password") or ""):
            clear_failures(email)
            db.session.commit()
            session.permanent = True  # wygasa po PERMANENT_SESSION_LIFETIME
            login_user(user)
            return redirect(_safe_next(request.args.get("next")) or url_for("docs.dashboard"))
        record_failure(email, ip)
        audit("login_failed", "user", user.id if user else None, {"email": email[:255], "ip": ip}, user="anonim")
        db.session.commit()
        flash("Nieprawidłowy e-mail lub hasło.", "error")
    return render_template("login.html")


@bp.post("/logout")
@login_required
def logout():
    # nowy token sesji unieważnia wszystkie wcześniej wydane ciasteczka tego użytkownika (SEC-4)
    current_user.rotate_session_token()
    db.session.commit()
    logout_user()
    return redirect(url_for("auth.login"))
