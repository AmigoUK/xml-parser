from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user

from app.models import User

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
        user = User.query.filter_by(email=(request.form.get("email") or "").strip().lower()).first()
        if user and user.check_password(request.form.get("password") or ""):
            login_user(user)
            return redirect(_safe_next(request.args.get("next")) or url_for("docs.dashboard"))
        flash("Nieprawidłowy e-mail lub hasło.", "error")
    return render_template("login.html")


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
