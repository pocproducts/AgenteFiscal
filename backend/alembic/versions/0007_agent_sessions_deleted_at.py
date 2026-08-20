"""agent_sessions + conversations.deleted_at

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-19 10:00:00.000000

Adds the ``agent_sessions`` telemetry table (AST-1): one row per agent tool
run (engine + browser), written post-execution by the chat stream — user-facing
"Acciones"/"Comenzó"/"Duración" data for the agent-sessions page and chat
hydrate. Coexists with ``browser_sessions`` (ADR-1): that table stays the
infra state (context reuse, active↔in_use, expires), this one is telemetry.

Also adds ``conversations.deleted_at`` (ADR-5): DELETE becomes a tombstone so
upserts can never resurrect an explicitly deleted conversation (CD-1/2).
"Hard delete" is interpreted as row-state gone; purge of tombstoned rows is a
future admin op (out of scope).

Every ``agent_sessions`` column is nullable or defaulted so existing flows
never break writes (AST-1 scenario 2). Downgrade drops the table and column.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ── agent_sessions ─────────────────────────────────────────────────────
    op.create_table(
        'agent_sessions',
        sa.Column('tool', sa.String(length=64), nullable=False),
        sa.Column('message_id', sa.String(length=255), nullable=True),
        sa.Column('conversation_id', sa.String(length=255), nullable=True),
        sa.Column('session_id', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=32), server_default='completed', nullable=False),
        sa.Column('tasks', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('cost_cents', sa.Integer(), server_default='0', nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('profile_id', sa.Uuid(), nullable=True),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('running', 'completed', 'error')", name=op.f('ck_agent_sessions_agent_sessions_status_check')),
        sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], name=op.f('fk_agent_sessions_profile_id_profiles'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_agent_sessions_tenant_id_tenants'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_agent_sessions_user_id_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_sessions')),
    )
    op.create_index('ix_agent_sessions_tenant_created', 'agent_sessions', ['tenant_id', sa.text('created_at DESC')], unique=False)
    op.create_index('ix_agent_sessions_conversation', 'agent_sessions', ['conversation_id'], unique=False)
    op.create_index('ix_agent_sessions_profile', 'agent_sessions', ['profile_id'], unique=False)

    # ── conversations: tombstone column ───────────────────────────────────
    op.add_column('conversations', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('conversations', 'deleted_at')
    op.drop_index('ix_agent_sessions_profile', table_name='agent_sessions')
    op.drop_index('ix_agent_sessions_conversation', table_name='agent_sessions')
    op.drop_index('ix_agent_sessions_tenant_created', table_name='agent_sessions')
    op.drop_table('agent_sessions')