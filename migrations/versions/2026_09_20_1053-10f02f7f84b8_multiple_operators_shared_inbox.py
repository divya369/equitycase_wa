"""multiple operators: shared inbox

Drops the "operator is a single row" rule, gives operator.id a sequence, and
attaches OTP codes and FCM devices to one operator each. Existing rows belong
to the seeded operator (id = 1).

Revision ID: 10f02f7f84b8
Revises: 87f4abbdf85f
Create Date: 2026-09-20 10:53:29.844329

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '10f02f7f84b8'
down_revision: Union[str, Sequence[str], None] = '87f4abbdf85f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEEDED_OPERATOR_ID = 1


def upgrade() -> None:
    """Upgrade schema."""
    # operator: many rows, ids handed out by a sequence
    op.drop_constraint('ck_operator_singleton', 'operator', type_='check')
    op.execute('CREATE SEQUENCE IF NOT EXISTS operator_id_seq AS smallint OWNED BY operator.id')
    op.execute("ALTER TABLE operator ALTER COLUMN id SET DEFAULT nextval('operator_id_seq')")
    # the seeded row already uses id = 1, so start handing out ids after it
    op.execute("SELECT setval('operator_id_seq', COALESCE((SELECT MAX(id) FROM operator), 1))")

    # fcm_tokens.operator_id — existing devices belong to the seeded operator
    op.add_column('fcm_tokens', sa.Column('operator_id', sa.SmallInteger(), nullable=True))
    op.execute(f'UPDATE fcm_tokens SET operator_id = {SEEDED_OPERATOR_ID} WHERE operator_id IS NULL')
    op.alter_column('fcm_tokens', 'operator_id', nullable=False)
    op.create_index(op.f('ix_fcm_tokens_operator_id'), 'fcm_tokens', ['operator_id'], unique=False)
    op.create_foreign_key('fk_fcm_tokens_operator', 'fcm_tokens', 'operator', ['operator_id'], ['id'], ondelete='CASCADE')

    # otp_codes.operator_id — pending codes were for the seeded operator
    op.add_column('otp_codes', sa.Column('operator_id', sa.SmallInteger(), nullable=True))
    op.execute(f'UPDATE otp_codes SET operator_id = {SEEDED_OPERATOR_ID} WHERE operator_id IS NULL')
    op.alter_column('otp_codes', 'operator_id', nullable=False)
    op.drop_index(op.f('ix_otp_codes_created_at'), table_name='otp_codes')
    op.create_index('ix_otp_codes_operator_created', 'otp_codes', ['operator_id', 'created_at'], unique=False)
    op.create_foreign_key('fk_otp_codes_operator', 'otp_codes', 'operator', ['operator_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_otp_codes_operator', 'otp_codes', type_='foreignkey')
    op.drop_index('ix_otp_codes_operator_created', table_name='otp_codes')
    op.create_index(op.f('ix_otp_codes_created_at'), 'otp_codes', ['created_at'], unique=False)
    op.drop_column('otp_codes', 'operator_id')

    op.drop_constraint('fk_fcm_tokens_operator', 'fcm_tokens', type_='foreignkey')
    op.drop_index(op.f('ix_fcm_tokens_operator_id'), table_name='fcm_tokens')
    op.drop_column('fcm_tokens', 'operator_id')

    # back to one operator: the extra ones must go first
    op.execute(f'DELETE FROM operator WHERE id <> {SEEDED_OPERATOR_ID}')
    op.execute('ALTER TABLE operator ALTER COLUMN id SET DEFAULT 1')
    op.execute('DROP SEQUENCE IF EXISTS operator_id_seq')
    op.create_check_constraint('ck_operator_singleton', 'operator', 'id = 1')
