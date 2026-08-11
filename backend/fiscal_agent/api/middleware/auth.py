"""AuthMiddleware — Bearer token + X-API-Key dual support.

Resolves the full entity chain (ApiKey → App → Developer → Plan)
via Redis and injects into ``request.state``.
"""

from __future__ import annotations

import logging

from fastapi import Request, Response
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from fiscal_agent.api.middleware.clerk import ClerkJWTExtractor
from fiscal_agent.api.store import RedisStore, _KEY_APIKEY, _KEY_APP, _KEY_DEVELOPER, _KEY_KEYHASH
from fiscal_agent.domain.models import ApiError, ApiKey, App, Developer, Plan, UnifiedResponse

logger = logging.getLogger(__name__)

# Paths that bypass auth entirely
_PUBLIC_PATHS = frozenset(
	{
		'/v1/health',
		'/v1/admin/register',
	}
)


class AuthMiddleware(BaseHTTPMiddleware):
	"""Extract Bearer token, resolve entity chain, inject state.

	Order: CORS → RateLimit → TenantContext → **Auth** → Metrics → Route
	"""

	async def _resolve_api_key(self, raw_key: str, request: Request, redis: Redis, store: RedisStore) -> bool:
		"""Resolve an API key (``fa_`` prefix) and inject developer/app/key/plan state.

		Returns ``True`` on success, ``False`` on any failure.
		"""
		# ── SHA-256 → Redis lookup ────────────────────────────────────
		key_hash = RedisStore._hash_key(raw_key)
		api_key_id = await redis.get(_KEY_KEYHASH.format(key_hash))
		if not api_key_id:
			return False

		# ── Resolve ApiKey ────────────────────────────────────────────
		api_key_data = await redis.hgetall(_KEY_APIKEY.format(api_key_id))
		if not api_key_data:
			return False
		api_key: ApiKey = RedisStore._deserialize(ApiKey, api_key_data)

		if not api_key.is_active:
			return False

		# ── Resolve App ───────────────────────────────────────────────
		app_data = await redis.hgetall(_KEY_APP.format(api_key.app_id))
		if not app_data:
			return False
		app: App = RedisStore._deserialize(App, app_data)

		if app.status == 'suspended':
			return False

		# ── Resolve Developer ─────────────────────────────────────────
		dev_data = await redis.hgetall(_KEY_DEVELOPER.format(app.developer_id))
		if not dev_data:
			return False
		developer: Developer = RedisStore._deserialize(Developer, dev_data)

		if not developer.is_active:
			return False

		# ── Resolve Plan ──────────────────────────────────────────────
		plan = await store._resolve_plan(api_key.scopes)

		# ── Inject state ──────────────────────────────────────────────
		request.state.developer = developer
		request.state.app = app
		request.state.api_key = api_key
		request.state.plan = plan
		request.state.auth_method = 'api_key'

		return True

	async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
		# ── Public path bypass ────────────────────────────────────────
		# NOTE: CORS preflight (OPTIONS) is handled by CORSMiddleware
		# (outermost), so it never reaches AuthMiddleware.
		if request.method in ('GET', 'POST') and request.url.path in _PUBLIC_PATHS:
			return await call_next(request)

		# ── Redis down — boot was degraded but the app stayed up ────────
		# Health stays reachable (public path above); every other request
		# must fail fast with 503 instead of an AttributeError stacktrace.
		if getattr(request.app.state, 'redis', None) is None:
			return JSONResponse(
				status_code=503,
				content=UnifiedResponse(
					status='error',
					error=ApiError(code='SERVICE_UNAVAILABLE', cause='Servicio temporalmente no disponible'),
				).model_dump(),
			)

		# ── Extract raw key (Bearer preferred, fallback X-API-Key) ────
		raw_key: str | None = None
		auth_header = request.headers.get('Authorization', '')
		if auth_header.startswith('Bearer '):
			raw_key = auth_header[7:]
		else:
			x_api_key = request.headers.get('X-API-Key')
			if x_api_key:
				raw_key = x_api_key
			elif auth_header:
				# Wrong scheme (Basic, Digest, etc.) → 401
				return JSONResponse(
					status_code=401,
					content=UnifiedResponse(
						status='error',
						error=ApiError(code='UNAUTHORIZED', cause='Scheme de autenticación inválido. Usá Bearer.'),
					).model_dump(),
				)

		if not raw_key:
			return JSONResponse(
				status_code=401,
				content=UnifiedResponse(
					status='error',
					error=ApiError(code='UNAUTHORIZED', cause='Header Authorization faltante o inválido'),
				).model_dump(),
			)

		# ── Dual extractor dispatch ───────────────────────────────────
		redis = request.app.state.redis  # type: ignore[attr-defined]
		store: RedisStore = request.app.state.store  # type: ignore[attr-defined]

		if raw_key.startswith('fa_'):
			ok = await self._resolve_api_key(raw_key, request, redis, store)
		else:
			factory = getattr(request.app.state, 'session_factory', None)
			extractor = ClerkJWTExtractor(factory)
			ok = await extractor.handle(raw_key, request, redis)

		if not ok:
			clerk_error = getattr(request.state, 'clerk_error', None)
			if clerk_error == 'TENANT_NOT_FOUND':
				return JSONResponse(
					status_code=401,
					content=UnifiedResponse(
						status='error',
						error=ApiError(
							code='TENANT_NOT_FOUND',
							cause='El tenant no existe. Verificá que la org de Clerk esté registrada.',
						),
					).model_dump(),
				)
			return JSONResponse(
				status_code=401,
				content=UnifiedResponse(
					status='error',
					error=ApiError(code='UNAUTHORIZED', cause='Token de autenticación inválido o expirado'),
				).model_dump(),
			)

		return await call_next(request)
