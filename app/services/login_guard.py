"""Limit nieudanych prób logowania (SEC-2) — liczony w bazie, więc wspólny dla wszystkich workerów gunicorna."""
from datetime import timedelta

from flask import current_app

from app.extensions import db
from app.models import LoginAttempt, utcnow


def _settings() -> tuple[int, timedelta]:
    cfg = current_app.config
    return int(cfg.get("LOGIN_MAX_ATTEMPTS", 5)), timedelta(minutes=int(cfg.get("LOGIN_LOCKOUT_MINUTES", 15)))


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()[:255]


def _norm_ip(ip: str | None) -> str:
    return (ip or "?")[:64]


def lockout_remaining(email: str, ip: str | None) -> int | None:
    """Liczba minut do końca blokady albo None, gdy logowanie jest dozwolone."""
    limit, window = _settings()
    if limit <= 0:
        return None
    since = utcnow() - window
    remaining = []
    for column, value in ((LoginAttempt.email, _norm_email(email)), (LoginAttempt.ip, _norm_ip(ip))):
        recent = (LoginAttempt.query.with_entities(LoginAttempt.created_at)
                  .filter(column == value, LoginAttempt.created_at > since)
                  .order_by(LoginAttempt.created_at.desc()).limit(limit).all())
        if len(recent) >= limit:
            # blokada trwa, dopóki najstarsza z ostatnich `limit` prób nie wyjdzie poza okno
            unlock_at = recent[-1][0] + window
            remaining.append(unlock_at - utcnow())
    if not remaining:
        return None
    return max(1, int(max(remaining).total_seconds() // 60) + 1)


def record_failure(email: str, ip: str | None) -> None:
    _, window = _settings()
    LoginAttempt.query.filter(LoginAttempt.created_at < utcnow() - window).delete(synchronize_session=False)
    db.session.add(LoginAttempt(email=_norm_email(email), ip=_norm_ip(ip)))


def clear_failures(email: str) -> None:
    LoginAttempt.query.filter_by(email=_norm_email(email)).delete(synchronize_session=False)
