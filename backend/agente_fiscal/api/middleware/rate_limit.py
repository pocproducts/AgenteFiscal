"""RateLimitMiddleware — Redis sliding window rate limiter.

Runs AFTER auth (needs ``request.state.api_key`` and ``request.state.plan``).
Returns 429 with standard headers when exceeded.
"""

from __future__ import annotations

import time
import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from agente_fiscal.api.rate_limiter import check_rate_limit
from agente_fiscal.domain.models import ApiError, UnifiedResponse

logger = logging.getLogger(__name__)

#: True once we've logged the Redis-down pass-through warning (per process),
#: so a degraded boot doesn't spam one warning per request.
_logged_no_redis = False


def _warn_redis_passthrough(message: str) -> None:
	"""Log the Redis-passthrough warning at most once per process."""
	global _logged_no_redis
	if not _logged_no_redis:
		_logged_no_redis = True
		logger.warning(message)


class RateLimitMiddleware(BaseHTTPMiddleware):
	"""Check rate limits per API key using Redis sliding windows."""

	async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
		# Bypass health endpoint
		if request.url.path == '/v1/health':
			return await call_next(request)

		api_key = getattr(request.state, 'api_key', None)
		plan = getattr(request.state, 'plan', None)

		# Unauthenticated requests (shouldn't reach here, but safety check)
		if api_key is None:
			return await call_next(request)

		redis = getattr(request.app.state, 'redis', None)
		if redis is None:
			# Redis-down passthrough: no rate limiting enforced, no headers.
			_warn_redis_passthrough('Redis no disponible — rate limiting desactivado (passthrough)')
			return await call_next(request)

		try:
			result = await check_rate_limit(redis, api_key.id, plan)
		except Exception:
			# Defensive: a broken Redis client (e.g. Redis died mid-run) must
			# degrade to pass-through, never a 500.
			_warn_redis_passthrough('Error de Redis en rate limiting — passthrough')
			return await call_next(request)

		if not result['allowed']:
			now = time.time()
			retry_after = result['retry_after']
			return JSONResponse(
				status_code=429,
				content=UnifiedResponse(
					status='error',
					error=ApiError(
						code='RATE_LIMIT_EXCEEDED',
						cause=f'Límite de tasa excedido. Esperá {retry_after} segundos.',
					),
				).model_dump(),
				headers={
					'Retry-After': str(retry_after),
					'X-RateLimit-Limit': str(result['limit']),
					'X-RateLimit-Remaining': '0',
					'X-RateLimit-Reset': str(int(now + retry_after)),
				},
			)

		# Allowed — pass through with rate limit headers
		response = await call_next(request)
		response.headers['X-RateLimit-Limit'] = str(result['limit'])
		response.headers['X-RateLimit-Remaining'] = str(result['remaining'])
		return response
