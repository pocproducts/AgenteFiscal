"""Security-critical multi-tenant isolation tests.

Covers the Clerk -> tenant -> plan chain (``agente_fiscal.db.auth``) and the
per-tenant client CRUD adapter (``agente_fiscal.adapters.db_clients``) against
the real test Postgres. Everything here is designed to fail loudly if tenant A
can observe or mutate tenant B's data.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from agente_fiscal.adapters.db_clients import PostgresClientRepository
from agente_fiscal.db import auth as auth_mod
from agente_fiscal.db.auth import (
    PERSONAL_NS,
    TenantNotFoundError,
    _personal_tenant_uuid,
    _to_plan,
    get_active_plan,
    resolve_or_create_tenant,
    resolve_or_create_user,
)
from agente_fiscal.db.models import (
    Subscription,
    Tenant as TenantRow,
    TenantMember,
    User as UserRow,
)
from agente_fiscal.ports.clients import ClientAlreadyExistsError

pytestmark = pytest.mark.usefixtures('db_reset')

CUIT_A = '20301234561'
CUIT_B = '20123456780'


# ─── Part A: db/auth.py ─────────────────────────────────────────────────────


def test_personal_tenant_uuid_deterministic() -> None:
    first = _personal_tenant_uuid('user_123')
    second = _personal_tenant_uuid('user_123')
    other = _personal_tenant_uuid('user_456')
    assert first == second
    assert first != other
    assert first == uuid.uuid5(PERSONAL_NS, 'personal:user_123')


async def test_resolve_or_create_user_creates_and_reuses(
    test_session_factory,
) -> None:
    async with test_session_factory() as session:
        user = await resolve_or_create_user(
            session, 'user_1', email='ana@acme.io', display_name='Ana'
        )
        assert user.clerk_user_id == 'user_1'
        assert user.email == 'ana@acme.io'
        assert user.display_name == 'Ana'

        again = await resolve_or_create_user(session, 'user_1')
        assert again.id == user.id
        await session.commit()

    async with test_session_factory() as session:
        rows = (await session.execute(select(UserRow))).scalars().all()
    assert len(rows) == 1
    assert rows[0].email == 'ana@acme.io'


async def test_resolve_or_create_tenant_personal_provisions_owner_and_free(
    test_session_factory, make_plan
) -> None:
    async with test_session_factory() as session:
        await make_plan(session, slug='free', name='Free', tier='free')
        tenant, user = await resolve_or_create_tenant(
            session, None, 'user_1', email='ana@acme.io'
        )
        assert tenant.id == _personal_tenant_uuid('user_1')
        assert tenant.clerk_org_id is None
        assert user.clerk_user_id == 'user_1'
        await session.commit()

    # Idempotency: a second resolution must not duplicate anything.
    async with test_session_factory() as session:
        tenant2, user2 = await resolve_or_create_tenant(session, None, 'user_1')
        assert tenant2.id == tenant.id
        assert user2.id == user.id
        await session.commit()

    async with test_session_factory() as session:
        memberships = (await session.execute(select(TenantMember))).scalars().all()
        subscriptions = (await session.execute(select(Subscription))).scalars().all()
        users = (await session.execute(select(UserRow))).scalars().all()
    assert len(memberships) == 1
    assert memberships[0].role == 'owner'
    assert memberships[0].user_id == user.id
    assert len(subscriptions) == 1
    assert subscriptions[0].status == 'active'
    assert len(users) == 1


async def test_resolve_or_create_tenant_personal_without_free_catalog(
    test_session_factory,
) -> None:
    async with test_session_factory() as session:
        tenant, user = await resolve_or_create_tenant(session, None, 'user_2')
        await session.commit()

    async with test_session_factory() as session:
        subs = (await session.execute(select(Subscription))).scalars().all()
    assert subs == []


async def test_resolve_or_create_tenant_org_provisioned(
    test_session_factory, make_tenant
) -> None:
    async with test_session_factory() as session:
        org = await make_tenant(session, name='Org', clerk_org_id='org_abc')

    async with test_session_factory() as session:
        tenant, user = await resolve_or_create_tenant(
            session, 'org_abc', 'user_3', email='boss@acme.io'
        )
        assert tenant.id == org.id
        assert user.clerk_user_id == 'user_3'
        await session.commit()

    async with test_session_factory() as session:
        rows = (await session.execute(select(UserRow))).scalars().all()
    assert len(rows) == 1


async def test_resolve_or_create_tenant_org_unprovisioned_raises(
    test_session_factory,
) -> None:
    async with test_session_factory() as session:
        with pytest.raises(TenantNotFoundError):
            await resolve_or_create_tenant(session, 'org_nope', 'user_4')

    # Nothing committed before the raise.
    async with test_session_factory() as session:
        rows = (await session.execute(select(UserRow))).scalars().all()
    assert rows == []


async def test_resolve_or_create_user_retries_on_integrity_error() -> None:
    """Deterministic simulation of a racing insert winning the unique index."""

    class RacingSession:
        def __init__(self):
            self.flushes = 0

        async def scalar(self, stmt):
            return None

        def add(self, obj):
            pass

        async def flush(self):
            self.flushes += 1
            raise IntegrityError('stmt', {}, Exception('duplicate clerk_user_id'))

        async def rollback(self):
            pass

    session = RacingSession()
    with pytest.raises(IntegrityError):
        await resolve_or_create_user(session, 'user_race')
    # Both attempts flushed; the second re-raised.
    assert session.flushes == 2


async def test_resolve_or_create_tenant_retries_on_integrity_error() -> None:
    """The tenant insert fails once (racing provision), then succeeds."""

    class RacingSession:
        def __init__(self):
            self.flushes = 0

        async def scalar(self, stmt):
            return None

        def add(self, obj):
            pass

        async def flush(self):
            self.flushes += 1
            if self.flushes == 2:  # the TenantRow flush on the first attempt
                raise IntegrityError('stmt', {}, Exception('duplicate tenant'))

        async def rollback(self):
            pass

    session = RacingSession()
    tenant, user = await resolve_or_create_tenant(session, None, 'user_race')
    assert tenant.id == _personal_tenant_uuid('user_race')
    assert user.clerk_user_id == 'user_race'
    assert session.flushes == 4  # user + tenant on each of the two attempts


async def test_resolve_or_create_tenant_raises_after_two_collisions() -> None:
    """Both attempts collide on the same unique index -> the second re-raises."""

    class RacingSession:
        def __init__(self):
            self.flushes = 0

        async def scalar(self, stmt):
            return None

        def add(self, obj):
            pass

        async def flush(self):
            self.flushes += 1
            raise IntegrityError('stmt', {}, Exception('duplicate tenant'))

        async def rollback(self):
            pass

    session = RacingSession()
    with pytest.raises(IntegrityError):
        await resolve_or_create_tenant(session, None, 'user_race')
    # user + tenant flushes on attempt 1, then again on attempt 2 -> re-raise.
    assert session.flushes == 4


async def test_get_active_plan_from_subscription(
    test_session_factory, make_tenant, make_plan
) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
        plan = await make_plan(
            session,
            slug='pro',
            name='Pro',
            tier='pro',
            limits={'rpm': 100, 'rpd': 2000},
            features={'scopes': ['report:read']},
        )
        session.add(
            Subscription(tenant_id=tenant.id, plan_id=plan.id, status='active', provider='stripe')
        )
        await session.commit()

    async with test_session_factory() as session:
        resolved = await get_active_plan(session, tenant.id)
    assert resolved.id == str(plan.id)
    assert resolved.name == 'Pro'
    assert resolved.rate_limit_rpm == 100
    assert resolved.rate_limit_rpd == 2000
    assert resolved.scopes == ['report:read']


async def test_get_active_plan_falls_back_to_catalog_free(
    test_session_factory, make_tenant, make_plan
) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
        await make_plan(session, slug='free', name='Free', tier='free')

    async with test_session_factory() as session:
        resolved = await get_active_plan(session, tenant.id)
    assert resolved.name == 'Free'
    assert resolved.rate_limit_rpm == 10
    assert resolved.rate_limit_rpd == 100
    assert resolved.scopes == ['chat:read', 'chat:write']


async def test_get_active_plan_ignores_canceled_subscription(
    test_session_factory, make_tenant, make_plan
) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
        await make_plan(session, slug='free', name='Free', tier='free')
        old_plan = await make_plan(
            session, slug='old', name='Old', tier='pro', limits={'rpm': 999, 'rpd': 999}
        )
        session.add(
            Subscription(tenant_id=tenant.id, plan_id=old_plan.id, status='canceled', provider='manual')
        )
        await session.commit()

    async with test_session_factory() as session:
        resolved = await get_active_plan(session, tenant.id)
    assert resolved.name == 'Free'  # canceled does not count as active


async def test_get_active_plan_synthesizes_free_defaults(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)

    async with test_session_factory() as session:
        resolved = await get_active_plan(session, tenant.id)
    assert resolved.id == 'free'
    assert resolved.name == 'Free'
    assert resolved.rate_limit_rpm == 10
    assert resolved.rate_limit_rpd == 100
    assert resolved.scopes == ['chat:read', 'chat:write']


async def test_to_plan_none_synthesizes_defaults() -> None:
    plan = _to_plan(None)
    assert plan.id == 'free'
    assert plan.rate_limit_rpm == 10
    assert plan.rate_limit_rpd == 100
    assert plan.scopes == ['chat:read', 'chat:write']


async def test_to_plan_bad_limits_fall_back_to_defaults(test_session_factory, make_plan) -> None:
    async with test_session_factory() as session:
        plan = await make_plan(
            session,
            slug='janky',
            name='Janky',
            limits={'rpm': 'not-an-int', 'rpd': None},
            features={'scopes': []},
        )

    resolved = _to_plan(plan)
    assert resolved.rate_limit_rpm == 10
    assert resolved.rate_limit_rpd == 100
    assert resolved.scopes == ['chat:read', 'chat:write']


# ─── Part B: db_clients.py adapter — cross-tenant isolation matrix ──────────


async def _create_tenants(test_session_factory, make_tenant, make_user):
    async with test_session_factory() as session:
        tenant_a = await make_tenant(session, name='Tenant A')
        tenant_b = await make_tenant(session, name='Tenant B')
        await make_user(session, clerk_user_id='user_a')
        await make_user(session, clerk_user_id='user_b')
    return tenant_a, tenant_b


async def test_create_client_persists_fields(test_session_factory, make_tenant, make_user) -> None:
    tenant_a, _ = await _create_tenants(test_session_factory, make_tenant, make_user)
    repo = PostgresClientRepository(test_session_factory)

    client = await repo.create_client(
        tenant_a.id, cuit=CUIT_A, name='Acme SA', email='acme@corp.ar', config={'notas': 'x'}
    )
    assert client.id
    assert client.tenant_id == str(tenant_a.id)
    assert client.cuit == CUIT_A
    assert client.name == 'Acme SA'
    assert client.email == 'acme@corp.ar'
    assert client.config == {'notas': 'x'}
    assert client.created_at is not None


async def test_list_clients_no_cross_tenant_leak(
    test_session_factory, make_tenant, make_user
) -> None:
    tenant_a, tenant_b = await _create_tenants(test_session_factory, make_tenant, make_user)
    repo = PostgresClientRepository(test_session_factory)
    await repo.create_client(tenant_a.id, cuit=CUIT_A, name='Acme')

    clients_a = await repo.list_clients(tenant_a.id)
    clients_b = await repo.list_clients(tenant_b.id)
    assert [c.cuit for c in clients_a] == [CUIT_A]
    assert clients_b == []


async def test_get_client_is_scoped_to_tenant(
    test_session_factory, make_tenant, make_user
) -> None:
    tenant_a, tenant_b = await _create_tenants(test_session_factory, make_tenant, make_user)
    repo = PostgresClientRepository(test_session_factory)
    client = await repo.create_client(tenant_a.id, cuit=CUIT_A, name='Acme')

    assert await repo.get_client(tenant_b.id, uuid.UUID(client.id)) is None
    visible = await repo.get_client(tenant_a.id, uuid.UUID(client.id))
    assert visible is not None
    assert visible.cuit == CUIT_A


async def test_delete_client_foreign_tenant_does_not_delete(
    test_session_factory, make_tenant, make_user
) -> None:
    tenant_a, tenant_b = await _create_tenants(test_session_factory, make_tenant, make_user)
    repo = PostgresClientRepository(test_session_factory)
    client = await repo.create_client(tenant_a.id, cuit=CUIT_A, name='Acme')

    deleted = await repo.delete_client(tenant_b.id, uuid.UUID(client.id))
    assert deleted is False
    assert await repo.get_client(tenant_a.id, uuid.UUID(client.id)) is not None


async def test_delete_client_own_tenant_removes_it(
    test_session_factory, make_tenant, make_user
) -> None:
    tenant_a, _ = await _create_tenants(test_session_factory, make_tenant, make_user)
    repo = PostgresClientRepository(test_session_factory)
    client = await repo.create_client(tenant_a.id, cuit=CUIT_A, name='Acme')

    deleted = await repo.delete_client(tenant_a.id, uuid.UUID(client.id))
    assert deleted is True
    assert await repo.get_client(tenant_a.id, uuid.UUID(client.id)) is None
    assert await repo.list_clients(tenant_a.id) == []


async def test_delete_client_missing_returns_false(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant_a = await make_tenant(session)
    repo = PostgresClientRepository(test_session_factory)
    assert await repo.delete_client(tenant_a.id, uuid.uuid4()) is False


async def test_duplicate_cuit_same_tenant_raises(
    test_session_factory, make_tenant, make_user
) -> None:
    tenant_a, _ = await _create_tenants(test_session_factory, make_tenant, make_user)
    repo = PostgresClientRepository(test_session_factory)
    await repo.create_client(tenant_a.id, cuit=CUIT_A, name='Acme')

    with pytest.raises(ClientAlreadyExistsError):
        await repo.create_client(tenant_a.id, cuit=CUIT_A, name='Dupe')


async def test_same_cuit_different_tenant_allowed(
    test_session_factory, make_tenant, make_user
) -> None:
    tenant_a, tenant_b = await _create_tenants(test_session_factory, make_tenant, make_user)
    repo = PostgresClientRepository(test_session_factory)

    in_a = await repo.create_client(tenant_a.id, cuit=CUIT_A, name='Acme')
    in_b = await repo.create_client(tenant_b.id, cuit=CUIT_A, name='Other firm')
    assert in_a.id != in_b.id
    assert len(await repo.list_clients(tenant_a.id)) == 1
    assert len(await repo.list_clients(tenant_b.id)) == 1


async def test_get_client_missing_returns_none(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant_a = await make_tenant(session)
    repo = PostgresClientRepository(test_session_factory)
    assert await repo.get_client(tenant_a.id, uuid.uuid4()) is None