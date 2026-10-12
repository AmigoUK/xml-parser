"""Konta operatorów: polityka haseł i ustawianie hasła administratora (seed, CLI `flask set-admin-password`,
widok „Zmień hasło”). Jedna reguła dla wszystkich ścieżek."""
from __future__ import annotations

from app.extensions import db
from app.models import User
from app.services.audit import audit

PASSWORD_MIN_LENGTH = 10
PLACEHOLDER_PASSWORDS = {"zmien-mnie", "change-me", "admin", "password"}
PASSWORD_RULE = (f"Hasło musi mieć co najmniej {PASSWORD_MIN_LENGTH} znaków i nie może być hasłem przykładowym "
                 "(np. zmien-mnie, admin, password).")


def password_problem(password: str | None) -> str | None:
    """Komunikat, dlaczego hasło jest za słabe, albo None, gdy spełnia politykę."""
    pw = password or ""
    if len(pw) < PASSWORD_MIN_LENGTH or pw.lower() in PLACEHOLDER_PASSWORDS:
        return PASSWORD_RULE
    return None


def set_admin_password(email: str, password: str, actor: str | None = None) -> tuple[User, bool]:
    """Ustawia hasło konta (tworzy konto admina, gdy go nie ma). `set_password` rotuje token sesji, więc wszystkie
    wydane ciasteczka sesji tego konta przestają działać. Zwraca (użytkownik, czy_utworzono); bez commitu."""
    email = (email or "").strip().lower()
    if not email:
        raise ValueError("Brak adresu e-mail konta.")
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    user = User.query.filter_by(email=email).first()
    created = user is None
    if created:
        user = User(email=email, role="admin")
        db.session.add(user)
    user.set_password(password)
    db.session.flush()
    audit("password_set", "user", user.id, {"email": email, "created": created}, user=actor or "system")
    return user, created
