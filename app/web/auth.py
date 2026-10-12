from datetime import timedelta
from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db
from app.models import AuditLog, User, utcnow
from app.services.accounts import password_problem
from app.services.audit import audit
from app.services.login_guard import clear_failures, discard_attempt, lockout_minutes, reserve_attempt

bp = Blueprint("auth", __name__)
# e-mail z formularza w dzienniku: wystarczy do identyfikacji, a nie daje atakującemu 255 znaków na wiersz
AUDIT_EMAIL_MAX = 100
BLOCKED_SCAN_LIMIT = 200


def _blocked_already_logged(ip: str) -> bool:
    """Czy w oknie blokady jest już wpis `login_blocked` z tego IP — jeden wpis na IP i okno, żeby odrzucane
    żądania nie dopisywały wiersza dziennika każde z osobna (wektor zapełnienia bazy)."""
    cfg = current_app.config
    window = timedelta(minutes=max(cfg["LOGIN_LOCKOUT_MINUTES"], cfg["LOGIN_EMAIL_LOCKOUT_MINUTES"]))
    recent = (AuditLog.query.filter(AuditLog.action == "login_blocked", AuditLog.created_at >= utcnow() - window)
              .order_by(AuditLog.id.desc()).limit(BLOCKED_SCAN_LIMIT).all())
    return any((row.payload or {}).get("ip") == ip for row in recent)


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
        ip = request.remote_addr or "?"
        # najpierw zapis próby, potem liczenie — równoległe żądania nie ominą limitu (SEC-2)
        attempt = reserve_attempt(email, ip)
        minutes = lockout_minutes(attempt)
        if minutes:
            discard_attempt(attempt)
            if not _blocked_already_logged(ip):
                audit("login_blocked", "user", None, {"email": email[:AUDIT_EMAIL_MAX], "ip": ip}, user="anonim")
            db.session.commit()
            flash(f"Zbyt wiele nieudanych prób logowania. Spróbuj ponownie za {minutes} min.", "error")
            return render_template("login.html"), 429
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(request.form.get("password") or ""):
            discard_attempt(attempt)
            clear_failures(email, ip)
            db.session.commit()
            session.permanent = True  # wygasa po PERMANENT_SESSION_LIFETIME
            login_user(user)
            return redirect(_safe_next(request.args.get("next")) or url_for("docs.dashboard"))
        audit("login_failed", "user", user.id if user else None, {"email": email[:AUDIT_EMAIL_MAX], "ip": ip},
              user="anonim")
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


@bp.route("/konto/haslo", methods=["GET", "POST"])
@login_required
def change_password():
    """Zmiana własnego hasła: wymaga obecnego hasła; `set_password` rotuje token sesji (inne sesje wylogowane),
    a bieżąca sesja dostaje nowy token przez ponowne `login_user`."""
    if request.method == "POST":
        current = request.form.get("current_password") or ""
        new, new2 = request.form.get("new_password") or "", request.form.get("new_password2") or ""
        problem = password_problem(new)
        if not current_user.check_password(current):
            flash("Obecne hasło jest nieprawidłowe.", "error")
        elif new != new2:
            flash("Nowe hasła nie są takie same.", "error")
        elif problem:
            flash(problem, "error")
        else:
            user = db.session.get(User, current_user.id)
            user.set_password(new)
            audit("password_change", "user", user.id, {}, user=user.email)
            db.session.commit()
            login_user(user)
            flash("Hasło zmienione. Pozostałe sesje tego konta zostały wylogowane.", "success")
            return redirect(url_for("docs.dashboard"))
    return render_template("password_change.html")
