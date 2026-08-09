"""monitored apis onboarded by api key

Revision ID: c41b7a92de05
Revises: dbe6fa71ee42
Create Date: 2026-08-09 10:12:44.118207

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c41b7a92de05'
down_revision: Union[str, Sequence[str], None] = 'dbe6fa71ee42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # New table only — no backfill needed, and known_endpoints is untouched
    # because a connection's endpoints are tagged via its existing `source`
    # column ("connection:<id>") rather than a new foreign key.
    op.create_table(
        'monitored_apis',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('base_url', sa.String(length=512), nullable=False),
        sa.Column('verify_path', sa.String(length=512), nullable=False, server_default='/'),
        sa.Column('credential_ciphertext', sa.Text(), nullable=False),
        sa.Column('key_prefix', sa.String(length=32), nullable=False),
        sa.Column('key_last4', sa.String(length=8), nullable=False, server_default=''),
        sa.Column('endpoints_registered', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='unverified'),
        sa.Column('last_checked_at', sa.DateTime(), nullable=True),
        sa.Column('last_check_detail', sa.String(length=512), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'name', name='uq_monitored_api_org_name'),
    )
    op.create_index(op.f('ix_monitored_apis_org_id'), 'monitored_apis', ['org_id'], unique=False)
    op.create_index(op.f('ix_monitored_apis_provider'), 'monitored_apis', ['provider'], unique=False)
    op.create_index(op.f('ix_monitored_apis_status'), 'monitored_apis', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_monitored_apis_status'), table_name='monitored_apis')
    op.drop_index(op.f('ix_monitored_apis_provider'), table_name='monitored_apis')
    op.drop_index(op.f('ix_monitored_apis_org_id'), table_name='monitored_apis')
    op.drop_table('monitored_apis')
