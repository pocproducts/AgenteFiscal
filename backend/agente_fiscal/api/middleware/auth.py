"""AuthMiddleware — Bearer token + X-API-Key dual support.

The ``fa_`` API-key path resolves the full entity chain
(ApiKey → App → Developer → Plan) through the hexagonal
:class:`agente_fiscal.ports.api_keys.ApiKeyPort` (Postgres-backed), and
injects it into ``request.state``. Redis is no longer consulted for business
data; it remains rate-limit/cache (and the Clerk JWKS cache).
"""

from __future__ import annotations

import logging

from fastapi import Request, Response
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from agente_fiscal.adapters.db_api_keys import hash_api_key
from agente_fiscal.api.middleware.clerk import ClerkJWTExtractor
from agente_fiscal.api.store import RedisStore  # type annotation for the kept signature
from agente_fiscal.domain.models import ApiError, UnifiedResponse
from agente_fiscal.ports.api_keys import ApiKeyPort, ApiKeyStoreUnavailableError

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

		The hash + lookup are delegated to the Postgres-backed
		``ApiKeyPort`` (``request.app.state.api_key_port``). On DB
		unavailability the port raises :class:`ApiKeyStoreUnavailableError`,
		which the caller maps to the degraded 503 — never a crash.

		State injected on success (same contract as the Redis era, plus the
		Phase 5 improvement):
		  - ``api_key`` / ``app`` / ``developer`` / ``plan`` — pydantic objects
		  - ``tenant_id`` — UUID, now read directly from the ``ApiKey`` row
		  - ``scopes`` — ``chat:read``/``chat:write``-style, from the plan
		  - ``auth_method`` = ``'api_key'``
		  - ``rate_limit_config`` — ``{'rpm': ..., 'rpd': ...}`` from the plan

		Returns ``True`` on success, ``False`` on any failure.
		"""
		port: ApiKeyPort | None = getattr(request.app.state, 'api_key_port', None)
		if port is None:
			logger.error('No api_key_port configured — API-key auth unavailable')
			return False

		ctx = await port.resolve(hash_api_key(raw_key))
		if ctx is None:
			return False

		request.state.developer = ctx.developer
		request.state.app = ctx.app
		request.state.api_key = ctx.api_key
		request.state.plan = ctx.plan
		request.state.tenant_id = str(ctx.tenant_id) if ctx.tenant_id else None
		request.state.tenant = None
		request.state.scopes = list(ctx.scopes)
		request.state.auth_method = 'api_key'
		request.state.rate_limit_config = {'rpm': ctx.rpm, 'rpd': ctx.rpd}

		return True

	async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
		# ── Public path bypass ────────────────────────────────────────
		# NOTE: CORS preflight (OPTIONS) is handled by CORSMiddleware
		# (outermost), so it never reaches AuthMiddleware.
		if request.method in ('GET', 'POST') and request.url.path in _PUBLIC_PATHS:
			return await call_next(request)

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
			try:
				ok = await self._resolve_api_key(raw_key, request, redis, store)
			except ApiKeyStoreUnavailableError:
				# Postgres down for the key-resolution path → same degraded
				# 503 the Redis outage path uses, never a 500.
				logger.error('Postgres unavailable for API-key auth — returning 503')
				return JSONResponse(
					status_code=503,
					content=UnifiedResponse(
						status='error',
						error=ApiError(code='SERVICE_UNAVAILABLE', cause='Servicio temporalmente no disponible'),
					).model_dump(),
				)
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
