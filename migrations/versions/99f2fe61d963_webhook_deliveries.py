"""webhook_deliveries: outbox webhooków (dostawy zdarzeń na adres klucza API)

Revision ID: 99f2fe61d963
Revises: d2c1e7a94f30
Create Date: 2026-10-12 12:00:00.000000

Nowa tabela `webhook_deliveries` (model `WebhookDelivery`, v0.9.0): jeden wiersz = jedno zdarzenie
(`document.status_changed`, `webhook.test`) do wysłania na `api_keys.webhook_url`; wysyła je worker z ponowieniami.
Kolumny `api_keys.webhook_url` / `webhook_secret` istnieją od migracji początkowej — tu ich nie ruszamy.

- Klucze obce: `api_key_id` z ON DELETE CASCADE (usunięcie klucza usuwa jego dostawy), `document_id` NULL-owalny
  i bez kaskady — dokumentu z dostawą nie da się usunąć (reset demo kasuje najpierw dostawy).
- Czasy (`created_at`, `next_attempt_at`, `sent_at`) w MariaDB/MySQL jako `DATETIME(6)` (keyset po created_at
  i lease workera potrzebują mikrosekund, jak w 86ccf8021da9); SQLite przechowuje mikrosekundy w zwykłym DATETIME.
- Indeksy jak w modelu: unikalny `uuid`, `document_id`, `status`, `next_attempt_at` oraz złożony
  (api_key_id, created_at, id) dla list — obsługuje on też klucz obcy api_key_id na InnoDB.
- Ponawialność (jak w 2eff54106035): na MariaDB DDL nie jest transakcyjny, więc po awarii w trakcie upgrade
  rewizja zostaje na poprzedniej. upgrade zakłada tabelę tylko, gdy jej nie ma, i każdy indeks tylko, gdy go
  brakuje; downgrade usuwa tabelę (z indeksami) tylko, gdy jest — ponowny `flask db upgrade` / `downgrade`
  jest bezpieczny.
- downgrade usuwa historię dostaw (niewysłane zdarzenia przepadają).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision = '99f2fe61d963'
down_revision = 'd2c1e7a94f30'
branch_labels = None
depends_on = None

TABLE = 'webhook_deliveries'
# (nazwa, kolumny, unikalny) — te same co w modelu WebhookDelivery
INDEXES = (
    ('ix_webhook_deliveries_uuid', ['uuid'], True),
    ('ix_webhook_deliveries_document_id', ['document_id'], False),
    ('ix_webhook_deliveries_status', ['status'], False),
    ('ix_webhook_deliveries_next_attempt_at', ['next_attempt_at'], False),
    ('ix_webhook_deliveries_api_key_created', ['api_key_id', 'created_at', 'id'], False),
)


def _precise_datetime():
    # jak PRECISE_DATETIME w app/models.py: mikrosekundy w MariaDB/MySQL, zwykły DATETIME gdzie indziej
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), 'mysql', 'mariadb')


def _tables(bind):
    # nowy inspektor przy każdym wywołaniu — bez cache, widzi bieżący stan schematu
    return set(sa.inspect(bind).get_table_names())


def _indexes(bind):
    return {i['name'] for i in sa.inspect(bind).get_indexes(TABLE)}


def upgrade():
    bind = op.get_bind()
    if TABLE not in _tables(bind):
        op.create_table(
            TABLE,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('uuid', sa.String(length=36), nullable=False),
            sa.Column('api_key_id', sa.Integer(), nullable=False),
            sa.Column('document_id', sa.Integer(), nullable=True),
            sa.Column('event', sa.String(length=64), nullable=False),
            sa.Column('payload', sa.JSON(), nullable=False),
            sa.Column('status', sa.String(length=16), nullable=False),
            sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
            sa.Column('next_attempt_at', _precise_datetime(), nullable=True),
            sa.Column('last_error', sa.Text(), nullable=True),
            sa.Column('last_status_code', sa.Integer(), nullable=True),
            sa.Column('created_at', _precise_datetime(), nullable=False),
            sa.Column('sent_at', _precise_datetime(), nullable=True),
            sa.ForeignKeyConstraint(['api_key_id'], ['api_keys.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['document_id'], ['documents.id']),
            sa.PrimaryKeyConstraint('id'),
        )
    existing = _indexes(bind)
    for name, columns, unique in INDEXES:
        if name not in existing:
            op.create_index(name, TABLE, columns, unique=unique)


def downgrade():
    if TABLE in _tables(op.get_bind()):
        op.drop_table(TABLE)
