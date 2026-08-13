"""Tests for system monitoring endpoints — /v1/system/*.

Uses FastAPI TestClient with mocked Engram search and Redis cache.

Scenarios:
- GET /v1/system/metrics: 24h/7d/30d, empty state
- GET /v1/system/services: all services listed
- GET /v1/system/activity: pagination
- GET /v1/system/errors: filter by severity, service
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agente_fiscal.domain.models import UnifiedResponse


@pytest.fixture
def app() -> FastAPI:
	"""Build app with monitor router and mocked store."""
	app = FastAPI()
	app.state.redis = MagicMock()

	from agente_fiscal.api.routes.monitor import router

	app.include_router(router)
	return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
	"""TestClient without auth."""
	return TestClient(app)


# ── GET /v1/system/metrics ─────────────────────────────────────────────────────


class TestSystemMetrics:
	"""GET /v1/system/metrics endpoint."""

	@patch('agente_fiscal.api.routes.monitor.get_memory')
	def test_metrics_24h(self, mock_get_memory: MagicMock, client: TestClient) -> None:
		"""Happy path: returns metrics with 24h period."""
		mock_memory = MagicMock()
		mock_memory._engram_get.return_value = []
		mock_get_memory.return_value = mock_memory

		resp = client.get('/v1/system/metrics?period=24h')
		assert resp.status_code == 200
		data = resp.json()
		assert data['status'] == 'success'
		assert 'total_runs' in data['result']

	@patch('agente_fiscal.api.routes.monitor.get_memory')
	def test_metrics_7d(self, mock_get_memory: MagicMock, client: TestClient) -> None:
		"""Happy path: 7d period."""
		mock_memory = MagicMock()
		mock_memory._engram_get.return_value = []
		mock_get_memory.return_value = mock_memory

		resp = client.get('/v1/system/metrics?period=7d')
		assert resp.status_code == 200
		data = resp.json()
		assert data['result']['total_runs'] == 0

	@patch('agente_fiscal.api.routes.monitor.get_memory')
	def test_metrics_empty(self, mock_get_memory: MagicMock, client: TestClient) -> None:
		"""Empty state: zero metrics returned."""
		mock_memory = MagicMock()
		mock_memory._engram_get.return_value = []
		mock_get_memory.return_value = mock_memory

		resp = client.get('/v1/system/metrics')
		assert resp.status_code == 200
		data = resp.json()
		assert data['result']['total_runs'] == 0
		assert data['result']['error_rate'] == 0.0

	def test_metrics_no_auth(self) -> None:
		"""Without auth, still returns 200 (auth removed)."""
		app = FastAPI()
		from agente_fiscal.api.routes.monitor import router

		app.include_router(router)
		resp = TestClient(app).get('/v1/system/metrics')
		assert resp.status_code == 200


# ── GET /v1/system/services ──────────────────────────────────────────────────


class TestSystemServices:
	"""GET /v1/system/services endpoint."""

	@patch('agente_fiscal.api.routes.monitor.get_memory')
	@patch('agente_fiscal.api.routes.monitor._check_redis')
	@patch('agente_fiscal.api.routes.monitor._check_engram')
	@patch('agente_fiscal.api.routes.monitor._check_ta')
	@patch('agente_fiscal.api.routes.monitor._check_composio')
	def test_services_list(
		self,
		mock_composio: MagicMock,
		mock_ta: MagicMock,
		mock_engram: MagicMock,
		mock_redis: MagicMock,
		mock_get_memory: MagicMock,
		client: TestClient,
		auth_header: dict,
	) -> None:
		"""Returns all four services."""
		from agente_fiscal.domain.models import ServiceStatus

		from datetime import datetime

		ts = datetime(2026, 1, 1)
		mock_redis.return_value = ServiceStatus(name='redis', status='healthy', last_check=ts)
		mock_engram.return_value = ServiceStatus(name='engram', status='healthy', last_check=ts)
		mock_ta.return_value = ServiceStatus(name='ta', status='healthy', last_check=ts)
		mock_composio.return_value = ServiceStatus(name='composio', status='healthy', last_check=ts)

		resp = client.get('/v1/system/services', headers=auth_header)
		assert resp.status_code == 200
		data = resp.json()
		assert data['status'] == 'success'
		names = {s['name'] for s in data['result']}
		assert names == {'redis', 'engram', 'ta', 'composio'}


# ── GET /v1/system/activity ─────────────────────────────────────────────────


class TestSystemActivity:
	"""GET /v1/system/activity endpoint."""

	@patch('agente_fiscal.api.routes.monitor.get_memory')
	def test_activity_pagination(
		self,
		mock_get_memory: MagicMock,
		client: TestClient,
	) -> None:
		"""Returns paginated activity events."""
		mock_memory = MagicMock()
		mock_memory._engram_get.return_value = [
			{'id': 1, 'type': 'pipeline_run', 'title': 'Run 1', 'content': '**Cuit**: 20324837796\n**Status**: success'},
			{'id': 2, 'type': 'error', 'title': 'Error 1', 'content': '**Cuit**: 20324837796\n**Error**: timeout'},
		]
		mock_get_memory.return_value = mock_memory

		resp = client.get('/v1/system/activity?limit=2&offset=0')
		assert resp.status_code == 200
		data = resp.json()
		assert data['status'] == 'success'
		assert len(data['result']) == 2

	@patch('agente_fiscal.api.routes.monitor.get_memory')
	def test_activity_empty(
		self,
		mock_get_memory: MagicMock,
		client: TestClient,
	) -> None:
		"""Empty activity returns empty list."""
		mock_memory = MagicMock()
		mock_memory._engram_get.return_value = []
		mock_get_memory.return_value = mock_memory

		resp = client.get('/v1/system/activity')
		assert resp.status_code == 200
		data = resp.json()
		assert data['result'] == []


# ── GET /v1/system/errors ───────────────────────────────────────────────────


class TestSystemErrors:
	"""GET /v1/system/errors endpoint."""

	@patch('agente_fiscal.api.routes.monitor.get_memory')
	def test_errors_filter_severity(
		self,
		mock_get_memory: MagicMock,
		client: TestClient,
	) -> None:
		"""Filter by severity."""
		mock_memory = MagicMock()
		mock_memory._engram_get.return_value = [
			{'id': 1, 'type': 'error', 'title': 'Error', 'content': '**Stage**: pipeline\n**Error**: timeout'},
		]
		mock_get_memory.return_value = mock_memory

		resp = client.get('/v1/system/errors?severity=error')
		assert resp.status_code == 200
		data = resp.json()
		assert data['status'] == 'success'

	@patch('agente_fiscal.api.routes.monitor.get_memory')
	def test_errors_filter_service(
		self,
		mock_get_memory: MagicMock,
		client: TestClient,
	) -> None:
		"""Filter by service name."""
		mock_memory = MagicMock()
		mock_memory._engram_get.return_value = []
		mock_get_memory.return_value = mock_memory

		resp = client.get('/v1/system/errors?service=pipeline&period=7d')
		assert resp.status_code == 200
		data = resp.json()
		assert data['status'] == 'success'
