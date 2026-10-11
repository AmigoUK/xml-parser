"""indeks listy synchronizacji API: documents (api_key_id, updated_at, id)

Revision ID: 2eff54106035
Revises: 86ccf8021da9
Create Date: 2026-10-11 08:21:17.000000

Tryb synchronizacji `GET /api/v1/documents` (`updated_since` / `cursor`) czyta dokumenty jednego klucza API rosnąco
po (updated_at, id) od pozycji kursora (keyset). Indeks złożony (api_key_id, updated_at, id) obsługuje filtr klucza,
warunek keyset i sortowanie. Ten sam indeks deklaruje model (`Document.__table_args__`), więc `db.create_all()`
i migracje dają ten sam schemat. Działa tak samo na SQLite i MariaDB.

- Ponawialność (jak w e4a1d7c03b52): na MariaDB DDL nie jest transakcyjny, więc po awarii między CREATE INDEX
  a wpisem do alembic_version rewizja zostaje na poprzedniej. upgrade zakłada indeks tylko, gdy go nie ma,
  a downgrade usuwa go tylko, gdy jest — ponowny `flask db upgrade` / `flask db downgrade` jest bezpieczny.
- downgrade nie narusza klucza obcego api_key_id: InnoDB nadal ma dla niego indeks
  `ix_documents_api_status_created` (api_key_id na pierwszej pozycji).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2eff54106035'
down_revision = '86ccf8021da9'
branch_labels = None
depends_on = None

TABLE = 'documents'
INDEX = 'ix_documents_api_key_updated'
COLUMNS = ['api_key_id', 'updated_at', 'id']


def _index(bind, table, name):
    # nowy inspektor przy każdym wywołaniu — bez cache, widzi bieżący stan schematu
    return next((i for i in sa.inspect(bind).get_indexes(table) if i['name'] == name), None)


def upgrade():
    if _index(op.get_bind(), TABLE, INDEX) is None:
        op.create_index(INDEX, TABLE, COLUMNS)


def downgrade():
    if _index(op.get_bind(), TABLE, INDEX) is not None:
        op.drop_index(INDEX, table_name=TABLE)
