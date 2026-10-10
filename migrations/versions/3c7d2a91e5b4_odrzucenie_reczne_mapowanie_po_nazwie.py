"""odrzucenie ręczne i mapowanie towaru po nazwie (pakiet D)

Revision ID: 3c7d2a91e5b4
Revises: 96049e3e3e09
Create Date: 2026-10-10 23:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3c7d2a91e5b4'
down_revision = '96049e3e3e09'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('rejected_by', sa.String(length=255), nullable=True))
    with op.batch_alter_table('product_mappings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('supplier_name_norm', sa.String(length=255), nullable=True))
    # Dotychczasowe odrzucenia bez błędu odczytu to decyzje operatora (automatyczne mają `error`).
    op.execute("UPDATE documents SET rejected_by = '(przed migracją)' "
               "WHERE status = 'rejected' AND error IS NULL")


def downgrade():
    with op.batch_alter_table('product_mappings', schema=None) as batch_op:
        batch_op.drop_column('supplier_name_norm')
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_column('rejected_by')
