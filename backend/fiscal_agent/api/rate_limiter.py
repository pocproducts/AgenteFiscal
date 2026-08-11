"""Redis-backed sliding window rate limiter using Sorted Sets.

Replaces the in-memory fixed-window implementation. Uses Redis Sorted Sets
with Unix timestamps as scores to implement accurate sliding windows.

Two windows are tracked per API key:
- Minute window (60 seconds)
- Day window (86,400 seconds)
"""

from __future__ import annotations

import time
import uuid
from typing import Optional

from redis.asyncio import Redis

from fiscal_agent.models import Plan

#: Default limits for plans without explicit config
_DEFAULT_RPM = 10
_DEFAULT_RPD = 100

#: Window sizes in seconds
_WINDOW_MINUTE = 60
_WINDOW_DAY = 86400

#: Redis key prefix for rate limit windows
_KEY_RATELIMIT = 'ratelimit:{}:{}'


async def _check_window(redis: Redis, key: str, window_seconds: int, limit: int) -> dict:
	"""Check and record a request in a sliding window.

	Trims expired entries, counts current entries, adds the current
	request, and sets a TTL for auto-cleanup.

	Returns:
		``{allowed: bool, remaining: int, limit: int}``
	"""
	now = time.time()
	cutoff = now - window_seconds

	# Remove entries outside the window
	await redis.zremrangebyscore(key, '-inf', cutoff)

	# Count current entries
	count = await redis.zcard(key)

	# Add current request
	member = f'{now}:{uuid.uuid4().hex[:8]}'
	await redis.zadd(key, {member: now})

	# Set TTL for auto-cleanup (2x window)
	await redis.expire(key, window_seconds * 2)

	allowed = count < limit
	return {
		'allowed': allowed,
		'remaining': max(0, limit - count - 1),
		'limit': limit,
	}


async def _get_retry_after(redis: Redis, key: str, window_seconds: int) -> int:
	"""Calculate seconds until the earliest entry falls out of the window."""
	now = time.time()
	earliest = await redis.zrange(key, 0, 0, withscores=True)
	if earliest:
		_, score = earliest[0]
		retry_after = int((score + window_seconds) - now)
		return max(1, retry_after)
	return 1


async def check_rate_limit(redis: Redis, api_key_id: str, plan: Optional[Plan] = None) -> dict:
	"""Check if a request is within rate limits.

	Args:
		redis: Async Redis client from ``app.state.redis``.
		api_key_id: The API key ID to check limits for.
		plan: Optional plan with custom rate limits. If None, defaults are used.

	Returns:
		Dict with::

	                {
	                    'allowed': bool,
	                    'limit': int,  # RPM from plan
	                    'remaining': int,
	                    'retry_after': int,  # seconds (0 if allowed)
	                }
	"""
	rpm = plan.rate_limit_rpm if plan else _DEFAULT_RPM
	rpd = plan.rate_limit_rpd if plan else _DEFAULT_RPD

	minute_key = _KEY_RATELIMIT.format(api_key_id, 'minute')
	day_key = _KEY_RATELIMIT.format(api_key_id, 'day')

	minute_result = await _check_window(redis, minute_key, _WINDOW_MINUTE, rpm)
	day_result = await _check_window(redis, day_key, _WINDOW_DAY, rpd)

	allowed = minute_result['allowed'] and day_result['allowed']
	retry_after = 0

	if not allowed:
		if not minute_result['allowed']:
			retry_after = await _get_retry_after(redis, minute_key, _WINDOW_MINUTE)
		else:
			retry_after = await _get_retry_after(redis, day_key, _WINDOW_DAY)

	return {
		'allowed': allowed,
		'limit': rpm,
		'remaining': minute_result['remaining'] if allowed else 0,
		'retry_after': max(1, retry_after),
	}
