"""In-memory request metrics middleware for FastAPI.

Tracks per-endpoint request counts, status code distributions,
and latency histograms. Metrics are in-memory and reset on
server restart — acceptable per spec (Req 4).
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


@dataclass
class EndpointMetrics:
	"""Aggregated metrics for a single endpoint (method + route template).

	Attributes:
		count: Total request count.
		status_2xx: Count of 2xx responses.
		status_4xx: Count of 4xx responses.
		status_5xx: Count of 5xx responses.
		latencies: Raw latency samples in seconds (for percentile calculation).
	"""

	count: int = 0
	status_2xx: int = 0
	status_4xx: int = 0
	status_5xx: int = 0
	latencies: list[float] = field(default_factory=list)

	def record(self, status_code: int, latency: float) -> None:
		"""Record one request outcome."""
		self.count += 1
		if 200 <= status_code < 300:
			self.status_2xx += 1
		elif 400 <= status_code < 500:
			self.status_4xx += 1
		elif 500 <= status_code < 600:
			self.status_5xx += 1
		self.latencies.append(latency)

	def p50(self) -> float:
		"""Median latency in seconds."""
		return _percentile(self.latencies, 50)

	def p95(self) -> float:
		"""95th percentile latency in seconds."""
		return _percentile(self.latencies, 95)

	def p99(self) -> float:
		"""99th percentile latency in seconds."""
		return _percentile(self.latencies, 99)


def _percentile(sorted_samples: list[float], p: int) -> float:
	"""Calculate the *p*-th percentile of a sorted sample list."""
	if not sorted_samples:
		return 0.0
	sorted_copy = sorted(sorted_samples)
	k = math.ceil(len(sorted_copy) * p / 100) - 1
	return sorted_copy[max(0, min(k, len(sorted_copy) - 1))]


class RequestMetricsStore:
	"""In-memory metrics store, thread-safe via Lock.

	Resets on server restart (acceptable per spec Req 4).
	Allows recording requests by (method, route_template) and
	taking atomic snapshots.
	"""

	def __init__(self) -> None:
		self._lock = Lock()
		self._data: dict[str, EndpointMetrics] = defaultdict(EndpointMetrics)

	@staticmethod
	def _key(method: str, path: str) -> str:
		"""Build a composite key from HTTP method and route path."""
		return f'{method.upper()} {path}'

	def record(self, method: str, path: str, status_code: int, latency: float) -> None:
		"""Record one request.

		Thread-safe: acquires the internal lock before mutating.

		Args:
			method: HTTP method (GET, POST, etc.).
			path: Route template path (e.g. ``/v1/report/{cuit}``).
			status_code: HTTP response status code.
			latency: Request duration in seconds.
		"""
		key = self._key(method, path)
		with self._lock:
			self._data[key].record(status_code, latency)

	def get_snapshot(self) -> dict[str, EndpointMetrics]:
		"""Return a copy of all current metrics.

		Thread-safe: acquires the internal lock for the read.
		"""
		with self._lock:
			return dict(self._data)

	def reset(self) -> None:
		"""Clear all collected metrics."""
		with self._lock:
			self._data.clear()


class RequestMetricsMiddleware(BaseHTTPMiddleware):
	"""FastAPI middleware that records HTTP metrics per endpoint.

	Captures request count, status code distribution, and latency
	samples for each (method, route template) pair.

	Usage::

	        app.add_middleware(RequestMetricsMiddleware)
	"""

	def __init__(self, app: ASGIApp, store: RequestMetricsStore | None = None) -> None:
		super().__init__(app)
		self.store = store or RequestMetricsStore()

	async def dispatch(self, request: Request, call_next: Any) -> Response:
		"""Intercept request, record timing and status."""
		start = time.monotonic()

		response = await call_next(request)

		latency = time.monotonic() - start
		# Use route template for grouping (e.g. /v1/report/{cuit})
		route = request.scope.get('route')
		path_template = route.path if route else request.url.path
		self.store.record(request.method, path_template, response.status_code, latency)

		return response
