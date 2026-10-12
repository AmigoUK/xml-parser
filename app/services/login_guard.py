"""Limit prób logowania (SEC-2) — liczony w bazie, więc wspólny dla wszystkich workerów gunicorna.

Zasady (konfigurowalne w Config):
- główny limit per para (e-mail, IP): LOGIN_MAX_ATTEMPTS w oknie LOGIN_LOCKOUT_MINUTES;
- per adres IP (wiele e-maili z jednego IP): LOGIN_MAX_ATTEMPTS_PER_IP w tym samym oknie;
- per sam e-mail (z dowolnych IP): znacznie wyższy próg LOGIN_MAX_ATTEMPTS_PER_EMAIL w krótszym oknie
  LOGIN_EMAIL_LOCKOUT_MINUTES — obcy bez hasła nie zablokuje konta 5 próbami, a rozproszony atak
  z wielu IP i tak zostanie spowolniony.

Wyścig (wiele równoległych prób): próba jest najpierw ZAPISYWANA (i zatwierdzana), a dopiero potem liczona
(insert-then-count). Każde żądanie widzi co najmniej wszystkie próby zatwierdzone przed nim, więc z burstu
N równoległych żądań hasło sprawdzi co najwyżej tyle, ile wynosi limit. Próby odrzucone blokadą są usuwane,
żeby nie przedłużały blokady i nie wliczały się do limitów innych zakresów.
"""
from dataclasses import dataclass
from datetime import timedelta

from flask import current_app

from app.extensions import db
from app.models import LoginAttempt, utcnow


@dataclass
class Rule:
    limit: int
    window: timedelta
    filters: tuple


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()[:LoginAttempt.email.type.length]


def _norm_ip(ip: str | None) -> str:
    return (ip or "?")[:LoginAttempt.ip.type.length]


def _rules(email: str, ip: str) -> list[Rule]:
    cfg = current_app.config  # wartości domyślne wyłącznie w Config (jedno źródło)
    window = timedelta(minutes=int(cfg["LOGIN_LOCKOUT_MINUTES"]))
    email_window = timedelta(minutes=int(cfg["LOGIN_EMAIL_LOCKOUT_MINUTES"]))
    return [
        Rule(int(cfg["LOGIN_MAX_ATTEMPTS"]), window, (LoginAttempt.email == email, LoginAttempt.ip == ip)),
        Rule(int(cfg["LOGIN_MAX_ATTEMPTS_PER_IP"]), window, (LoginAttempt.ip == ip,)),
        Rule(int(cfg["LOGIN_MAX_ATTEMPTS_PER_EMAIL"]), email_window, (LoginAttempt.email == email,)),
    ]


def reserve_attempt(email: str, ip: str | None) -> LoginAttempt:
    """Zapisuje próbę logowania przed sprawdzeniem hasła (zatwierdza transakcję)."""
    longest = max(r.window for r in _rules(_norm_email(email), _norm_ip(ip)))
    LoginAttempt.query.filter(LoginAttempt.created_at < utcnow() - longest).delete(synchronize_session=False)
    attempt = LoginAttempt(email=_norm_email(email), ip=_norm_ip(ip), created_at=utcnow())
    db.session.add(attempt)
    db.session.commit()
    return attempt


def lockout_minutes(attempt: LoginAttempt) -> int | None:
    """Po zapisaniu próby: liczba minut blokady albo None, gdy wolno sprawdzić hasło.

    Liczy próby łącznie z bieżącą — blokada, gdy jest ich więcej niż limit."""
    now = utcnow()
    remaining = []
    for rule in _rules(attempt.email, attempt.ip):
        if rule.limit <= 0:
            continue
        rows = (LoginAttempt.query.with_entities(LoginAttempt.created_at)
                .filter(*rule.filters, LoginAttempt.created_at > now - rule.window, LoginAttempt.id != attempt.id)
                .order_by(LoginAttempt.created_at.desc()).limit(rule.limit).all())
        if len(rows) >= rule.limit:
            # zwolni się, gdy najstarsza z ostatnich `limit` prób wyjdzie poza okno
            remaining.append(rows[-1][0] + rule.window - now)
    if not remaining:
        return None
    return max(1, int(max(remaining).total_seconds() // 60) + 1)


def discard_attempt(attempt: LoginAttempt) -> None:
    """Usuwa próbę, która nie powinna się liczyć (zablokowana albo udana)."""
    LoginAttempt.query.filter_by(id=attempt.id).delete(synchronize_session=False)


def clear_failures(email: str, ip: str | None) -> None:
    """Po udanym logowaniu: kasuje nieudane próby tej pary (e-mail, IP)."""
    LoginAttempt.query.filter_by(email=_norm_email(email), ip=_norm_ip(ip)).delete(synchronize_session=False)
