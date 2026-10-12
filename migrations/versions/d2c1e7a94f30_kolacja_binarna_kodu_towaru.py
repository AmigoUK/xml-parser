"""kolacja binarna kodu towaru: products.code (MariaDB/MySQL)

Revision ID: d2c1e7a94f30
Revises: 2eff54106035
Create Date: 2026-10-11 16:40:00.000000

Produkcja działa na kolacji utf8mb4_unicode_ci (bez rozróżniania wielkości liter i akcentów, PAD SPACE), testy na
SQLite (porównania binarne). Kod aplikacji nie normalizuje `products.code` (w odróżnieniu od `units.code`,
`users.email`, `suppliers.tax_id` i kluczy sha256), więc na MariaDB `ABC-1`, `abc-1` i `ÁBC-1` były jednym kluczem:
import CSV z kodem `abc-1` nadpisywał po cichu towar `ABC-1`, a kartoteka i negocjacja zgłaszały „duplikat”.
Po migracji kolumna ma kolację utf8mb4_bin — porównania i unikat działają tak samo jak w SQLite i w testach.
Ten sam wariant deklaruje model (`Product.code`), więc `db.create_all()` i migracje dają ten sam schemat.

- SQLite: bez zmian (porównania binarne od zawsze).
- Ponawialność (jak w e4a1d7c03b52): ALTER TABLE na MariaDB nie jest transakcyjny — upgrade zmienia kolumnę tylko,
  gdy kolacja jest inna niż utf8mb4_bin, downgrade tylko, gdy jest utf8mb4_bin.
- downgrade przywraca kolację domyślną tabeli (MODIFY bez COLLATE) i nie powiedzie się, gdy w kartotece są kody
  różniące się tylko wielkością liter lub akcentami (duplikat klucza) — najpierw je scal.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd2c1e7a94f30'
down_revision = '2eff54106035'
branch_labels = None
depends_on = None

BINARY = 'utf8mb4_bin'


def _mysql() -> bool:
    return op.get_bind().dialect.name in ('mysql', 'mariadb')


def _code_collation():
    return op.get_bind().execute(sa.text(
        "SELECT COLLATION_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'products' AND COLUMN_NAME = 'code'")).scalar()


def upgrade():
    if _mysql() and _code_collation() != BINARY:
        op.execute(f'ALTER TABLE products MODIFY code VARCHAR(64) CHARACTER SET utf8mb4 COLLATE {BINARY} NOT NULL')


def downgrade():
    if _mysql() and _code_collation() == BINARY:
        op.execute('ALTER TABLE products MODIFY code VARCHAR(64) NOT NULL')  # kolacja domyślna tabeli
