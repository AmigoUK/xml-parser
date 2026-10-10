from flask import has_request_context
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog


def audit(action: str, entity: str, entity_id: int | None, payload: dict | None = None,
          user: str | None = None) -> None:
    if user is None and has_request_context() and getattr(current_user, "is_authenticated", False):
        user = current_user.email
    db.session.add(AuditLog(user=user or "system", action=action, entity=entity, entity_id=entity_id,
                            payload=payload or {}))
