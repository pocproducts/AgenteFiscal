"""Business domain models (clients, conversations, reports, billing)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agente_fiscal.db.base import Base, TimestampMixin, UuidPkMixin

if TYPE_CHECKING:  # pragma: no cover
    from agente_fiscal.db.models.core import (
        Plan,
        PlanPrice,
        Subscription,
        Tenant,
        User,
    )


class Conversation(UuidPkMixin, TimestampMixin, Base):
    """Chat conversation, scoped to a tenant. Replaces ``tenant:*:conv:*``."""

    __tablename__ = 'conversations'

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('profiles.id', ondelete='SET NULL'), nullable=True
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='running')

    tenant: Mapped[Tenant] = relationship()
    user: Mapped[User | None] = relationship()
    profile: Mapped[Profile | None] = relationship()
    messages: Mapped[list[Message]] = relationship(
        back_populates='conversation', cascade='all, delete-orphan'
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'done')",
            name='conversations_status_check',
        ),
        Index('ix_conversations_tenant_id', 'tenant_id', 'created_at'),
        Index('ix_conversations_user_id', 'user_id'),
        Index('ix_conversations_profile_id', 'profile_id'),
    )


class Message(UuidPkMixin, Base):
    """A single message part within a conversation."""

    __tablename__ = 'messages'

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    parts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates='messages')

    __table_args__ = (
        CheckConstraint(
            "role IN ('system', 'user', 'assistant', 'tool')",
            name='messages_role_check',
        ),
        Index('ix_messages_conversation_id', 'conversation_id', 'created_at'),
    )


class Client(UuidPkMixin, TimestampMixin, Base):
    """Per-tenant client (CUIT) — migrated from ``clients.yaml``."""

    __tablename__ = 'clients'

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False
    )
    cuit: Mapped[str] = mapped_column(String(11), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    tenant: Mapped[Tenant] = relationship()
    report_runs: Mapped[list[ReportRun]] = relationship(
        back_populates='client', foreign_keys='ReportRun.client_id'
    )

    __table_args__ = (
        UniqueConstraint('tenant_id', 'cuit', name='uq_clients_tenant_cuit'),
        UniqueConstraint('tenant_id', 'id', name='uq_clients_tenant_id'),
    )


class Profile(UuidPkMixin, TimestampMixin, Base):
    """Per-tenant system identity that aggregates reports, token spend and activity.

    NOT a fiscal client (``Client`` stays the CUIT taxpayer). A profile is the
    accountable actor for a tenant: every ``report_runs`` row MUST reference an
    active profile of the same tenant (invariant enforced at the API boundary).
    """

    __tablename__ = 'profiles'

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cuit: Mapped[str | None] = mapped_column(String(11), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default='active', server_default='active'
    )
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    tenant: Mapped[Tenant] = relationship()
    creator: Mapped[User | None] = relationship()
    report_runs: Mapped[list[ReportRun]] = relationship(back_populates='profile')

    __table_args__ = (
        UniqueConstraint('tenant_id', 'cuit', name='uq_profiles_tenant_cuit'),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name='profiles_status_check',
        ),
        Index('ix_profiles_tenant_id', 'tenant_id'),
        Index('ix_profiles_tenant_status', 'tenant_id', 'status'),
        Index('ix_profiles_created_by', 'created_by'),
    )


class BrowserSession(UuidPkMixin, TimestampMixin, Base):
    """Persisted Browserbase context per (tenant, profile, provider).

    Mapea en NUESTRA base el contexto persistido del provider (Browserbase):
    las cookies del login ARCA sobreviven entre runs reuseando
    ``browser_settings.context`` → la siguiente tool arranca ya logueada. La
    fila única activa cicla ``active ↔ in_use``: ``acquire`` la marca in_use de
    forma atómica (FOR UPDATE SKIP LOCKED) y ``release`` la vuelve a active con
    las métricas reales del último run (proxy bytes, duración, costo).
    ``expires_at`` es el TTL del contexto: vencido ya no se reusa.
    """

    __tablename__ = 'browser_sessions'

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False
    )
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('profiles.id', ondelete='SET NULL'), nullable=True
    )
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default='browserbase', server_default='browserbase'
    )
    context_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default='active', server_default='active'
    )
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    proxy_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped[Tenant] = relationship()
    profile: Mapped[Profile | None] = relationship()

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'in_use')",
            name='browser_sessions_status_check',
        ),
        UniqueConstraint(
            'tenant_id', 'profile_id', 'provider',
            name='uq_browser_sessions_tenant_profile_provider',
        ),
        Index('ix_browser_sessions_tenant_profile_id', 'tenant_id', 'profile_id'),
    )


class ReportRun(UuidPkMixin, TimestampMixin, Base):
    """Audit trail of a fiscal report pipeline run — feeds the history UI."""

    __tablename__ = 'report_runs'

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('profiles.id', ondelete='RESTRICT'), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('clients.id', ondelete='SET NULL'), nullable=True
    )
    cuit: Mapped[str] = mapped_column(String(11), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='queued')
    steps: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    period_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pending_actions: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    tenant: Mapped[Tenant] = relationship()
    profile: Mapped[Profile] = relationship(back_populates='report_runs')
    user: Mapped[User | None] = relationship()
    client: Mapped[Client | None] = relationship(
        back_populates='report_runs', foreign_keys='ReportRun.client_id'
    )
    generated_pdfs: Mapped[list[GeneratedPdf]] = relationship(
        back_populates='report_run', cascade='all, delete-orphan'
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed', 'waiting_approval')",
            name='report_runs_status_check',
        ),
        Index('ix_report_runs_tenant_status', 'tenant_id', 'status', 'created_at'),
        Index('ix_report_runs_client_id', 'client_id'),
        Index('ix_report_runs_cuit', 'cuit'),
        Index('ix_report_runs_tenant_profile_id', 'tenant_id', 'profile_id'),
        # Tenant-consistency: a run's client (when set) must belong to the run's
        # own tenant, not just any client with that id.
        ForeignKeyConstraint(
            ['client_id', 'tenant_id'],
            ['clients.id', 'clients.tenant_id'],
            name='fk_report_runs_client_tenant',
        ),
    )


class GeneratedPdf(UuidPkMixin, TimestampMixin, Base):
    """Reference to a generated PDF on object storage (S3/R2)."""

    __tablename__ = 'generated_pdfs'

    report_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('report_runs.id', ondelete='CASCADE'), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    content_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    report_run: Mapped[ReportRun] = relationship(back_populates='generated_pdfs')

    __table_args__ = (
        Index('ix_generated_pdfs_report_run_id', 'report_run_id'),
    )


class BillingEvent(UuidPkMixin, TimestampMixin, Base):
    """A metered billing event for a tenant/plan."""

    __tablename__ = 'billing_events'

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('plans.id', ondelete='SET NULL'), nullable=True
    )
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default='ARS')

    tenant: Mapped[Tenant] = relationship()
    plan: Mapped[Plan | None] = relationship()

    __table_args__ = (
        CheckConstraint(
            "currency IN ('ARS', 'USD')",
            name='billing_events_currency_check',
        ),
        Index('ix_billing_events_tenant_id', 'tenant_id', 'created_at'),
        Index('ix_billing_events_plan_id', 'plan_id'),
    )


class TokenPackage(UuidPkMixin, TimestampMixin, Base):
    """Recharge catalog entry: buy a block of tokens (credits top-up).

    ``price_cents`` is nullable: no price defined yet, schema only.
    """

    __tablename__ = 'token_packages'

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tokens: Mapped[int] = mapped_column(nullable=False)
    price_cents: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default='USD', server_default='USD')
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='true')

    __table_args__ = (
        CheckConstraint(
            'tokens > 0',
            name='token_packages_tokens_check',
        ),
    )


class TokenBalance(UuidPkMixin, TimestampMixin, Base):
    """Current token (credit) balance for a tenant — one row per tenant.

    ``created_at``/``updated_at`` come from ``TimestampMixin``; the balance
    is mutated in place as transactions land in ``token_transactions``.
    """

    __tablename__ = 'token_balances'

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, unique=True
    )
    balance: Mapped[int] = mapped_column(nullable=False, default=0, server_default='0')

    tenant: Mapped[Tenant] = relationship()


class TokenTransaction(UuidPkMixin, TimestampMixin, Base):
    """Append-only ledger entry for a token balance change (signed delta)."""

    __tablename__ = 'token_transactions'

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('profiles.id', ondelete='SET NULL'), nullable=True
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    delta: Mapped[int] = mapped_column(nullable=False)
    balance_after: Mapped[int] = mapped_column(nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)

    tenant: Mapped[Tenant] = relationship()
    user: Mapped[User | None] = relationship()
    profile: Mapped[Profile | None] = relationship()

    __table_args__ = (
        CheckConstraint(
            "type IN ('purchase', 'grant', 'consume', 'refund', 'expiry')",
            name='token_transactions_type_check',
        ),
        Index('ix_token_transactions_tenant_id', 'tenant_id', 'created_at'),
        Index('ix_token_transactions_reference', 'reference_type', 'reference_id'),
        Index('ix_token_transactions_profile_id', 'profile_id'),
    )


class Invoice(UuidPkMixin, TimestampMixin, Base):
    """Billing document for a subscription charge or token recharge."""

    __tablename__ = 'invoices'

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('subscriptions.id', ondelete='SET NULL'), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='draft')
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default='USD', server_default='USD')
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_invoice_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column('metadata', JSONB, nullable=True)

    tenant: Mapped[Tenant] = relationship()
    subscription: Mapped[Subscription | None] = relationship()
    payments: Mapped[list[Payment]] = relationship(
        back_populates='invoice', cascade='all, delete-orphan'
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('subscription', 'recharge')",
            name='invoices_kind_check',
        ),
        CheckConstraint(
            "status IN ('draft', 'open', 'paid', 'void', 'refunded')",
            name='invoices_status_check',
        ),
        CheckConstraint(
            "provider IN ('stripe', 'mercadopago', 'manual')",
            name='invoices_provider_check',
        ),
        Index('ix_invoices_tenant_id', 'tenant_id', 'created_at'),
        Index('ix_invoices_subscription_id', 'subscription_id'),
    )


class Payment(UuidPkMixin, TimestampMixin, Base):
    """A payment attempt against an invoice (one-to-many: retries allowed)."""

    __tablename__ = 'payments'

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('invoices.id', ondelete='CASCADE'), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default='USD', server_default='USD')
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='pending')
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    invoice: Mapped[Invoice] = relationship(back_populates='payments')

    __table_args__ = (
        CheckConstraint(
            "provider IN ('stripe', 'mercadopago', 'manual')",
            name='payments_provider_check',
        ),
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'refunded')",
            name='payments_status_check',
        ),
        Index('ix_payments_invoice_id', 'invoice_id'),
    )