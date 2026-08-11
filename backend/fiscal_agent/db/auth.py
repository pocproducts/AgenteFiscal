"""Clerk auth context resolution against Postgres (Fase 1 data layer).

Replaces the Redis tenant/plan resolution in the Clerk JWT path. Kept as a
single async module so the extractor can drop in a session and resolve the
full ``User -> Tenant -> Plan`` chain in one transaction.

Every function takes an ``AsyncSession`` (obtained from the app's
``async_sessionmaker``). Commits are left to the caller so a single logical
unit (e.g. auto-provisioning a personal tenant) commits once.

Stable id mapping (documented decision):
  - Org tenant: ``tenants.clerk_org_id`` == the Clerk ``org_id`` claim.
  - Personal tenant (no ``org_id``): deterministic ``UUIDv5`` derived from
    the Clerk user id — ``uuid5(PERSONAL_NS, f'personal:{clerk_user_id}')``.
    This replaces the old Redis convention ``user_{sub[:12]}`` while keeping
    the SAME user always mapped to the SAME tenant id, even across concurrent
    first requests, without needing a global lock.
"""

from __future__ import annotations

import logging
import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fiscal_agent.db.models.core import (
    Plan as PlanModel,
    Subscription,
    Tenant as TenantRow,
    TenantMember,
    User,
)
from fiscal_agent.domain.models import Plan, PlanTier

logger = logging.getLogger(__name__)

#: UUID namespace for deterministic personal-tenant ids.
PERSONAL_NS = uuid.UUID('6f1e6c25-2c8a-4f8e-9b7a-3c1d2e4f5a6b')

#: Subscription statuses that count as "active" for plan resolution.
_ACTIVE_STATUSES = ('trialing', 'active', 'past_due')

#: Limit defaults when the catalog ``limits`` JSONB has no rpm/rpd keys.
_DEFAULT_RPM = 10
_DEFAULT_RPD = 100
_DEFAULT_LIMITS = {'rpm': _DEFAULT_RPM, 'rpd': _DEFAULT_RPD}

#: Scopes default until the catalog carries per-plan scopes.
_DEFAULT_SCOPES = ['chat:read', 'chat:write']


class TenantNotFoundError(LookupError):
    """Raised when a Clerk ``org_id`` has no provisioning tenant in Postgres."""


def _personal_tenant_uuid(clerk_user_id: str) -> UUID:
    """Deterministic UUID for a user's personal tenant (no org)."""
    return uuid.uuid5(PERSONAL_NS, f'personal:{clerk_user_id}')


async def resolve_or_create_user(
    session: AsyncSession,
    clerk_user_id: str,
    email: str | None = None,
    display_name: str | None = None,
) -> User:
    """Return the ``User`` for a Clerk user id, inserting it if missing.

    Concurrency-safe: on a unique-index collision the insert is rolled back
    and the row (created by a racing request) is re-selected.
    """
    for attempt in range(2):
        try:
            user = await session.scalar(
                select(User).where(User.clerk_user_id == clerk_user_id)
            )
            if user is None:
                user = User(
                    clerk_user_id=clerk_user_id,
                    email=email or '',
                    display_name=display_name,
                )
                session.add(user)
                await session.flush()
                logger.info('Provisioned user %s', clerk_user_id)
            return user
        except IntegrityError:
            await session.rollback()
            if attempt == 0:
                continue
            raise


