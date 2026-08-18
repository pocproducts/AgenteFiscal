"""browser_sessions

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-17 10:00:00.000000

Introduces the ``browser_sessions`` table: persisted Browserbase contexts for
reauth-free browser sessions between chat tools.

Reuso de sesiones de browser (Browserbase): el SDK soporta persistencia de
CONTEXTO (``browser_settings={'context': {'id': ..., 'persist': True}}`` en
``agents.runs.create``) para que las cookies del login ARCA sobrevivan entre
runs — la siguiente tool arranca ya logueada. Esta tabla NOSOTROS la mapeamos
tenant/profile → provider context ``context_id`` (el SDK de Browserbase NO
acepta ``user_metadata`` en ``runs.create``, así que el mapping no vive en el
provider). También registra métricas reales del último run (proxy bytes,
duración, costo) para el UI de sesiones de agentes.

- ``browser_sessions`` — nueva tabla. Única fila activa por
  (tenant_id, profile_id, provider). ``status`` cicla active ↔ in_use:
  ``acquire`` marca in_use atómicamente (SELECT ... FOR UPDATE SKIP LOCKED),
  ``release`` vuelve a active con las métricas del run terminado.
```
Downgrade reverses in the opposite order.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ── browser_sessions ────────────────────────────────────────────────────
    op.create_table(
        'browser_sessions',
        sa.Column('provider', sa.String(length=32), server_default='browserbase', nullable=False),
        sa.Column('context_id', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='active', nullable=False),
        sa.Column('session_id', sa.String(length=255), nullable=True),
        sa.Column('proxy_bytes', sa.BigInteger(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('cost_cents', sa.Integer(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('profile_id', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('active', 'in_use')", name=op.f('ck_browser_sessions_browser_sessions_status_check')),
        sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], name=op.f('fk_browser_sessions_profile_id_profiles'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_browser_sessions_tenant_id_tenants'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_browser_sessions')),
        sa.UniqueConstraint('tenant_id', 'profile_id', 'provider', name='uq_browser_sessions_tenant_profile_provider')
    )
    op.create_index('ix_browser_sessions_tenant_profile_id', 'browser_sessions', ['tenant_id', 'profile_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # ── browser_sessions ────────────────────────────────────────────────────
    op.drop_index('ix_browser_sessions_tenant_profile_id', table_name='browser_sessions')
    op.drop_table('browser_sessions')