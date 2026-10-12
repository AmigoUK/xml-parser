from flask import Blueprint, render_template
from flask_login import login_required

from app.models import AuditLog

bp = Blueprint("history", __name__, url_prefix="/historia")
HISTORY_LIMIT = 300  # ostatnie wpisy dziennika pokazywane w panelu


@bp.get("")
@login_required
def index():
    return render_template("history.html", rows=AuditLog.query.order_by(AuditLog.id.desc()).limit(HISTORY_LIMIT).all())