async def _ensure_owner_membership(session: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
    """Ensure the user owns the personal tenant (idempotent)."""
    existing = await session.scalar(
        select(TenantMember).where(
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_id == user_id,
        )
    )
    if existing is None:
        session.add(TenantMember(tenant_id=tenant_id, user_id=user_id, role='owner'))
        logger.info('Provisioned owner membership for tenant %s user %s', tenant_id, user_id)


async def _ensure_free_subscription(session: AsyncSession, tenant_id: UUID) -> None:
    """Grant the catalog Free plan when the tenant has no active subscription.

    Respects the partial unique index ``uq_subscriptions_active_tenant`` (one
    active subscription per tenant): nothing is inserted if one already exists.
    """
    free_plan = await session.scalar(
        select(PlanModel).where(PlanModel.slug == 'free', PlanModel.is_active.is_(True))
    )
    if free_plan is None:
        logger.warning('Catalog free plan missing — skipping auto subscription for %s', tenant_id)
        return
    existing = await session.scalar(
        select(Subscription).where(
            Subscription.tenant_id == tenant_id,
            Subscription.status.in_(_ACTIVE_STATUSES),
        )
    )
    if existing is None:
        session.add(
            Subscription(
                tenant_id=tenant_id,
                plan_id=free_plan.id,
                status='active',
                provider='manual',
            )
        )
        logger.info('Provisioned free subscription for tenant %s', tenant_id)


async def resolve_or_create_tenant(
    session: AsyncSession,
    clerk_org_id: str | None,
    clerk_user_id: str,
    email: str | None = None,
    display_name: str | None = None,
) -> tuple[TenantRow, User]:
    """Resolve (and auto-provision) the tenant for a Clerk session.

    - ``clerk_org_id`` present: look up ``tenants.clerk_org_id``; raise
      :class:`TenantNotFoundError` (maps to the 401-equivalent
      ``'TENANT_NOT_FOUND'`` behaviour) when unprovisioned.
    - No org: resolve (or create) the user and their deterministic personal
      tenant, an owner membership, and a Free subscription — idempotent and
      concurrent-safe via IntegrityError + re-select.

    Returns ``(tenant_row, user_row)``. The caller commits.
    """
    for attempt in range(2):
        try:
            user = await resolve_or_create_user(session, clerk_user_id, email, display_name)

            if clerk_org_id:
                tenant = await session.scalar(
                    select(TenantRow).where(TenantRow.clerk_org_id == clerk_org_id)
                )
                if tenant is None:
                    logger.warning(
                        'Clerk org_id %s not provisioned for user %s', clerk_org_id, clerk_user_id
                    )
                    raise TenantNotFoundError(f'org_id {clerk_org_id!r} not provisioned')
                return tenant, user

            tenant_id = _personal_tenant_uuid(clerk_user_id)
            tenant = await session.scalar(select(TenantRow).where(TenantRow.id == tenant_id))
            if tenant is None:
                tenant = TenantRow(id=tenant_id, name='Personal', clerk_org_id=None)
                session.add(tenant)
                await session.flush()
                logger.info('Provisioned personal tenant %s for user %s', tenant_id, clerk_user_id)
            await _ensure_owner_membership(session, tenant.id, user.id)
            await _ensure_free_subscription(session, tenant.id)
            return tenant, user
        except IntegrityError:
            await session.rollback()
            if attempt == 0:
                logger.info('Racing provision for %s — retrying against committed state', clerk_user_id)
                continue
            raise


def _to_plan(plan_row: PlanModel | None) -> Plan:
    """Map a catalog ``Plan`` row (or a missing row) to the pydantic ``Plan``.

    ``limits`` JSONB rpm/rpd are honoured when present; otherwise the legacy
    defaults (10 rpm / 100 rpd) are used, so rate limits always resolve.
    Scopes fall back to ``['chat:read', 'chat:write']`` until the catalog
    carries them (``features.scopes``).
    """
    if plan_row is None:
        return Plan(
            id='free',
            name='Free',
            scopes=list(_DEFAULT_SCOPES),
            rate_limit_rpm=_DEFAULT_RPM,
            rate_limit_rpd=_DEFAULT_RPD,
        )

    limits = plan_row.limits or {}
    try:
        rpm = int(limits.get('rpm', _DEFAULT_RPM))
    except (TypeError, ValueError):
        rpm = _DEFAULT_RPM
    try:
        rpd = int(limits.get('rpd', _DEFAULT_RPD))
    except (TypeError, ValueError):
        rpd = _DEFAULT_RPD

    features = plan_row.features or {}
    scopes = features.get('scopes') or list(_DEFAULT_SCOPES)

    return Plan(
        id=str(plan_row.id),
        name=plan_row.name,
        scopes=scopes,
        rate_limit_rpm=rpm,
        rate_limit_rpd=rpd,
    )


async def get_active_plan(session: AsyncSession, tenant_id: UUID) -> Plan | None:
    """Resolve the tenant's active plan from Postgres.

    Prefers the tenant's subscription (status ``trialing``/``active``/
    ``past_due``) joined to the catalog; falls back to the catalog Free plan
    (so rate limits always resolve); finally synthesizes Free defaults when
    the catalog is unseeded.
    """
    plan_row = await session.scalar(
        select(PlanModel)
        .join(Subscription, Subscription.plan_id == PlanModel.id)
        .where(
            Subscription.tenant_id == tenant_id,
            Subscription.status.in_(_ACTIVE_STATUSES),
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    if plan_row is None:
        plan_row = await session.scalar(
            select(PlanModel).where(PlanModel.slug == 'free', PlanModel.is_active.is_(True))
        )
    if plan_row is None:
        logger.warning('No plan catalog row for tenant %s — synthesizing Free defaults', tenant_id)
    return _to_plan(plan_row)


__all__ = [
    'TenantNotFoundError',
    'get_active_plan',
    'resolve_or_create_tenant',
    'resolve_or_create_user',
]