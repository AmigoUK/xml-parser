from flask import Blueprint, render_template, request
from flask_login import login_required

from app.extensions import db
from app.models import AuditLog

from .paging import cursor_arg, page_by_id, page_context

bp = Blueprint("history", __name__, url_prefix="/historia")
HISTORY_LIMIT = 300  # rozmiar strony dziennika w panelu
HISTORY_USERS_LIMIT = 200  # maks. pozycji listy użytkowników w filtrze

# czytelne etykiety akcji dziennika — każda akcja przekazywana do audit() w app/ (pilnuje tego test skanujący źródła)
ACTION_LABELS = {
    "ingest": "Przyjęcie dokumentu",
    "restore": "Przywrócenie",
    "edit": "Zmiana szablonu",
    "edit_draft": "Zmiana reguł roboczych dokumentu",
    "create": "Dodanie",
    "update": "Zmiana",
    "delete": "Usunięcie",
    "toggle": "Włączenie / wyłączenie",
    "import": "Import CSV",
    "reset": "Reset demo",
    "login_failed": "Nieudane logowanie",
    "login_blocked": "Zablokowane logowanie",
    "password_change": "Zmiana hasła",
    "password_set": "Ustawienie hasła",
    "resolve:create_supplier": "Wyjaśnienie: utworzenie dostawcy",
    "resolve:use_supplier": "Wyjaśnienie: wskazanie dostawcy",
    "resolve:map_field": "Wyjaśnienie: mapowanie pola",
    "resolve:map_unit": "Wyjaśnienie: mapowanie jednostki",
    "resolve:add_conversion": "Wyjaśnienie: dodanie przelicznika",
    "resolve:map_product": "Wyjaśnienie: mapowanie towaru",
    "resolve:create_product": "Wyjaśnienie: utworzenie towaru",
    "resolve:allow_duplicate": "Wyjaśnienie: zgoda na duplikat",
    "resolve:reject": "Wyjaśnienie: odrzucenie dokumentu",
}
_ACTION_MAX = AuditLog.action.type.length
_USER_MAX = AuditLog.user.type.length


@bp.get("")
@login_required
def index():
    query = AuditLog.query
    action = (request.args.get("action") or "").strip()[:_ACTION_MAX]
    if action:
        query = query.filter(AuditLog.action == action)
    user = (request.args.get("user") or "").strip()[:_USER_MAX]
    if user:
        query = query.filter(AuditLog.user == user)
    rows, cursor = page_by_id(query, AuditLog.id, HISTORY_LIMIT, before=cursor_arg("before"))
    users = [u for (u,) in db.session.query(AuditLog.user).filter(AuditLog.user.isnot(None)).distinct()
             .order_by(AuditLog.user).limit(HISTORY_USERS_LIMIT)]
    return render_template(
        "history.html", rows=rows, labels=ACTION_LABELS, actions=list(ACTION_LABELS.items()),
        users=users, action=action, user=user, **page_context(rows, cursor, "before"))
