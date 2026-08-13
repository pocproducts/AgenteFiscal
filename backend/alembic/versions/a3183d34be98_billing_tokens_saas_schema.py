"""billing tokens SaaS schema

Revision ID: a3183d34be98
Revises: 0001
Create Date: 2026-08-11 17:45:54.701421

Reshapes ``plans`` into a global catalog (drops tenant binding) and adds the
SaaS subscription + token recharge schema (Browser Use-style):
  - ``plans``     — global catalog (slug/name/description/is_active/tokens_included/limits/features)
  - ``plan_prices`` — per-period price per plan, price_cents NULL (no pricing yet)
  - ``subscriptions`` — tenant -> plan, one active per tenant (partial unique index)
  - ``token_packages`` — recharge catalog
  - ``token_balances`` — one balance row per tenant
  - ``token_transactions`` — append-only signed ledger
  - ``invoices`` / ``payments`` — billing documents and payment attempts

CRITICAL ORDERING for the ``plans`` reshape: drop the ``billing_events`` FK to
``plans`` first, recreate ``plans`` (drop/recreate — it holds only the seeded
'pro' row), then re-add the FK and create the new tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from agente_fiscal.db.uuid7 import uuid7

# revision identifiers, used by Alembic.
revision: str = 'a3183d34be98'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PLANS_CATALOG = (
    ('free', 'Free', 'Introductory plan to try the product', 'free', None),
    ('pro', 'Pro', 'For growing accounting studios', 'pro', 5_000),
    ('pro_max', 'Pro Max', 'Advanced plan with higher limits', 'pro_max', 20_000),
    ('enterprise', 'Enterprise', 'Corporate plan with dedicated support', 'enterprise', 60_000),
)


def _seed_catalog() -> None:
    """Idempotent catalog rows: 4 plans, monthly/yearly prices, one token pack.

    Prices stay NULL (no pricing decided yet). Re-runs are safe:
    plans uses ON CONFLICT(slug), prices ON CONFLICT(plan_id, period), and
    the token package is guarded by an existence check (no unique column).
    """
    bind = op.get_bind()

    for slug, name, description, tier, tokens in PLANS_CATALOG:
        bind.execute(
            sa.text(
                """
                INSERT INTO plans
                    (id, slug, name, description, tier, is_active, tokens_included,
                     limits, features, currency, created_at, updated_at)
                VALUES
                    (:id, :slug, :name, :description, :tier, true, :tokens,
                     '{}'::jsonb, '{}'::jsonb, 'USD', now(), now())
                ON CONFLICT (slug) DO NOTHING
                """
            ),
            {
                'id': uuid7(),
                'slug': slug,
                'name': name,
                'description': description,
                'tier': tier,
                'tokens': tokens,
            },
        )

    for slug in ('free', 'pro', 'pro_max', 'enterprise'):
        for period in ('monthly', 'yearly'):
            bind.execute(
                sa.text(
                    """
                    INSERT INTO plan_prices
                        (id, plan_id, period, price_cents, currency, created_at, updated_at)
                    VALUES
                        (:id, (SELECT id FROM plans WHERE slug = :slug), :period,
                         NULL, 'USD', now(), now())
                    ON CONFLICT (plan_id, period) DO NOTHING
                    """
                ),
                {'id': uuid7(), 'slug': slug, 'period': period},
            )

    existing = bind.execute(
        sa.text("SELECT 1 FROM token_packages WHERE name = 'Token pack 10k'")
    ).first()
    if existing is None:
        bind.execute(
            sa.text(
                """
                INSERT INTO token_packages
                    (id, name, tokens, price_cents, currency, is_active, created_at, updated_at)
                VALUES
                    (:id, 'Token pack 10k', 10000, NULL, 'USD', true, now(), now())
                """
            ),
            {'id': uuid7()},
        )


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Drop billing_events FK to plans so the table can be recreated.
    op.drop_constraint(op.f('fk_billing_events_plan_id_plans'), 'billing_events', type_='foreignkey')

    # 2. Drop the old tenant-bound plans table (only the seeded 'pro' row lives in it).
    op.drop_index(op.f('ix_plans_tenant_id'), table_name='plans')
    op.drop_table('plans')

    # 3. Recreate plans as the global catalog.
    op.create_table('plans',
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.String(length=512), nullable=True),
    sa.Column('tier', sa.String(length=32), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('tokens_included', sa.Integer(), nullable=True),
    sa.Column('limits', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('features', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('currency', sa.String(length=3), server_default='USD', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("currency IN ('ARS', 'USD')", name=op.f('ck_plans_plans_currency_check')),
    sa.CheckConstraint("tier IN ('free', 'pro', 'pro_max', 'enterprise')", name=op.f('ck_plans_plans_tier_check')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_plans')),
    sa.UniqueConstraint('slug', name=op.f('uq_plans_slug'))
    )

    # 4. New SaaS billing / token tables (FKs reference the new plans).
    op.create_table('token_packages',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('tokens', sa.Integer(), nullable=False),
    sa.Column('price_cents', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('currency', sa.String(length=3), server_default='USD', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('tokens > 0', name=op.f('ck_token_packages_token_packages_tokens_check')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_token_packages'))
    )
    op.create_table('plan_prices',
    sa.Column('plan_id', sa.Uuid(), nullable=False),
    sa.Column('period', sa.String(length=16), nullable=False),
    sa.Column('price_cents', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('currency', sa.String(length=3), server_default='USD', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("period IN ('monthly', 'yearly')", name=op.f('ck_plan_prices_plan_prices_period_check')),
    sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], name=op.f('fk_plan_prices_plan_id_plans'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_plan_prices')),
    sa.UniqueConstraint('plan_id', 'period', name='uq_plan_prices_plan_period')
    )
    op.create_table('subscriptions',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('plan_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancel_at_period_end', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('provider_subscription_id', sa.String(length=255), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("provider IN ('stripe', 'mercadopago', 'manual')", name=op.f('ck_subscriptions_subscriptions_provider_check')),
    sa.CheckConstraint("status IN ('trialing', 'active', 'past_due', 'canceled', 'expired')", name=op.f('ck_subscriptions_subscriptions_status_check')),
    sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], name=op.f('fk_subscriptions_plan_id_plans'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_subscriptions_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_subscriptions'))
    )
    op.create_index('ix_subscriptions_plan_id', 'subscriptions', ['plan_id'], unique=False)
    op.create_index('ix_subscriptions_tenant_id', 'subscriptions', ['tenant_id'], unique=False)
    op.create_index('uq_subscriptions_active_tenant', 'subscriptions', ['tenant_id'], unique=True, postgresql_where=sa.text("status IN ('trialing', 'active', 'past_due')"))
    op.create_table('token_balances',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('balance', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_token_balances_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_token_balances')),
    sa.UniqueConstraint('tenant_id', name=op.f('uq_token_balances_tenant_id'))
    )
    op.create_table('token_transactions',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('type', sa.String(length=32), nullable=False),
    sa.Column('delta', sa.Integer(), nullable=False),
    sa.Column('balance_after', sa.Integer(), nullable=False),
    sa.Column('reference_type', sa.String(length=64), nullable=True),
    sa.Column('reference_id', sa.Uuid(), nullable=True),
    sa.Column('description', sa.String(length=512), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("type IN ('purchase', 'grant', 'consume', 'refund', 'expiry')", name=op.f('ck_token_transactions_token_transactions_type_check')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_token_transactions_tenant_id_tenants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_token_transactions_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_token_transactions'))
    )
    op.create_index('ix_token_transactions_reference', 'token_transactions', ['reference_type', 'reference_id'], unique=False)
    op.create_index('ix_token_transactions_tenant_id', 'token_transactions', ['tenant_id', 'created_at'], unique=False)
    op.create_table('invoices',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('subscription_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), server_default='USD', nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('provider', sa.String(length=32), nullable=True),
    sa.Column('provider_invoice_id', sa.String(length=255), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('subscription', 'recharge')", name=op.f('ck_invoices_invoices_kind_check')),
    sa.CheckConstraint("provider IN ('stripe', 'mercadopago', 'manual')", name=op.f('ck_invoices_invoices_provider_check')),
    sa.CheckConstraint("status IN ('draft', 'open', 'paid', 'void', 'refunded')", name=op.f('ck_invoices_invoices_status_check')),
    sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], name=op.f('fk_invoices_subscription_id_subscriptions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_invoices_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invoices'))
    )
    op.create_index('ix_invoices_subscription_id', 'invoices', ['subscription_id'], unique=False)
    op.create_index('ix_invoices_tenant_id', 'invoices', ['tenant_id', 'created_at'], unique=False)
    op.create_table('payments',
    sa.Column('invoice_id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('provider_payment_id', sa.String(length=255), nullable=True),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), server_default='USD', nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("provider IN ('stripe', 'mercadopago', 'manual')", name=op.f('ck_payments_payments_provider_check')),
    sa.CheckConstraint("status IN ('pending', 'succeeded', 'failed', 'refunded')", name=op.f('ck_payments_payments_status_check')),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=op.f('fk_payments_invoice_id_invoices'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payments'))
    )
    op.create_index('ix_payments_invoice_id', 'payments', ['invoice_id'], unique=False)

    # 5. Re-add the billing_events FK to the recreated plans table.
    op.create_foreign_key(
        op.f('fk_billing_events_plan_id_plans'),
        'billing_events', 'plans', ['plan_id'], ['id'],
        ondelete='SET NULL',
    )

    # 6. Seed the catalog rows (idempotent).
    _seed_catalog()


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Remove the new SaaS/token tables (reverse dependency order).
    op.drop_index('ix_payments_invoice_id', table_name='payments')
    op.drop_table('payments')
    op.drop_index('ix_invoices_tenant_id', table_name='invoices')
    op.drop_index('ix_invoices_subscription_id', table_name='invoices')
    op.drop_table('invoices')
    op.drop_index('ix_token_transactions_tenant_id', table_name='token_transactions')
    op.drop_index('ix_token_transactions_reference', table_name='token_transactions')
    op.drop_table('token_transactions')
    op.drop_table('token_balances')
    op.drop_index('uq_subscriptions_active_tenant', table_name='subscriptions', postgresql_where=sa.text("status IN ('trialing', 'active', 'past_due')"))
    op.drop_index('ix_subscriptions_tenant_id', table_name='subscriptions')
    op.drop_index('ix_subscriptions_plan_id', table_name='subscriptions')
    op.drop_table('subscriptions')
    op.drop_table('plan_prices')
    op.drop_table('token_packages')

    # 2. Drop the billing_events FK, then the catalog plans table.
    op.drop_constraint(op.f('fk_billing_events_plan_id_plans'), 'billing_events', type_='foreignkey')
    op.drop_table('plans')

    # 3. Recreate the old tenant-bound plans table.
    op.create_table('plans',
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('tier', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('period', sa.String(length=32), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("period IN ('monthly', 'yearly')", name=op.f('ck_plans_plans_period_check')),
    sa.CheckConstraint("status IN ('active', 'inactive', 'canceled')", name=op.f('ck_plans_plans_status_check')),
    sa.CheckConstraint("tier IN ('free', 'pro', 'pro_max', 'enterprise')", name=op.f('ck_plans_plans_tier_check')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_plans_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_plans'))
    )
    op.create_index('ix_plans_tenant_id', 'plans', ['tenant_id'], unique=False)

    # 4. Re-add the billing_events FK.
    op.create_foreign_key(
        op.f('fk_billing_events_plan_id_plans'),
        'billing_events', 'plans', ['plan_id'], ['id'],
        ondelete='SET NULL',
    )