from datetime import timedelta

from flask import has_request_context
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog, utcnow

# wpisy generowane przez nieuwierzytelnionych klientów — jedyne, które rosną z ruchem, a nie z pracą operatora
LOGIN_ACTIONS = ("login_failed", "login_blocked")


def audit(action: str, entity: str, entity_id: int | None, payload: dict | None = None,
          user: str | None = None) -> None:
    if user is None and has_request_context() and getattr(current_user, "is_authenticated", False):
        user = current_user.email
    db.session.add(AuditLog(user=user or "system", action=action, entity=entity, entity_id=entity_id,
                            payload=payload or {}))


def prune_audit(days: int, all_actions: bool = False) -> int:
    """Usuwa wpisy dziennika starsze niż `days` dni: domyślnie tylko nieudane/zablokowane logowania (wektor
    zapełnienia bazy przez każdego, kto widzi /login), z `all_actions` — wszystkie. Zwraca liczbę usuniętych;
    bez commitu."""
    if days < 1:
        raise ValueError("Retencja musi wynosić co najmniej 1 dzień.")
    q = AuditLog.query.filter(AuditLog.created_at < utcnow() - timedelta(days=days))
    if not all_actions:
        q = q.filter(AuditLog.action.in_(LOGIN_ACTIONS))
    return q.delete(synchronize_session=False)
