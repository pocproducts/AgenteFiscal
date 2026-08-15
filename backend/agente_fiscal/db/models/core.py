"""Core domain models (replaces Redis-owned business data)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    TEXT,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agente_fiscal.db.base import Base, TimestampMixin, UuidPkMixin

if TYPE_CHECKING:  # pragma: no cover
    from agente_fiscal.db.models.business import Profile


class Tenant(UuidPkMixin, TimestampMixin, Base):
    """Tenant — mirror of ``backend/db/schema.ts`` ``Tenant``.

    ``clerk_org_id`` is null until the org is provisioned in Clerk.
    """

    __tablename__ = 'tenants'

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    clerk_org_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    members: Mapped[list[TenantMember]] = relationship(
        back_populates='tenant', cascade='all, delete-orphan'
    )
    api_keys: Mapped[list[ApiKey]] = relationship(
        back_populates='tenant', cascade='all, delete-orphan'
    )
    apps: Mapped[list[App]] = relationship(
        back_populates='tenant', cascade='all, delete-orphan'
    )
    profiles: Mapped[list[Profile]] = relationship(back_populates='tenant')

    __table_args__ = (Index('uq_tenants_clerk_org_id', 'clerk_org_id', unique=True),)


class User(UuidPkMixin, TimestampMixin, Base):
    """End user, identified by the Clerk user id once auth is wired."""

    __tablename__ = 'users'

    clerk_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    memberships: Mapped[list[TenantMember]] = relationship(
        back_populates='user', cascade='all, delete-orphan'
    )
    owned_apps: Mapped[list[App]] = relationship(back_populates='developer', foreign_keys='App.developer_id')

    __table_args__ = (Index('uq_users_clerk_user_id', 'clerk_user_id', unique=True),)


class TenantMember(UuidPkMixin, TimestampMixin, Base):
    """A user's membership/role within a tenant."""

    __tablename__ = 'tenant_members'

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default='member')

    tenant: Mapped[Tenant] = relationship(back_populates='members')
    user: Mapped[User] = relationship(back_populates='memberships')

    __table_args__ = (
        UniqueConstraint('tenant_id', 'user_id', name='uq_tenant_members_tenant_user'),
        CheckConstraint(
            "role IN ('owner', 'admin', 'member')",
            name='tenant_members_role_check',
        ),
        Index('ix_tenant_members_tenant_id', 'tenant_id'),
        Index('ix_tenant_members_user_id', 'user_id'),
    )


class ApiKey(UuidPkMixin, TimestampMixin, Base):
    """API key for a tenant. Stores only a sha256 ``key_hash``, never plaintext."""

    __tablename__ = 'api_keys'

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False
    )
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='true')
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[list[str] | None] = mapped_column(ARRAY(TEXT), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates='api_keys')

    __table_args__ = (
        Index('uq_api_keys_key_hash', 'key_hash', unique=True),
        Index('ix_api_keys_tenant_id', 'tenant_id'),
    )


class App(UuidPkMixin, TimestampMixin, Base):
    """Third-party app / integration owned by a tenant."""

    __tablename__ = 'apps'

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False
    )
    developer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    tenant: Mapped[Tenant] = relationship(back_populates='apps')
    developer: Mapped[User | None] = relationship(back_populates='owned_apps', foreign_keys=[developer_id])

    __table_args__ = (
        Index('ix_apps_tenant_id', 'tenant_id'),
        Index('ix_apps_developer_id', 'developer_id'),
    )


class Plan(UuidPkMixin, TimestampMixin, Base):
    """Global subscription plan catalog (Browser Use-style).

    Not tenant-bound: tenants subscribe via ``subscriptions``. ``tier``
    mirrors the billing tiers (free / pro / pro_max / enterprise); pricing
    lives per period in ``plan_prices`` and is NULL until set.
    """

    __tablename__ = 'plans'

    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tier: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='true')
    tokens_included: Mapped[int | None] = mapped_column(nullable=True)
    limits: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    features: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default='USD', server_default='USD')

    prices: Mapped[list[PlanPrice]] = relationship(
        back_populates='plan', cascade='all, delete-orphan'
    )

    __table_args__ = (
        CheckConstraint(
            "tier IN ('free', 'pro', 'pro_max', 'enterprise')",
            name='plans_tier_check',
        ),
        CheckConstraint(
            "currency IN ('ARS', 'USD')",
            name='plans_currency_check',
        ),
    )


class PlanPrice(UuidPkMixin, TimestampMixin, Base):
    """Per-period price for a catalog plan (Stripe-style).

    ``price_cents`` is nullable: prices are not set yet, but the schema
    keeps the door open without any business logic.
    """

    __tablename__ = 'plan_prices'

    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('plans.id', ondelete='CASCADE'), nullable=False
    )
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    price_cents: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default='USD', server_default='USD')

    plan: Mapped[Plan] = relationship(back_populates='prices')

    __table_args__ = (
        CheckConstraint(
            "period IN ('monthly', 'yearly')",
            name='plan_prices_period_check',
        ),
        UniqueConstraint('plan_id', 'period', name='uq_plan_prices_plan_period'),
    )


class Subscription(UuidPkMixin, TimestampMixin, Base):
    """A tenant's subscription to a catalog plan (one active per tenant)."""

    __tablename__ = 'subscriptions'

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('plans.id', ondelete='RESTRICT'), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='active')
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='false')
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default='manual')
    provider_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    tenant: Mapped[Tenant] = relationship()
    plan: Mapped[Plan] = relationship()

    __table_args__ = (
        CheckConstraint(
            "status IN ('trialing', 'active', 'past_due', 'canceled', 'expired')",
            name='subscriptions_status_check',
        ),
        CheckConstraint(
            "provider IN ('stripe', 'mercadopago', 'manual')",
            name='subscriptions_provider_check',
        ),
        Index('ix_subscriptions_tenant_id', 'tenant_id'),
        Index('ix_subscriptions_plan_id', 'plan_id'),
        Index(
            'uq_subscriptions_active_tenant',
            'tenant_id',
            unique=True,
            postgresql_where=text("status IN ('trialing', 'active', 'past_due')"),
        ),
    )