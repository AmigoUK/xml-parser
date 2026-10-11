"""mikrosekundy w czasie dokumentów: documents.created_at i documents.updated_at jako DATETIME(6)

Revision ID: 86ccf8021da9
Revises: e4a1d7c03b52
Create Date: 2026-10-11 07:35:46.000000

Stronicowanie listy dokumentów w API (keyset po (updated_at, id)) potrzebuje czasu dokładniejszego niż sekunda:
przy precyzji sekund wiele dokumentów ma identyczny updated_at. W MariaDB/MySQL obie kolumny były `DATETIME`
(DATETIME_PRECISION = 0); migracja zmienia je na `DATETIME(6)`. SQLite przechowuje mikrosekundy bez zmiany
typu, więc tam (i na innych silnikach) migracja tylko przesuwa rewizję.

- Jedno `ALTER TABLE documents MODIFY …` obejmuje obie kolumny, czyli jedną przebudowę tabeli — przy dużej bazie
  wykonaj ją po kopii zapasowej (`tools/backup.sh`), poza godzinami pracy. Indeksy (`ix_documents_created_at`,
  `ix_documents_api_status_created`) zostają, a istniejące wartości zachowują sekundy (`.000000`).
- Kolumny są NULL-owalne i nie mają w bazie wartości domyślnej (czas nadaje aplikacja: default, onupdate,
  `touch()`), więc `MODIFY` powtarza tylko `NULL` — niczego innego nie trzeba przepisywać.
- Ponawialność (jak w e4a1d7c03b52): na MariaDB DDL nie jest transakcyjny, więc po awarii między ALTER a wpisem
  do alembic_version rewizja zostaje na poprzedniej. Migracja czyta aktualną precyzję z information_schema
  i zmienia tylko kolumny, które jej jeszcze nie mają — ponowny `flask db upgrade` jest bezpieczny.
- downgrade przywraca `DATETIME` (precyzja 0) kolumnom z precyzją ≠ 0. **Ułamki sekund są obcinane** (MariaDB
  przy domyślnym sql_mode obcina, nie zaokrągla), więc po cofnięciu nie da się już odróżnić kolejności zmian
  w obrębie jednej sekundy.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '86ccf8021da9'
down_revision = 'e4a1d7c03b52'
branch_labels = None
depends_on = None

# stałe z kodu — nazwy trafiają bezpośrednio do ALTER TABLE (nigdy z wejścia)
TIME_COLUMNS = ('created_at', 'updated_at')
MICROSECONDS = 6
SECONDS = 0


def _precision(bind):
    """{kolumna: DATETIME_PRECISION} dla documents.created_at / updated_at (information_schema, bieżąca baza)."""
    query = sa.text("SELECT COLUMN_NAME, DATETIME_PRECISION FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME IN :columns"
                    ).bindparams(sa.bindparam('columns', expanding=True))
    rows = bind.execute(query, {'table': 'documents', 'columns': list(TIME_COLUMNS)})
    return {name: precision for name, precision in rows}


def _modify(columns, definition):
    """Jedno ALTER TABLE (jedna przebudowa tabeli) dla wskazanych kolumn; brak kolumn = nic do zrobienia."""
    if columns:
        clauses = ', '.join(f'MODIFY {name} {definition} NULL' for name in columns)
        op.execute(sa.text(f'ALTER TABLE documents {clauses}'))


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name not in ('mysql', 'mariadb'):
        return  # SQLite przechowuje mikrosekundy bez zmiany typu
    precision = _precision(bind)
    _modify([c for c in TIME_COLUMNS if precision.get(c) != MICROSECONDS], f'DATETIME({MICROSECONDS})')


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name not in ('mysql', 'mariadb'):
        return
    precision = _precision(bind)
    _modify([c for c in TIME_COLUMNS if precision.get(c) != SECONDS], 'DATETIME')
