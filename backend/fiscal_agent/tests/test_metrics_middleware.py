"""Tests for in-memory request metrics middleware.

Unit tests:
- ``RequestMetricsStore.record()`` increments counters correctly
- ``RequestMetricsStore.get_snapshot()`` returns a consistent view
- ``RequestMetricsStore.reset()`` clears all data
- ``EndpointMetrics.p50/p95/p99()`` calculate percentiles accurately

Integration tests:
- Each request to TestClient increments store counters
- Status code ranges (2xx, 4xx, 5xx) are tracked separately
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fiscal_agent.api.middleware.metrics import EndpointMetrics, RequestMetricsStore

# ── Percentile helpers for verification ──────────────────────────────────────────


def _sorted_latencies(*values: float) -> list[float]:
	return sorted(values)


# ── Unit: EndpointMetrics ───────────────────────────────────────────────────────


class TestEndpointMetrics:
	"""EndpointMetrics dataclass — record + percentiles."""

	def test_record_increments_count(self) -> None:
		m = EndpointMetrics()
		m.record(200, 0.1)
		m.record(201, 0.2)
		assert m.count == 2

	def test_record_status_2xx(self) -> None:
		m = EndpointMetrics()
		m.record(200, 0.1)
		m.record(301, 0.2)
		assert m.status_2xx == 1

	def test_record_status_4xx(self) -> None:
		m = EndpointMetrics()
		m.record(404, 0.1)
		m.record(500, 0.2)
		assert m.status_4xx == 1

	def test_record_status_5xx(self) -> None:
		m = EndpointMetrics()
		m.record(500, 0.1)
		m.record(502, 0.2)
		assert m.status_5xx == 2

	def test_p50_no_samples(self) -> None:
		m = EndpointMetrics()
		assert m.p50() == 0.0

	def test_p50_single_sample(self) -> None:
		m = EndpointMetrics()
		m.record(200, 0.5)
		assert m.p50() == 0.5

	def test_p50_median(self) -> None:
		m = EndpointMetrics()
		for lat in [0.1, 0.2, 0.3, 0.4, 0.5]:
			m.record(200, lat)
		assert m.p50() == 0.3

	def test_p95(self) -> None:
		m = EndpointMetrics()
		for i in range(1, 101):
			m.record(200, float(i) / 100)
		# 95th percentile of 100 sorted samples at index 94
		assert m.p95() == pytest.approx(0.95, abs=0.01)

	def test_p99(self) -> None:
		m = EndpointMetrics()
		for i in range(1, 101):
			m.record(200, float(i) / 100)
		# 99th percentile of 100 sorted samples at index 98
		assert m.p99() == pytest.approx(0.99, abs=0.01)


# ── Unit: RequestMetricsStore ───────────────────────────────────────────────────


class TestRequestMetricsStore:
	"""RequestMetricsStore — record, snapshot, reset."""

	def test_record_creates_entry(self) -> None:
		store = RequestMetricsStore()
		store.record('GET', '/v1/health', 200, 0.05)
		snapshot = store.get_snapshot()
		assert 'GET /v1/health' in snapshot
		assert snapshot['GET /v1/health'].count == 1

	def test_record_multiple_paths(self) -> None:
		store = RequestMetricsStore()
		store.record('GET', '/v1/health', 200, 0.05)
		store.record('POST', '/v1/memory/observe', 201, 0.1)
		snapshot = store.get_snapshot()
		assert len(snapshot) == 2

	def test_record_same_path_aggregates(self) -> None:
		store = RequestMetricsStore()
		store.record('GET', '/v1/health', 200, 0.05)
		store.record('GET', '/v1/health', 200, 0.07)
		snapshot = store.get_snapshot()
		assert snapshot['GET /v1/health'].count == 2
		assert len(snapshot['GET /v1/health'].latencies) == 2

	def test_reset_clears_all(self) -> None:
		store = RequestMetricsStore()
		store.record('GET', '/v1/health', 200, 0.05)
		store.reset()
		assert store.get_snapshot() == {}

	def test_snapshot_is_copy(self) -> None:
		store = RequestMetricsStore()
		store.record('GET', '/v1/health', 200, 0.05)
		snapshot = store.get_snapshot()
		store.record('GET', '/v1/health', 200, 0.07)
		# Snapshot should have count 1 (taken before second record)
		assert snapshot['GET /v1/health'].count == 1

	def test_record_4xx_tracked(self) -> None:
		store = RequestMetricsStore()
		store.record('GET', '/v1/health', 404, 0.05)
		snapshot = store.get_snapshot()
		assert snapshot['GET /v1/health'].status_4xx == 1

	def test_record_5xx_tracked(self) -> None:
		store = RequestMetricsStore()
		store.record('GET', '/v1/health', 500, 0.05)
		snapshot = store.get_snapshot()
		assert snapshot['GET /v1/health'].status_5xx == 1

	def test_record_2xx_tracked(self) -> None:
		store = RequestMetricsStore()
		store.record('GET', '/v1/health', 200, 0.05)
		snapshot = store.get_snapshot()
		assert snapshot['GET /v1/health'].status_2xx == 1


# ── Integration: middleware with TestClient ──────────────────────────────────────


@pytest.fixture
def metrics_store() -> RequestMetricsStore:
	return RequestMetricsStore()


@pytest.fixture
def app(metrics_store: RequestMetricsStore) -> FastAPI:
	from fiscal_agent.api.middleware.metrics import RequestMetricsMiddleware

	app = FastAPI()

	@app.get('/v1/test-ok')
	async def test_ok():
		return {'status': 'ok'}

	@app.get('/v1/test-error')
	async def test_error():
		from fastapi import HTTPException

		raise HTTPException(status_code=404, detail='Not found')

	app.add_middleware(RequestMetricsMiddleware, store=metrics_store)
	return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
	return TestClient(app)


class TestMiddlewareIntegration:
	"""Middleware records metrics for each request."""

	def test_ok_request_increments_count(self, client: TestClient, metrics_store: RequestMetricsStore) -> None:
		client.get('/v1/test-ok')
		snapshot = metrics_store.get_snapshot()
		key = 'GET /v1/test-ok'
		assert key in snapshot
		assert snapshot[key].count == 1
		assert snapshot[key].status_2xx == 1

	def test_error_request_4xx(self, client: TestClient, metrics_store: RequestMetricsStore) -> None:
		client.get('/v1/test-error')
		snapshot = metrics_store.get_snapshot()
		key = 'GET /v1/test-error'
		assert key in snapshot
		assert snapshot[key].status_4xx == 1

	def test_multiple_requests_aggregate(self, client: TestClient, metrics_store: RequestMetricsStore) -> None:
		for _ in range(5):
			client.get('/v1/test-ok')
		snapshot = metrics_store.get_snapshot()
		assert snapshot['GET /v1/test-ok'].count == 5

	def test_latency_recorded(self, client: TestClient, metrics_store: RequestMetricsStore) -> None:
		client.get('/v1/test-ok')
		snapshot = metrics_store.get_snapshot()
		latencies = snapshot['GET /v1/test-ok'].latencies
		assert len(latencies) == 1
		assert latencies[0] > 0  # Latency should be positive
