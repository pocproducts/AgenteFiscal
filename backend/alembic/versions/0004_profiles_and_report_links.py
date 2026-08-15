"""profiles + report/token/conversation links

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-14 10:00:00.000000

Introduces the first-class tenant-scoped ``profiles`` identity and links the
report/token/conversation tables to it.

- ``profiles`` — new table. A profile is a tenant-scoped system identity that
  aggregates reports, token spend and activity (NOT ``clients``, NOT a browser
  mock). Enforced at the API boundary: NO report generation without an ACTIVE
  profile of the current tenant.
- ``clients`` — gains ``UNIQUE(tenant_id, id)`` (``uq_clients_tenant_id``) as
  the prerequisite for the composite FK on ``report_runs`` that pins a run to
  the same tenant as its client.
- ``report_runs`` — gains ``profile_id`` (NOT NULL, FK RESTRICT, required), a
  composite FK ``fk_report_runs_client_tenant`` -> ``clients(tenant_id, id)``
  (tenant-consistency for ``client_id``), ``user_id`` (FK users SET NULL),
  ``period_year`` / ``period_month`` (Integer, denormalised from period), and
  indexes on ``cuit`` and ``(tenant_id, profile_id)``. Rows with a NULL
  profile are purged before the column turns NOT NULL.
- ``token_transactions`` — gains nullable ``profile_id`` (FK SET NULL) + index.
- ``conversations`` — gains nullable ``profile_id`` (FK SET NULL) + index.

Downgrade reverses everything in the opposite order.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ── profiles ──────────────────────────────────────────────────────────
    op.create_table(
        'profiles',
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('cuit', sa.String(length=11), nullable=True),
        sa.Column('status', sa.String(length=32), server_default='active', nullable=False),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name=op.f('ck_profiles_profiles_status_check')),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_profiles_created_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_profiles_tenant_id_tenants'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_profiles')),
        sa.UniqueConstraint('tenant_id', 'cuit', name='uq_profiles_tenant_cuit')
    )
    op.create_index('ix_profiles_tenant_id', 'profiles', ['tenant_id'], unique=False)
    op.create_index('ix_profiles_tenant_status', 'profiles', ['tenant_id', 'status'], unique=False)
    op.create_index('ix_profiles_created_by', 'profiles', ['created_by'], unique=False)

    # ── clients: UNIQUE(tenant_id, id) — prerequisite for the composite FK ──
    op.create_unique_constraint('uq_clients_tenant_id', 'clients', ['tenant_id', 'id'])

    # ── report_runs ───────────────────────────────────────────────────────
    op.add_column('report_runs', sa.Column('profile_id', sa.Uuid(), nullable=True))
    op.add_column('report_runs', sa.Column('user_id', sa.Uuid(), nullable=True))
    op.add_column('report_runs', sa.Column('period_year', sa.Integer(), nullable=True))
    op.add_column('report_runs', sa.Column('period_month', sa.Integer(), nullable=True))
    # A run is meaningless without a profile — purge orphaned rows before NOT NULL.
    op.execute('DELETE FROM report_runs WHERE profile_id IS NULL')
    op.alter_column('report_runs', 'profile_id', existing_type=sa.Uuid(), nullable=False)
    op.create_foreign_key('fk_report_runs_profile_id_profiles', 'report_runs', 'profiles', ['profile_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_report_runs_user_id_users', 'report_runs', 'users', ['user_id'], ['id'], ondelete='SET NULL')
    # tenant-consistency: a run's client must belong to the run's tenant.
    op.create_foreign_key('fk_report_runs_client_tenant', 'report_runs', 'clients', ['client_id', 'tenant_id'], ['id', 'tenant_id'])
    op.create_index('ix_report_runs_cuit', 'report_runs', ['cuit'], unique=False)
    op.create_index('ix_report_runs_tenant_profile_id', 'report_runs', ['tenant_id', 'profile_id'], unique=False)

    # ── token_transactions ────────────────────────────────────────────────
    op.add_column('token_transactions', sa.Column('profile_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_token_transactions_profile_id_profiles', 'token_transactions', 'profiles', ['profile_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_token_transactions_profile_id', 'token_transactions', ['profile_id'], unique=False)

    # ── conversations ─────────────────────────────────────────────────────
    op.add_column('conversations', sa.Column('profile_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_conversations_profile_id_profiles', 'conversations', 'profiles', ['profile_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_conversations_profile_id', 'conversations', ['profile_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # ── conversations ─────────────────────────────────────────────────────
    op.drop_index('ix_conversations_profile_id', table_name='conversations')
    op.drop_constraint('fk_conversations_profile_id_profiles', 'conversations', type_='foreignkey')
    op.drop_column('conversations', 'profile_id')

    # ── token_transactions ────────────────────────────────────────────────
    op.drop_index('ix_token_transactions_profile_id', table_name='token_transactions')
    op.drop_constraint('fk_token_transactions_profile_id_profiles', 'token_transactions', type_='foreignkey')
    op.drop_column('token_transactions', 'profile_id')

    # ── report_runs ───────────────────────────────────────────────────────
    op.drop_index('ix_report_runs_tenant_profile_id', table_name='report_runs')
    op.drop_index('ix_report_runs_cuit', table_name='report_runs')
    op.drop_constraint('fk_report_runs_client_tenant', 'report_runs', type_='foreignkey')
    op.drop_constraint('fk_report_runs_user_id_users', 'report_runs', type_='foreignkey')
    op.drop_constraint('fk_report_runs_profile_id_profiles', 'report_runs', type_='foreignkey')
    op.drop_column('report_runs', 'period_month')
    op.drop_column('report_runs', 'period_year')
    op.drop_column('report_runs', 'user_id')
    op.drop_column('report_runs', 'profile_id')

    # ── clients: drop the composite unique constraint ─────────────────────
    op.drop_constraint('uq_clients_tenant_id', 'clients', type_='unique')

    # ── profiles ──────────────────────────────────────────────────────────
    op.drop_index('ix_profiles_created_by', table_name='profiles')
    op.drop_index('ix_profiles_tenant_status', table_name='profiles')
    op.drop_index('ix_profiles_tenant_id', table_name='profiles')
    op.drop_table('profiles')