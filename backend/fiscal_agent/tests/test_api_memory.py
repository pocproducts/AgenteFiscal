"""Tests for memory REST endpoints — GET /v1/memory/{cuit}, POST /v1/memory/observe.

Uses FastAPI TestClient with mocked Engram.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fiscal_agent.memory.client import FiscalMemoryClient


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_memory() -> MagicMock:
	"""Return a mocked FiscalMemoryClient."""
	mock = MagicMock(spec=FiscalMemoryClient)
	mock.get_pipeline_history.return_value = [
		{'id': 1, 'type': 'padron', 'title': 'Padrón A5'},
		{'id': 2, 'type': 'deuda', 'title': 'Extracción deuda'},
	]
	mock.get_extraction_history.return_value = [
		{'id': 1, 'type': 'padron', 'title': 'Padrón A5'},
	]
	mock.save_observation.return_value = None
	return mock


@pytest.fixture
def app(mock_memory: MagicMock) -> FastAPI:
	"""Build a FastAPI app with the memory router."""
	app = FastAPI()
	app.state.redis = MagicMock()

	from fiscal_agent.api.routes.memory import router

	app.include_router(router)

	# Override get_memory
	from fiscal_agent.api.deps import get_memory

	app.dependency_overrides[get_memory] = lambda: mock_memory

	return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
	"""Return a TestClient without auth."""
	return TestClient(app)


# ── Mock get_memory BEFORE the app constructs (module-level patch) ──────────


@pytest.fixture(autouse=True)
def _patch_get_memory(mock_memory: MagicMock):
	"""Patch get_memory at the route module level so imports resolve to mock."""
	with patch('fiscal_agent.api.routes.memory.get_memory', return_value=mock_memory):
		yield


# ── Happy path GET ───────────────────────────────────────────────────────────


class TestGetMemoryHistory:
	"""Task 4.4: GET /v1/memory/{cuit} endpoints."""

	def test_get_memory_history(self, client: TestClient) -> None:
		"""Happy path: returns observations list."""
		resp = client.get('/v1/memory/20324837796')

		assert resp.status_code == 200
		data = resp.json()
		assert data['status'] == 'success'
		assert len(data['result']) == 2
		assert data['result'][0]['type'] == 'padron'

	def test_get_memory_by_type(self, client: TestClient) -> None:
		"""Filtering by type returns only matching observations."""
		resp = client.get('/v1/memory/20324837796/padron')

		assert resp.status_code == 200
		data = resp.json()
		assert data['status'] == 'success'
		assert len(data['result']) == 1
		assert data['result'][0]['type'] == 'padron'

	def test_get_memory_history_empty(self, client: TestClient, mock_memory: MagicMock) -> None:
		"""CUIT sin observaciones devuelve lista vacía."""
		mock_memory.get_pipeline_history.return_value = []

		resp = client.get('/v1/memory/20324837796')

		assert resp.status_code == 200
		data = resp.json()
		assert data['status'] == 'success'
		assert data['result'] == []

	def test_get_memory_by_type_empty(self, client: TestClient, mock_memory: MagicMock) -> None:
		"""Filtrar por tipo sin resultados devuelve lista vacía."""
		mock_memory.get_extraction_history.return_value = []

		resp = client.get('/v1/memory/20324837796/deuda')

		assert resp.status_code == 200
		data = resp.json()
		assert data['status'] == 'success'
		assert data['result'] == []

	def test_get_memory_history_invalid_cuit(self, client: TestClient) -> None:
		"""CUIT inválido devuelve INVALID_CUIT."""
		resp = client.get('/v1/memory/12345')

		assert resp.status_code == 200  # UnifiedResponse siempre 200
		data = resp.json()
		assert data['status'] == 'error'
		assert data['error']['code'] == 'INVALID_CUIT'


# ── Happy path POST ──────────────────────────────────────────────────────────


class TestPostObserve:
	"""Task 4.4: POST /v1/memory/observe endpoint."""

	def test_observe_valid(self, client: TestClient) -> None:
		"""Happy path: returns 201 with success."""
		resp = client.post(
			'/v1/memory/observe',
			json={
				'cuit': '20324837796',
				'title': 'Observación test',
				'type': 'test',
				'content': '**Status**: ok',
			},
		)

		assert resp.status_code == 201
		data = resp.json()
		assert data['status'] == 'success'
		assert data['result']['cuit'] == '20324837796'

	def test_observe_engram_unavailable(self, client: TestClient, mock_memory: MagicMock) -> None:
		"""Engram no disponible devuelve MEMORY_UNAVAILABLE."""
		mock_memory.is_available.return_value = False

		resp = client.post(
			'/v1/memory/observe',
			json={
				'cuit': '20324837796',
				'title': 'Test',
				'type': 'test',
				'content': 'sin engram',
			},
		)

		assert resp.status_code == 200
		data = resp.json()
		assert data['status'] == 'error'
		assert data['error']['code'] == 'MEMORY_UNAVAILABLE'


# ── Validation errors ────────────────────────────────────────────────────────


class TestValidationErrors:
	"""Task 4.4: Validation errors return proper error responses."""

	def test_invalid_cuit_length(self, client: TestClient) -> None:
		"""CUIT must be 11 chars — 422 returned."""
		resp = client.post(
			'/v1/memory/observe',
			json={
				'cuit': '12345',
				'title': 'Test',
				'content': 'test',
			},
		)

		assert resp.status_code == 422

	def test_content_too_large(self, client: TestClient) -> None:
		"""Content > 10 KB returns 422."""
		resp = client.post(
			'/v1/memory/observe',
			json={
				'cuit': '20324837796',
				'title': 'Test',
				'content': 'x' * 10_241,
			},
		)

		assert resp.status_code == 422


# ── Auth fallback scope ─────────────────────────────────────────────────────


class TestWithoutAuth:
	"""Without auth, endpoints still work (auth was removed)."""

	def test_get_memory_history_works_without_auth(self) -> None:
		"""Without auth headers, returns 200 (auth removed)."""
		app = FastAPI()
		from fiscal_agent.api.routes.memory import router

		app.include_router(router)
		no_auth_client = TestClient(app)

		resp = no_auth_client.get('/v1/memory/20324837796')
		assert resp.status_code == 200

	def test_post_observe_works_without_auth(self) -> None:
		"""Without auth headers, returns 201 (auth removed)."""
		app = FastAPI()
		from fiscal_agent.api.routes.memory import router

		app.include_router(router)
		no_auth_client = TestClient(app)

		resp = no_auth_client.post(
			'/v1/memory/observe',
			json={'cuit': '20324837796', 'title': 'Test', 'content': 'test'},
		)
		assert resp.status_code == 201
