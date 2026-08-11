"""Tests for MCP memory tools — get_memory_history, save_memory_observation.

Mocks lifespan_context to avoid real Engram dependency.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from fiscal_agent.mcp.tools.memory import get_memory_history, save_memory_observation
from fiscal_agent.memory.client import FiscalMemoryClient
from fiscal_agent.models import UnifiedResponse


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_memory() -> MagicMock:
	"""Return a mocked FiscalMemoryClient."""
	mock = MagicMock(spec=FiscalMemoryClient)
	mock.get_pipeline_history.return_value = [
		{'id': 1, 'type': 'padron', 'title': 'Padrón A5'},
	]
	mock.get_extraction_history.return_value = [
		{'id': 1, 'type': 'padron', 'title': 'Padrón A5'},
	]
	mock.save_observation.return_value = None
	return mock


@pytest.fixture
def mock_ctx(mock_memory: MagicMock) -> MagicMock:
	"""Return a mock Context with lifespan_context containing memory."""
	ctx = MagicMock()
	type(ctx.request_context.lifespan_context).get = PropertyMock(
		return_value=lambda key, default=None: mock_memory if key == 'memory' else default
	)
	# More direct: use a dict as the lifespan context
	ctx.request_context.lifespan_context = {'memory': mock_memory}
	return ctx


@pytest.fixture
def ctx_no_memory() -> MagicMock:
	"""Return a mock Context with NO memory in lifespan_context."""
	ctx = MagicMock()
	ctx.request_context.lifespan_context = {}
	return ctx


# ── get_memory_history ───────────────────────────────────────────────────────


class TestGetMemoryHistory:
	"""Task 4.5: get_memory_history MCP tool."""

	async def test_happy_path_no_type(self, mock_ctx: MagicMock, mock_memory: MagicMock) -> None:
		"""Returns UnifiedResponse with observations (no type filter)."""
		result = await get_memory_history(cuit='20324837796', ctx=mock_ctx)

		resp = UnifiedResponse.model_validate_json(result)
		assert resp.status == 'success'
		assert len(resp.result) == 1
		assert resp.result[0]['type'] == 'padron'
		mock_memory.get_pipeline_history.assert_called_once_with('20324837796', 10)

	async def test_happy_path_with_type(self, mock_ctx: MagicMock, mock_memory: MagicMock) -> None:
		"""Returns filtered observations when obs_type is provided."""
		result = await get_memory_history(cuit='20324837796', obs_type='padron', ctx=mock_ctx)

		resp = UnifiedResponse.model_validate_json(result)
		assert resp.status == 'success'
		mock_memory.get_extraction_history.assert_called_once_with('20324837796', 'padron', 10)

	async def test_custom_limit(self, mock_ctx: MagicMock, mock_memory: MagicMock) -> None:
		"""Respects the limit parameter."""
		result = await get_memory_history(cuit='20324837796', limit=5, ctx=mock_ctx)

		resp = UnifiedResponse.model_validate_json(result)
		assert resp.status == 'success'
		mock_memory.get_pipeline_history.assert_called_once_with('20324837796', 5)

	async def test_engram_unavailable(self, ctx_no_memory: MagicMock) -> None:
		"""When memory is None in context, returns error."""
		result = await get_memory_history(cuit='20324837796', ctx=ctx_no_memory)

		resp = UnifiedResponse.model_validate_json(result)
		assert resp.status == 'error'
		assert resp.error.code == 'MEMORY_UNAVAILABLE'


# ── save_memory_observation ──────────────────────────────────────────────────


class TestSaveMemoryObservation:
	"""Task 4.5: save_memory_observation MCP tool."""

	async def test_happy_path(self, mock_ctx: MagicMock, mock_memory: MagicMock) -> None:
		"""Returns success on valid observation."""
		result = await save_memory_observation(
			cuit='20324837796',
			title='Test observation',
			type='test',
			content='**Status**: ok',
			ctx=mock_ctx,
		)

		resp = UnifiedResponse.model_validate_json(result)
		assert resp.status == 'success'
		assert resp.result['cuit'] == '20324837796'
		assert resp.result['type'] == 'test'

	async def test_default_type(self, mock_ctx: MagicMock, mock_memory: MagicMock) -> None:
		"""Type defaults to 'generic'."""
		result = await save_memory_observation(
			cuit='20324837796',
			title='Test',
			content='test',
			ctx=mock_ctx,
		)

		resp = UnifiedResponse.model_validate_json(result)
		assert resp.status == 'success'
		assert resp.result['type'] == 'generic'

	async def test_engram_unavailable(self, ctx_no_memory: MagicMock) -> None:
		"""When memory is None in context, returns error."""
		result = await save_memory_observation(
			cuit='20324837796',
			title='Test',
			content='test',
			ctx=ctx_no_memory,
		)

		resp = UnifiedResponse.model_validate_json(result)
		assert resp.status == 'error'
		assert resp.error.code == 'MEMORY_UNAVAILABLE'

	async def test_content_too_large(self, mock_ctx: MagicMock) -> None:
		"""Content exceeding 10 KB returns error."""
		result = await save_memory_observation(
			cuit='20324837796',
			title='Test',
			content='x' * 10_241,
			ctx=mock_ctx,
		)

		resp = UnifiedResponse.model_validate_json(result)
		assert resp.status == 'error'
		assert resp.error.code == 'CONTENT_TOO_LARGE'
