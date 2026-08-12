"""API-key ports — contracts for resolving/managing API keys, apps and plans.

Cutover Phase 5: business data (API keys, apps, plans, developers) moves out
of Redis into Postgres. The web layer (auth middleware, admin routes) depends
only on these protocols; concrete infrastructure lives in
``fiscal_agent.adapters.db_api_keys``.

Two contracts, one backing store:
  - :class:`ApiKeyPort` — what the auth middleware needs to resolve a raw
    ``fa_`` key into the full auth context (key/app/developer/plan/tenant).
  - :class:`ApiKeyRepository` — what the admin self-service routes need to
    create/list/deactivate keys, apps and developers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from fiscal_agent.domain.models import ApiKey, App, Developer, Plan

#: Fallback rate limits when no plan can be resolved (mirrors db/auth.py).
_DEFAULT_RPM = 10
_DEFAULT_RPD = 100
#: Default scopes until the catalog carries per-plan scopes (mirrors db/auth.py).
_DEFAULT_SCOPES: list[str] = ['chat:read', 'chat:write']


class ApiKeyStoreUnavailableError(RuntimeError):
	"""Raised by the adapter when the backing Postgres store is unreachable.

	The auth middleware maps this to the same 503 response used by the
	degraded Redis path — a controlled failure, never a crash (500).
	"""


@dataclass
class ApiKeyContext:
	"""Fully resolved auth context for one API key.

	``api_key``/``app``/``developer`` are the pydantic state objects injected
	into ``request.state`` by the auth middleware (same shape as the old
	Redis world). ``tenant_id`` is the owning tenant UUID from the Postgres
	``ApiKey`` row — previously derived from scopes, now direct.
	"""

	api_key: ApiKey | None = None
	app: App | None = None
	developer: Developer | None = None
	plan: Plan | None = None
	tenant_id: uuid.UUID | None = None
	scopes: list[str] = field(default_factory=lambda: list(_DEFAULT_SCOPES))

	@property
	def rpm(self) -> int:
		"""Requests per minute derived from the resolved plan limits."""
		return self.plan.rate_limit_rpm if self.plan else _DEFAULT_RPM

	@property
	def rpd(self) -> int:
		"""Requests per day derived from the resolved plan limits."""
		return self.plan.rate_limit_rpd if self.plan else _DEFAULT_RPD


@runtime_checkable
class ApiKeyPort(Protocol):
	"""Resolves a hashed API key to its full auth context."""

	async def resolve(self, key_hash: str) -> ApiKeyContext | None:
		"""Return the auth context for *key_hash* (sha256 hex), or ``None``.

		A key that is missing, inactive or revoked returns ``None`` (→ 401 in
		the auth middleware). A Postgres connectivity failure raises
		:class:`ApiKeyStoreUnavailableError` (→ 503) instead of ``None``.
		"""
		...


@runtime_checkable
class ApiKeyRepository(Protocol):
	"""Admin/self-service CRUD for developers, apps and API keys.

	Return types mirror the old ``RedisStore`` contract so the admin route
	response envelopes stay shape-compatible.
	"""

	async def get_developer_by_email(self, email: str) -> Developer | None:
		"""Look up a developer (a ``User`` row) by email."""
		...

	async def register_developer(self, name: str, email: str) -> Developer:
		"""Register a new developer on the seed tenant (``User`` + ``TenantMember``)."""
		...

	async def create_app(
		self, developer_id: str, name: str, environment: str
	) -> App | None:
		"""Create an app for a developer. Returns ``None`` if the developer is unknown."""
		...

	async def get_app(self, app_id: str) -> App | None:
		"""Fetch an app by id (ownership checks in admin routes)."""
		...

	async def create_api_key(
		self,
		app_id: str,
		*,
		tenant_id: str | None = None,
		scopes: list[str] | None = None,
	) -> dict | None:
		"""Create an API key. Returns ``{'api_key': ..., 'full_key': ...}`` or ``None``.

		``app_id`` resolves the owning tenant when ``tenant_id`` is omitted
		(register / dev-key flows). Clerk flow passes ``tenant_id`` directly.
		The plaintext ``full_key`` is returned exactly once; only its sha256
		hash is stored.
		"""
		...

	async def list_developer_keys(self, developer_id: str) -> list[ApiKey]:
		"""List all keys of the tenant the developer belongs to."""
		...

	async def list_tenant_keys(self, tenant_id: str) -> list[ApiKey]:
		"""List all keys of a tenant."""
		...

	async def deactivate_key(self, key_id: str, tenant_id: str) -> bool:
		"""Set ``is_active=False`` for a key, verifying tenant ownership."""
		...


__all__ = [
	'ApiKeyContext',
	'ApiKeyPort',
	'ApiKeyRepository',
	'ApiKeyStoreUnavailableError',
]