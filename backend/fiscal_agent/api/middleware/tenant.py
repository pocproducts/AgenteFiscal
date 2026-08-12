"""TenantContextMiddleware — retained for middleware-stack stability.

Cutover Phase 5: tenant context is resolved by the auth layer itself —
``AuthMiddleware`` sets ``request.state.tenant_id`` / ``scopes`` from the
Postgres ``ApiKey`` row for the API-key path, and ``ClerkJWTExtractor`` sets
``tenant``/``tenant_id``/``scopes``/``plan`` for the Clerk path. Redis no
longer holds tenant business data (it is rate-limit/cache + conversations
only), so this middleware is now an explicit no-op passthrough.

Non-blocking by design: it NEVER returns an error.
"""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


class TenantContextMiddleware(BaseHTTPMiddleware):
	"""No-op context enricher — keeps the middleware ordering stable."""

	async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
		request.state.tenant = getattr(request.state, 'tenant', None)
		return await call_next(request)