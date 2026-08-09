"""add organizations and org_id

Revision ID: 178fc3029731
Revises: 9a7f36609dac
Create Date: 2026-08-07 04:28:49.339658

Three-step pattern for org_id on the eight tenant-scoped tables plus
api_keys: add nullable -> backfill via a bootstrapped "Default Organization"
-> alter to NOT NULL. This is safe to run against a populated production
table without a maintenance-window-length single transaction (unlike
adding a NOT NULL column with no default outright, which most DBs reject
or lock the whole table for). See docs/adr/002-multi-tenancy-schema.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.security import utc_now

# revision identifiers, used by Alembic.
revision: str = '178fc3029731'
down_revision: Union[str, Sequence[str], None] = '9a7f36609dac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every table that gets an org_id column in this migration.
_ORG_SCOPED_TABLES = (
    "alerts",
    "api_keys",
    "discovered_endpoints",
    "known_endpoints",
    "openapi_snapshots",
    "shadow_endpoints",
    "traffic_daily_summary",
    "traffic_events",
    "zombie_endpoint_state",
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. New tables
    # ------------------------------------------------------------------
    op.create_table(
        'org_memberships',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'org_id', name='uq_membership_user_org'),
    )
    with op.batch_alter_table('org_memberships', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_org_memberships_org_id'), ['org_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_org_memberships_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_org_memberships_user_id'), ['user_id'], unique=False)

    op.create_table(
        'organizations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('slug', sa.String(length=128), nullable=False),
        sa.Column('owner_user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug', name='uq_org_slug'),
    )
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_organizations_slug'), ['slug'], unique=False)

    # ------------------------------------------------------------------
    # 2. org_id, nullable for now — existing rows have none yet.
    # ------------------------------------------------------------------
    for table in _ORG_SCOPED_TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('org_id', sa.Integer(), nullable=True))

    # ------------------------------------------------------------------
    # 3. Backfill: one "Default Organization", owned by the earliest admin
    # user (or the earliest user of any role, if somehow no admin exists —
    # a fresh install with zero users just skips this entirely and relies
    # on ensure_default_organization() at app startup instead).
    # ------------------------------------------------------------------
    bind = op.get_bind()
    now = utc_now()

    admin_id = bind.execute(
        sa.text("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1")
    ).scalar()
    if admin_id is None:
        admin_id = bind.execute(sa.text("SELECT id FROM users ORDER BY id LIMIT 1")).scalar()

    if admin_id is not None:
        # Raw SQL + a follow-up SELECT rather than relying on
        # inserted_primary_key, which isn't reliably populated for a plain
        # sa.text()/sa.table() insert on every backend.
        bind.execute(
            sa.text(
                "INSERT INTO organizations (name, slug, owner_user_id, created_at) "
                "VALUES (:name, :slug, :owner, :now)"
            ),
            {"name": "Default Organization", "slug": "default", "owner": admin_id, "now": now},
        )
        default_org_id = bind.execute(
            sa.text("SELECT id FROM organizations WHERE slug = 'default' ORDER BY id DESC LIMIT 1")
        ).scalar()

        for user_id, user_role in bind.execute(sa.text("SELECT id, role FROM users")).fetchall():
            org_role = "owner" if user_role == "admin" else user_role
            bind.execute(
                sa.text(
                    "INSERT INTO org_memberships (user_id, org_id, role, status, created_at, decided_at) "
                    "VALUES (:user_id, :org_id, :role, 'active', :now, :now)"
                ),
                {"user_id": user_id, "org_id": default_org_id, "role": org_role, "now": now},
            )

        for table in _ORG_SCOPED_TABLES:
            bind.execute(sa.text(f"UPDATE {table} SET org_id = :org_id WHERE org_id IS NULL"), {"org_id": default_org_id})

    # ------------------------------------------------------------------
    # 4. org_id NOT NULL, plus the per-table indexes/constraints that
    # depend on it now being populated.
    # ------------------------------------------------------------------
    with op.batch_alter_table('alerts', schema=None) as batch_op:
        batch_op.alter_column('org_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_index(batch_op.f('ix_alerts_org_id'), ['org_id'], unique=False)

    with op.batch_alter_table('api_keys', schema=None) as batch_op:
        batch_op.alter_column('org_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_index(batch_op.f('ix_api_keys_org_id'), ['org_id'], unique=False)

    with op.batch_alter_table('discovered_endpoints', schema=None) as batch_op:
        batch_op.alter_column('org_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_index(batch_op.f('uq_disc_method_path'))
        batch_op.create_index(
            'uq_disc_method_path', ['org_id', 'method', 'path_normalized'],
            unique=True, mysql_length={'path_normalized': 191},
        )
        batch_op.create_index(batch_op.f('ix_discovered_endpoints_org_id'), ['org_id'], unique=False)

    with op.batch_alter_table('known_endpoints', schema=None) as batch_op:
        batch_op.alter_column('org_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_constraint(batch_op.f('uq_known_method_path'), type_='unique')
        batch_op.create_unique_constraint('uq_known_method_path', ['org_id', 'method', 'path_template'])
        batch_op.create_index(batch_op.f('ix_known_endpoints_org_id'), ['org_id'], unique=False)

    with op.batch_alter_table('openapi_snapshots', schema=None) as batch_op:
        batch_op.alter_column('org_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_index(batch_op.f('ix_openapi_snapshots_org_id'), ['org_id'], unique=False)

    with op.batch_alter_table('shadow_endpoints', schema=None) as batch_op:
        batch_op.alter_column('org_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_index(batch_op.f('ix_shadow_method_path'))
        batch_op.create_index(
            'ix_shadow_method_path', ['org_id', 'method', 'path_normalized'],
            unique=True, mysql_length={'path_normalized': 191},
        )
        batch_op.create_index(batch_op.f('ix_shadow_endpoints_org_id'), ['org_id'], unique=False)

    with op.batch_alter_table('traffic_daily_summary', schema=None) as batch_op:
        batch_op.alter_column('org_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_index(batch_op.f('uq_summary_day_method_path'))
        batch_op.create_index(
            'uq_summary_day_method_path', ['org_id', 'day', 'method', 'path_normalized'],
            unique=True, mysql_length={'path_normalized': 191},
        )
        batch_op.create_index(batch_op.f('ix_traffic_daily_summary_org_id'), ['org_id'], unique=False)

    with op.batch_alter_table('traffic_events', schema=None) as batch_op:
        batch_op.alter_column('org_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_index(batch_op.f('ix_traffic_events_org_id'), ['org_id'], unique=False)
        batch_op.create_index('ix_traffic_org_ts', ['org_id', 'ts'], unique=False)

    with op.batch_alter_table('zombie_endpoint_state', schema=None) as batch_op:
        batch_op.alter_column('org_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_constraint(batch_op.f('uq_zombie_method_path'), type_='unique')
        batch_op.create_unique_constraint('uq_zombie_method_path', ['org_id', 'method', 'path_template'])
        batch_op.create_index(batch_op.f('ix_zombie_endpoint_state_org_id'), ['org_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('zombie_endpoint_state', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_zombie_endpoint_state_org_id'))
        batch_op.drop_constraint('uq_zombie_method_path', type_='unique')
        batch_op.create_unique_constraint(batch_op.f('uq_zombie_method_path'), ['method', 'path_template'])
        batch_op.drop_column('org_id')

    with op.batch_alter_table('traffic_events', schema=None) as batch_op:
        batch_op.drop_index('ix_traffic_org_ts')
        batch_op.drop_index(batch_op.f('ix_traffic_events_org_id'))
        batch_op.drop_column('org_id')

    with op.batch_alter_table('traffic_daily_summary', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_traffic_daily_summary_org_id'))
        batch_op.drop_index('uq_summary_day_method_path', mysql_length={'path_normalized': 191})
        batch_op.create_index(batch_op.f('uq_summary_day_method_path'), ['day', 'method', 'path_normalized'], unique=1)
        batch_op.drop_column('org_id')

    with op.batch_alter_table('shadow_endpoints', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_shadow_endpoints_org_id'))
        batch_op.drop_index('ix_shadow_method_path', mysql_length={'path_normalized': 191})
        batch_op.create_index(batch_op.f('ix_shadow_method_path'), ['method', 'path_normalized'], unique=1)
        batch_op.drop_column('org_id')

    with op.batch_alter_table('openapi_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_openapi_snapshots_org_id'))
        batch_op.drop_column('org_id')

    with op.batch_alter_table('known_endpoints', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_known_endpoints_org_id'))
        batch_op.drop_constraint('uq_known_method_path', type_='unique')
        batch_op.create_unique_constraint(batch_op.f('uq_known_method_path'), ['method', 'path_template'])
        batch_op.drop_column('org_id')

    with op.batch_alter_table('discovered_endpoints', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_discovered_endpoints_org_id'))
        batch_op.drop_index('uq_disc_method_path', mysql_length={'path_normalized': 191})
        batch_op.create_index(batch_op.f('uq_disc_method_path'), ['method', 'path_normalized'], unique=1)
        batch_op.drop_column('org_id')

    with op.batch_alter_table('api_keys', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_api_keys_org_id'))
        batch_op.drop_column('org_id')

    with op.batch_alter_table('alerts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_alerts_org_id'))
        batch_op.drop_column('org_id')

    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_organizations_slug'))

    op.drop_table('organizations')
    with op.batch_alter_table('org_memberships', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_org_memberships_user_id'))
        batch_op.drop_index(batch_op.f('ix_org_memberships_status'))
        batch_op.drop_index(batch_op.f('ix_org_memberships_org_id'))

    op.drop_table('org_memberships')
