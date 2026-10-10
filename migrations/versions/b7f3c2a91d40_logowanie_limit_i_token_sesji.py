"""limit prób logowania (login_attempts) i token sesji użytkownika (users.session_token)

Revision ID: b7f3c2a91d40
Revises: 3c7d2a91e5b4
Create Date: 2026-10-10 23:00:00.000000

"""
import secrets

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7f3c2a91d40'
down_revision = '3c7d2a91e5b4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('login_attempts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('login_attempts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_login_attempts_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_login_attempts_email'), ['email'], unique=False)
        batch_op.create_index(batch_op.f('ix_login_attempts_ip'), ['ip'], unique=False)

    # kolumna najpierw nullable, wypełniona losowym tokenem per użytkownik, potem NOT NULL
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('session_token', sa.String(length=64), nullable=True))
    conn = op.get_bind()
    users = sa.table('users', sa.column('id', sa.Integer), sa.column('session_token', sa.String))
    for (uid,) in conn.execute(sa.select(users.c.id)).fetchall():
        conn.execute(users.update().where(users.c.id == uid).values(session_token=secrets.token_hex(16)))
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('session_token', existing_type=sa.String(length=64), nullable=False)


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('session_token')

    with op.batch_alter_table('login_attempts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_login_attempts_ip'))
        batch_op.drop_index(batch_op.f('ix_login_attempts_email'))
        batch_op.drop_index(batch_op.f('ix_login_attempts_created_at'))

    op.drop_table('login_attempts')
