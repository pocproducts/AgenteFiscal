"""Tests for extended health endpoint — GET /v1/health.

Verifies that the health check correctly reflects Redis, Engram, TA,
and Composio status using mocked dependencies.

Scenarios from spec:
- All healthy → global status 'healthy'
- Redis down → global status 'degraded'
- TA expirado → global status 'degraded'
- Composio invalid → global status 'degraded'
- Multiple failures → global status 'down'
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fiscal_agent.models import ServiceStatus


# ── Helpers ──────────────────────────────────────────────────────────────────────


def _make_healthy_service(name: str) -> ServiceStatus:
	return ServiceStatus(name=name, status='healthy', last_check='2026-01-01T00:00:00Z')


def _make_unhealthy_service(name: str, error: str = 'mock error') -> ServiceStatus:
	return ServiceStatus(name=name, status='unhealthy', last_check='2026-01-01T00:00:00Z', error=error)


# ── Fixtures ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def app() -> FastAPI:
	"""Build a FastAPI app with only the health router."""
	app = FastAPI()
	app.state.redis = MagicMock()
	app.state.store = MagicMock()
	from fiscal_agent.api.routes.health import router

	app.include_router(router)
	return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
	"""Return a TestClient without auth (health endpoint is unauthenticated)."""
	return TestClient(app)


# ── All healthy ─────────────────────────────────────────────────────────────────


class TestAllHealthy:
	"""All services respond correctly."""

	def test_all_healthy_status(self, client: TestClient) -> None:
		"""Spec: healthy when all four services respond."""
		resp = client.get('/v1/health')
		assert resp.status_code == 200
		data = resp.json()
		assert data['status'] == 'success'
		result = data['result']
		services = {s['name']: s for s in result['services']}
		assert services['redis']['status'] == 'healthy'


# ── Redis failure ───────────────────────────────────────────────────────────────


class TestRedisFailure:
	"""Redis unavailable → degraded."""

	@patch('fiscal_agent.api.routes.health._check_redis')
	def test_redis_down(
		self,
		mock_check_redis: MagicMock,
		client: TestClient,
	) -> None:
		"""Spec: Redis ping fails → degraded + redis unhealthy."""
		mock_check_redis.return_value = _make_unhealthy_service('redis', error='Connection refused')

		resp = client.get('/v1/health')
		assert resp.status_code == 200
		data = resp.json()
		assert data['result']['status'] == 'degraded'


# ── TA failure ──────────────────────────────────────────────────────────────────


class TestTaFailure:
	"""TA expirado → degraded."""

	@patch('fiscal_agent.api.routes.health._check_ta')
	def test_ta_expired(
		self,
		mock_check_ta: MagicMock,
		client: TestClient,
	) -> None:
		"""Spec: TA token expirado → degraded + ta unhealthy."""
		mock_check_ta.return_value = _make_unhealthy_service('ta', error='Token expirado')

		resp = client.get('/v1/health')
		assert resp.status_code == 200
		data = resp.json()
		assert data['result']['status'] == 'degraded'


# ── Composio failure ────────────────────────────────────────────────────────────


class TestComposioFailure:
	"""Composio API key missing → degraded."""

	@patch('fiscal_agent.api.routes.health._check_composio')
	def test_composio_missing(
		self,
		mock_check_composio: MagicMock,
		client: TestClient,
	) -> None:
		"""Spec: COMPOSIO_API_KEY no configurada → degraded + composio unhealthy."""
		mock_check_composio.return_value = _make_unhealthy_service(
			'composio',
			error='COMPOSIO_API_KEY no configurada',
		)

		resp = client.get('/v1/health')
		assert resp.status_code == 200
		data = resp.json()
		assert data['result']['status'] == 'degraded'


# ── Multiple failures → down ────────────────────────────────────────────────────


class TestMultipleFailures:
	"""Multiple failures → global down."""

	@patch('fiscal_agent.api.routes.health._check_redis')
	@patch('fiscal_agent.api.routes.health._check_engram')
	@patch('fiscal_agent.api.routes.health._check_ta')
	@patch('fiscal_agent.api.routes.health._check_composio')
	def test_three_unhealthy(
		self,
		mock_composio: MagicMock,
		mock_ta: MagicMock,
		mock_engram: MagicMock,
		mock_redis: MagicMock,
		client: TestClient,
	) -> None:
		"""Spec: 3/4 servicios caídos → down."""
		mock_redis.return_value = _make_healthy_service('redis')
		mock_engram.return_value = _make_unhealthy_service('engram')
		mock_ta.return_value = _make_unhealthy_service('ta')
		mock_composio.return_value = _make_unhealthy_service('composio')

		resp = client.get('/v1/health')
		assert resp.status_code == 200
		data = resp.json()
		assert data['result']['status'] == 'down'
