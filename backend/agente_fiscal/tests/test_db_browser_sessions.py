"""Tests del store de sesiones de browser (adapters/db_browser_sessions.py).

Cubren el ciclo de vida real contra Postgres: acquire (None sin fila, reuso de
fila activa no vencida, NO reuso de vencida), create (status in_use) y release
(status active + métricas + swap de context_id). El claim atómico (FOR UPDATE
SKIP LOCKED) es el mismo patrón probado en runner.py — acá se cubre el
comportamiento observable del ciclo.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from agente_fiscal.adapters.db_browser_sessions import PostgresBrowserSessionsRepository
from agente_fiscal.db.models import BrowserSession as BrowserSessionRow
from agente_fiscal.db.models import Profile as ProfileRow

pytestmark = pytest.mark.usefixtures('db_reset')


async def _insert_active(
	test_session_factory,
	*,
	tenant_id,
	profile_id=None,
	provider='browserbase',
	context_id='ctx-1',
	expires_at=None,
	**extra,
) -> BrowserSessionRow:
	"""Inserta una fila directamente (evita el ciclo create/in_use → release)."""
	async with test_session_factory() as session:
		row = BrowserSessionRow(
			tenant_id=tenant_id,
			profile_id=profile_id,
			provider=provider,
			context_id=context_id,
			status=extra.pop('status', 'active'),
			expires_at=expires_at,
			started_at=datetime.now(timezone.utc) - timedelta(minutes=1),
			ended_at=datetime.now(timezone.utc),
			**extra,
		)
		session.add(row)
		await session.commit()
		await session.refresh(row)
		return row


# ── acquire: sin fila → None ────────────────────────────────────────────────


async def test_acquire_returns_none_without_row(test_session_factory, make_tenant) -> None:
	async with test_session_factory() as session:
		tenant = await make_tenant(session)
	uuid4 = tenant.id

	store = PostgresBrowserSessionsRepository(test_session_factory)
	assert await store.acquire(uuid4, None, provider='browserbase') is None
	assert await store.acquire(uuid4, None, provider='composio') is None


# ── acquire: reuso de fila activa no vencida (active → in_use) ──────────────


async def test_acquire_reuses_active_unexpired_row(test_session_factory, make_tenant) -> None:
	async with test_session_factory() as session:
		tenant = await make_tenant(session)
	row = await _insert_active(
		test_session_factory,
		tenant_id=tenant.id,
		context_id='ctx-reuse',
		expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
	)

	store = PostgresBrowserSessionsRepository(test_session_factory)
	sess = await store.acquire(tenant.id, None, provider='browserbase')

	assert sess is not None
	assert sess.context_id == 'ctx-reuse'
	assert sess.status == 'in_use'

	async with test_session_factory() as session:
		db_row = await session.get(BrowserSessionRow, row.id)
		assert db_row.status == 'in_use'


# ── acquire: fila vencida → None ────────────────────────────────────────────


async def test_acquire_ignores_expired_row(test_session_factory, make_tenant) -> None:
	async with test_session_factory() as session:
		tenant = await make_tenant(session)
	await _insert_active(
		test_session_factory,
		tenant_id=tenant.id,
		context_id='ctx-vencido',
		expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
	)

	store = PostgresBrowserSessionsRepository(test_session_factory)
	assert await store.acquire(tenant.id, None, provider='browserbase') is None


# ── create: inserta la fila como in_use ─────────────────────────────────────


async def test_create_inserts_in_use(test_session_factory, make_tenant) -> None:
	async with test_session_factory() as session:
		tenant = await make_tenant(session)
	expires = datetime.now(timezone.utc) + timedelta(hours=1)

	store = PostgresBrowserSessionsRepository(test_session_factory)
	sess = await store.create(
		tenant_id=tenant.id,
		profile_id=None,
		provider='browserbase',
		context_id='ctx-new',
		expires_at=expires,
	)

	assert sess.status == 'in_use'
	assert sess.context_id == 'ctx-new'
	assert sess.tenant_id == str(tenant.id)
	async with test_session_factory() as session:
		total = (await session.execute(select(BrowserSessionRow))).scalars().all()
		assert len(total) == 1


# ── release: marca active + guarda métricas + renueva expires_at ────────────


async def test_release_marks_active_and_saves_metrics(test_session_factory, make_tenant) -> None:
	async with test_session_factory() as session:
		tenant = await make_tenant(session)
	expires = datetime.now(timezone.utc) + timedelta(hours=1)

	store = PostgresBrowserSessionsRepository(test_session_factory)
	sess = await store.create(
		tenant_id=tenant.id,
		profile_id=None,
		provider='browserbase',
		context_id='ctx-metrics',
		expires_at=expires,
	)

	now = datetime.now(timezone.utc)
	started = now - timedelta(seconds=90)
	released = await store.release(
		id=uuid.UUID(sess.id),
		session_id='sess-123',
		proxy_bytes=2048,
		duration_ms=90000,
		cost_cents=0,
		started_at=started,
		ended_at=now,
		last_used_at=now,
		expires_at=now + timedelta(hours=1),
	)

	assert released is not None
	assert released.status == 'active'
	assert released.session_id == 'sess-123'
	assert released.proxy_bytes == 2048
	assert released.duration_ms == 90000
	assert released.cost_cents == 0

	reused = await store.acquire(tenant.id, None, provider='browserbase')
	assert reused is not None
	assert reused.status == 'in_use'
	assert reused.context_id == 'ctx-metrics'


# ── release: swap de context_id cuando el contexto se recreó ────────────────


async def test_release_updates_context_id(test_session_factory, make_tenant) -> None:
	async with test_session_factory() as session:
		tenant = await make_tenant(session)
	store = PostgresBrowserSessionsRepository(test_session_factory)
	created = await store.create(
		tenant_id=tenant.id,
		profile_id=None,
		provider='browserbase',
		context_id='ctx-viejo',
		expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
	)

	now = datetime.now(timezone.utc)
	released = await store.release(
		id=uuid.UUID(created.id),
		context_id='ctx-recreado',
		session_id='sess-456',
		last_used_at=now,
		expires_at=now + timedelta(hours=1),
	)

	assert released.context_id == 'ctx-recreado'
	assert released.session_id == 'sess-456'
	assert released.status == 'active'


# ── unique (tenant_id, profile_id, provider): JCC no rompe el reuso ─────────


async def test_acquire_scoped_by_profile(test_session_factory, make_tenant) -> None:
	async with test_session_factory() as session:
		tenant = await make_tenant(session)
		profile_row = ProfileRow(
			tenant_id=tenant.id,
			name='Perfil A',
			status='active',
			config={},
		)
		session.add(profile_row)
		await session.commit()
		await session.refresh(profile_row)
	await _insert_active(
		test_session_factory,
		tenant_id=tenant.id,
		profile_id=profile_row.id,
		context_id='ctx-profile',
		expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
	)

	store = PostgresBrowserSessionsRepository(test_session_factory)
	# El mismo tenant SIN profile no ve la fila del profile.
	assert await store.acquire(tenant.id, None, provider='browserbase') is None
	# Con el profile sí la reusa.
	sess = await store.acquire(tenant.id, profile_row.id, provider='browserbase')
	assert sess is not None and sess.context_id == 'ctx-profile'