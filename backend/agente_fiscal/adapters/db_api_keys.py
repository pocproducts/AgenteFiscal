"""Postgres-backed API key adapter (Cutover Phase 5).

Implements :class:`agente_fiscal.ports.api_keys.ApiKeyPort` (auth resolution)
and :class:`agente_fiscal.ports.api_keys.ApiKeyRepository` (admin CRUD) against
the ORM models in ``agente_fiscal.db.models.core``. Redis is no longer the
source of truth for API keys / apps / plans / developers — it only remains
rate-limit/cache (JWKS, TA) and best-effort conversations.

Mapping decisions (documented, essential scope):
  - ``hash_api_key`` mirrors the old ``RedisStore._hash_key`` EXACTLY (sha256
    hex of the raw ``fa_`` key), so a key created here resolves through the
    same lookup contract as the archived Redis flow. Both the auth middleware
    and key creation use this single function, via this module.
  - A "developer" maps to a ``User`` row plus a ``TenantMember`` (role
    ``'owner'``/``'admin'``) on the seed tenant (``Estudio Contable``). The
    ORM has no ``Developer`` entity; ``Apps.developer_id`` already points at
    ``users.id``.
  - ORM ``ApiKey`` has no ``app_id``/``scopes``/``key_preview`` columns (the
    schema predates the Redis domains). ``key_preview`` (last 4 plaintext
    chars) is carried inside ``ApiKey.name`` at creation; scopes come from the
    tenant's resolved plan (``db.auth.get_active_plan`` → ``features``), same
    rule the Clerk path already uses.
  - ORM ``App`` has no ``environment``/``status`` columns. ``environment`` is
    honored on create (request-only, not persisted); resolution defaults
    ``environment='production'``, ``status='active'``. A suspended-app concept
    is not representable in the schema yet (documented gap).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agente_fiscal.db.auth import get_active_plan
from agente_fiscal.db.models.core import (
	ApiKey as ApiKeyRow,
	App as AppRow,
	Tenant as TenantRow,
	TenantMember,
	User as UserRow,
)
from agente_fiscal.domain.models import ApiKey, App, Developer
from agente_fiscal.ports.api_keys import ApiKeyContext, ApiKeyStoreUnavailableError

logger = logging.getLogger(__name__)

#: Name of the seeded tenant from Fase 1 (db/seed.py). Developers register
#: into this single-tenant world, mirroring the old "one developer" assumption.
_DEFAULT_TENANT_NAME = 'Estudio Contable'

#: Fallback scopes for a fresh key when the tenant has no resolvable plan.
_DEFAULT_SCOPES: list[str] = ['chat:read', 'chat:write']


def hash_api_key(raw_key: str) -> str:
	"""SHA-256 hexdigest of a raw API key — identical to the archived Redis ``_hash_key``.

	This is the single shared hash for both auth resolution and key creation.
	"""
	return hashlib.sha256(raw_key.encode()).hexdigest()


def _as_uuid(value: object) -> UUID | None:
	"""Parse str/UUID to ``UUID``, returning ``None`` for non-UUID handles.

	The Clerk flow used virtual app handles like ``tapp_<id>`` grouped to a
	tenant; those are not real UUIDs and must not be sent to ``asyncpg``
	(a non-UUID bind on a ``uuid`` column raises ``DataError``).
	"""
	if isinstance(value, UUID):
		return value
	try:
		return UUID(str(value))
	except (ValueError, TypeError):
		return None


def _preview_from_name(name: str) -> str:
	"""Extract the stored last-4 preview (``… ' (abcd)'`` suffix) from ``ApiKey.name``."""
	if name and '(' in name and name.rstrip().endswith(')'):
		inner = name.rsplit('(', 1)[1][:-1].strip()
		if len(inner) == 4:
			return inner
	return ''


def _to_developer(user: UserRow) -> Developer:
	"""Map a ``User`` row to the pydantic Developer state/response contract."""
	return Developer(
		id=str(user.id),
		name=user.display_name or user.email or '',
		email=user.email,
		created_at=user.created_at,
		is_active=True,
	)


def _to_app(row: AppRow) -> App:
	"""Map an ORM ``App`` row to the pydantic App contract."""
	return App(
		id=str(row.id),
		developer_id=str(row.developer_id) if row.developer_id else '',
		name=row.name,
		environment='production',
		status='active',
	)


def _to_api_key(
	row: ApiKeyRow,
	*,
	app_id: str,
	scopes: list[str],
	preview: str | None = None,
) -> ApiKey:
	"""Map an ORM ``ApiKey`` row to the pydantic ApiKey state contract."""
	return ApiKey(
		id=str(row.id),
		app_id=app_id,
		key_preview=preview if preview is not None else _preview_from_name(row.name),
		is_active=bool(row.is_active),
		scopes=list(scopes),
		tenant_id=str(row.tenant_id),
		created_at=row.created_at,
	)


class PostgresApiKeyPort:
	"""Concrete port: API key resolution + admin CRUD over Postgres.

	Accepts an ``async_sessionmaker`` (the app's ``async_session_factory`` from
	``agente_fiscal.db.session``). Sessions are created per call, so the port is
	stateless and safe to share across requests/workers.
	"""

	def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
		self._session_factory = session_factory

	# ── ApiKeyPort: auth resolution ───────────────────────────────────

	async def resolve(self, key_hash: str) -> ApiKeyContext | None:
		"""Resolve a hashed key to its full auth context (see port docstring)."""
		async with self._session_factory() as session:
			try:
				row = await session.scalar(
					select(ApiKeyRow).where(
						ApiKeyRow.key_hash == key_hash,
						ApiKeyRow.is_active.is_(True),
						ApiKeyRow.revoked_at.is_(None),
					)
				)
				if row is None:
					return None

				plan = await get_active_plan(session, row.tenant_id)
				scopes = plan.scopes if plan else list(_DEFAULT_SCOPES)

				# App (informational state; mirrors the old request.state.app
				# contract) — first app of the tenant.
				app_row = await session.scalar(
					select(AppRow).where(AppRow.tenant_id == row.tenant_id).limit(1)
				)
				app = _to_app(app_row) if app_row else None

				# Developer = first owner/admin member of the tenant.
				developer = await self._find_developer(session, row.tenant_id)

				return ApiKeyContext(
					api_key=_to_api_key(
						row,
						app_id=app.id if app else '',
						scopes=scopes,
					),
					app=app,
					developer=developer,
					plan=plan,
					tenant_id=row.tenant_id,
					scopes=scopes,
				)
			except SQLAlchemyError as exc:
				# DB down / connection error — surface as 503, never None
				# (None would be indistinguishable from "key not found" → 401).
				logger.error('Postgres unavailable while resolving API key: %s', exc)
				await session.rollback()
				raise ApiKeyStoreUnavailableError(str(exc)) from exc
			except Exception:
				logger.exception('Unexpected error resolving API key')
				await session.rollback()
				raise

	# ── ApiKeyRepository: admin CRUD ──────────────────────────────────

	async def get_developer_by_email(self, email: str) -> Developer | None:
		async with self._session_factory() as session:
			user = await session.scalar(select(UserRow).where(UserRow.email == email).limit(1))
			return _to_developer(user) if user is not None else None

	async def register_developer(self, name: str, email: str) -> Developer:
		"""Create a ``User`` + ``TenantMember`` (role ``'admin'``) on the seed tenant.

		Concurrency-safe: on a unique-index collision (deterministic
		``clerk_user_id`` derived from the email) the existing row is returned.
		"""
		clerk_user_id = f'dev:{hashlib.sha256(email.encode()).hexdigest()[:16]}'
		async with self._session_factory() as session:
			try:
				tenant = await self._get_or_create_seed_tenant(session)
				user = UserRow(
					clerk_user_id=clerk_user_id,
					email=email,
					display_name=name,
				)
				session.add(user)
				await session.flush()
				session.add(TenantMember(tenant_id=tenant.id, user_id=user.id, role='admin'))
				await session.commit()
				logger.info('Registered developer %s on tenant %s', email, tenant.id)
				return _to_developer(user)
			except IntegrityError:
				await session.rollback()
				existing = await session.scalar(
					select(UserRow).where(UserRow.clerk_user_id == clerk_user_id)
				)
				if existing is not None:
					return _to_developer(existing)
				raise

	async def create_app(
		self, developer_id: str, name: str, environment: str
	) -> App | None:
		"""Create an app for a developer. Returns ``None`` if the developer is unknown.

		``environment`` is honored on create but not persisted (no ORM column);
		see module docstring.
		"""
		dev_uuid = _as_uuid(developer_id)
		if dev_uuid is None:
			return None
		async with self._session_factory() as session:
			user = await session.get(UserRow, dev_uuid)
			if user is None:
				return None
			tenant = await self._tenant_for_user(session, user.id)
			if tenant is None:
				tenant = await self._get_or_create_seed_tenant(session)
			row = AppRow(tenant_id=tenant.id, developer_id=user.id, name=name)
			session.add(row)
			await session.commit()
			await session.refresh(row)
			return App(
				id=str(row.id),
				developer_id=str(user.id),
				name=row.name,
				environment=environment,
				status='active',
			)

	async def get_app(self, app_id: str) -> App | None:
		app_uuid = _as_uuid(app_id)
		if app_uuid is None:
			return None
		async with self._session_factory() as session:
			row = await session.get(AppRow, app_uuid)
			return _to_app(row) if row is not None else None

	async def create_api_key(
		self,
		app_id: str,
		*,
		tenant_id: str | None = None,
		scopes: list[str] | None = None,
	) -> dict | None:
		"""Create an API key. Returns ``{'api_key', 'full_key'}`` or ``None``.

		Tenant resolution order:
		  1. ``app_id`` (a real UUID) → its owning tenant;
		  2. else ``tenant_id`` (Clerk flow, apps no longer required);
		  3. else ``None`` (the caller reports 404, matching the old contract).
		"""
		async with self._session_factory() as session:
			try:
				tid: UUID | None = None
				app_label: str | None = None

				app_uuid = _as_uuid(app_id)
				if app_uuid is not None:
					app_row = await session.get(AppRow, app_uuid)
					if app_row is not None:
						tid = app_row.tenant_id
						app_label = app_row.name

				if tid is None and tenant_id:
					tid = _as_uuid(tenant_id)

				if tid is None:
					return None

				full_key = f'fa_{secrets.token_hex(16)}'
				preview = full_key[-4:]
				label = f'Key for {app_label}' if app_label else 'API key'

				plan = await get_active_plan(session, tid)
				key_scopes = (
					list(scopes)
					if scopes is not None
					else (plan.scopes if plan is not None else list(_DEFAULT_SCOPES))
				)

				row = ApiKeyRow(
					tenant_id=tid,
					key_hash=hash_api_key(full_key),
					name=f'{label} ({preview})',
					is_active=True,
				)
				session.add(row)
				await session.flush()

				pydantic_key = _to_api_key(
					row,
					app_id=app_id or str(tid),
					scopes=key_scopes,
					preview=preview,
				)
				await session.commit()
				return {'api_key': pydantic_key, 'full_key': full_key}
			except SQLAlchemyError as exc:
				logger.error('Postgres unavailable while creating API key: %s', exc)
				await session.rollback()
				raise ApiKeyStoreUnavailableError(str(exc)) from exc

	async def list_developer_keys(self, developer_id: str) -> list[ApiKey]:
		"""List all keys of the tenant the developer belongs to (old semantic:
		"keys across all apps owned by the developer" → tenant-scoped keys)."""
		dev_uuid = _as_uuid(developer_id)
		if dev_uuid is None:
			return []
		async with self._session_factory() as session:
			user = await session.get(UserRow, dev_uuid)
			if user is None:
				return []
			tenant = await self._tenant_for_user(session, user.id)
			if tenant is None:
				return []
			return await self._list_keys_for_tenant(session, tenant.id)

	async def list_tenant_keys(self, tenant_id: str) -> list[ApiKey]:
		tid = _as_uuid(tenant_id)
		if tid is None:
			return []
		async with self._session_factory() as session:
			return await self._list_keys_for_tenant(session, tid)

	async def deactivate_key(self, key_id: str, tenant_id: str) -> bool:
		"""Set ``is_active=False`` for a key owned by *tenant_id* (idempotent)."""
		kid = _as_uuid(key_id)
		tid = _as_uuid(tenant_id)
		if kid is None or tid is None:
			return False
		async with self._session_factory() as session:
			row = await session.get(ApiKeyRow, kid)
			if row is None or row.tenant_id != tid:
				return False
			row.is_active = False
			await session.commit()
			return True

	# ── Private helpers ──────────────────────────────────────────────

	async def _get_or_create_seed_tenant(self, session: AsyncSession) -> TenantRow:
		"""Return the seeded ``Estudio Contable`` tenant, creating it when missing.

		Idempotent (mirrors ``db/seed.py``): register can run on an empty DB.
		"""
		tenant = await session.scalar(
			select(TenantRow).where(TenantRow.name == _DEFAULT_TENANT_NAME).limit(1)
		)
		if tenant is None:
			tenant = TenantRow(name=_DEFAULT_TENANT_NAME, clerk_org_id=None)
			session.add(tenant)
			await session.flush()
			logger.info('Created seed tenant %s', _DEFAULT_TENANT_NAME)
		return tenant

	async def _tenant_for_user(self, session: AsyncSession, user_id: UUID) -> TenantRow | None:
		"""First tenant the user is a member of."""
		member = await session.scalar(
			select(TenantMember).where(TenantMember.user_id == user_id).limit(1)
		)
		if member is None:
			return None
		return await session.get(TenantRow, member.tenant_id)

	async def _find_developer(self, session: AsyncSession, tenant_id: UUID) -> Developer | None:
		"""First ``owner``/``admin`` ``User`` of the tenant, if any."""
		member = await session.scalar(
			select(TenantMember)
			.where(
				TenantMember.tenant_id == tenant_id,
				TenantMember.role.in_(('owner', 'admin')),
			)
			.limit(1)
		)
		if member is None:
			return None
		user = await session.get(UserRow, member.user_id)
		return _to_developer(user) if user is not None else None

	async def _list_keys_for_tenant(self, session: AsyncSession, tenant_id: UUID) -> list[ApiKey]:
		"""All keys of a tenant, newest first, with plan-derived scopes."""
		plan = await get_active_plan(session, tenant_id)
		scopes = plan.scopes if plan is not None else list(_DEFAULT_SCOPES)
		rows = (
			await session.execute(
				select(ApiKeyRow)
				.where(ApiKeyRow.tenant_id == tenant_id)
				.order_by(ApiKeyRow.created_at.desc())
			)
		).scalars().all()
		app_row = await session.scalar(
			select(AppRow).where(AppRow.tenant_id == tenant_id).limit(1)
		)
		app_id = str(app_row.id) if app_row is not None else ''
		return [_to_api_key(r, app_id=app_id, scopes=scopes) for r in rows]


__all__ = [
	'PostgresApiKeyPort',
	'hash_api_key',
]