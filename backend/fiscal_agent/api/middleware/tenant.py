"""TenantContextMiddleware — resolve tenant from api_key.tenant_id.

Non-blocking enrichment middleware. NEVER returns an error — silently
sets ``request.state.tenant = None`` and passes through.
"""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from fiscal_agent.api.store import RedisStore, _KEY_TENANT
from fiscal_agent.models import Tenant


class TenantContextMiddleware(BaseHTTPMiddleware):
	"""Read ``api_key.tenant_id``, fetch ``Tenant`` from Redis, inject state."""

	async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
		request.state.tenant = None  # default

		# ClerkJWTExtractor already sets tenant_id (and tenant) directly
		if getattr(request.state, 'auth_method', None) == 'clerk_jwt':
			return await call_next(request)

		# For API key auth, resolve tenant from api_key.tenant_id
		api_key = getattr(request.state, 'api_key', None)
		if api_key is not None and api_key.tenant_id is not None:
			redis = request.app.state.redis  # type: ignore[attr-defined]
			tenant_data = await redis.hgetall(_KEY_TENANT.format(api_key.tenant_id))
			if tenant_data:
				tenant = RedisStore._deserialize(Tenant, tenant_data)
				request.state.tenant = tenant
				request.state.tenant_id = api_key.tenant_id
				request.state.scopes = api_key.scopes or []

		return await call_next(request)
