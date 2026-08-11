"""Tests for Chat UI Integration — append_messages, history, auto-persist, SSE, tenant.

Covers spec scenarios for both the store layer and chat endpoint changes.
"""

from __future__ import annotations

import json
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from fiscal_agent.api.store import RedisStore
from fiscal_agent.chat.intent_router import Intent


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_redis() -> AsyncMock:
	"""Return a mock async Redis client with common presets."""
	return AsyncMock()


@pytest.fixture
def store(mock_redis: AsyncMock) -> RedisStore:
	"""Return a RedisStore backed by the mock Redis."""
	return RedisStore(mock_redis)


@pytest.fixture
def app_with_store() -> FastAPI:
	"""Build a chat-only app with mock store and tenant middleware."""
	app = FastAPI()
	from fiscal_agent.api.routes.chat import router

	app.include_router(router)
	app.state.store = MagicMock(spec=RedisStore)
	app.state.store.append_messages = AsyncMock(return_value='conv_01')

	@app.middleware('http')
	async def _inject_tenant(request: Request, call_next):  # type: ignore[misc]
		request.state.tenant_id = 'test-tenant-id'
		return await call_next(request)

	return app


@pytest.fixture
def client(app_with_store: FastAPI) -> TestClient:
	"""Return a TestClient for the chat app with mock store + tenant."""
	return TestClient(app_with_store)


# ponytail: no `pytest.mark.asyncio` needed for TestClient tests


# ═══════════════════════════════════════════════════════════════════
# Phase 1 — append_messages unit tests
# ═══════════════════════════════════════════════════════════════════


class TestAppendMessages:
	"""Unit tests for RedisStore.append_messages()."""

	@pytest.mark.asyncio
	async def test_append_to_existing(self, mock_redis: AsyncMock, store: RedisStore) -> None:
		"""Append 2 messages to existing conv with 2 → verify 4 total, updated_at changes."""
		existing = [
			{'role': 'user', 'content': 'hola'},
			{'role': 'assistant', 'content': 'hola!'},
		]
		mock_redis.hgetall.return_value = {
			'id': json.dumps('conv_01'),
			'messages': json.dumps(existing),
			'title': json.dumps('hola'),
			'created_at': json.dumps('2025-01-01T00:00:00'),
			'updated_at': json.dumps('2025-01-01T00:00:00'),
		}

		new_msgs = [
			{'role': 'user', 'content': 'consulta CUIT 20324837796'},
			{'role': 'assistant', 'content': 'Juan Perez, responsable inscripto'},
		]
		result = await store.append_messages('t01', 'conv_01', new_msgs)

		assert result == 'conv_01'
		# hset called with serialized mapping
		hset_call = mock_redis.hset.call_args
		assert hset_call is not None
		mapping = hset_call.kwargs['mapping']
		all_msgs = json.loads(mapping['messages'])
		assert len(all_msgs) == 4
		assert all_msgs[-2:] == new_msgs
		# updated_at set
		assert isinstance(json.loads(mapping['updated_at']), str)
		# expire called
		mock_redis.expire.assert_awaited_once()

	@pytest.mark.asyncio
	async def test_append_creates_new(self, mock_redis: AsyncMock, store: RedisStore) -> None:
		"""Append to nonexistent conversation → key created with all fields."""
		mock_redis.hgetall.return_value = {}  # no existing data

		msgs = [
			{'role': 'user', 'content': 'consulta datos del contribuyente 20-32483779-6'},
			{'role': 'assistant', 'content': 'Datos del contribuyente...'},
		]
		result = await store.append_messages('t01', 'conv_new', msgs)

		assert result == 'conv_new'
		# hset called with full create payload
		hset_call = mock_redis.hset.call_args
		mapping = hset_call.kwargs['mapping']
		assert json.loads(mapping['id']) == 'conv_new'
		assert json.loads(mapping['messages']) == msgs
		assert json.loads(mapping['created_at'])
		assert json.loads(mapping['updated_at'])
		# SADD called for the all-conversations set
		mock_redis.sadd.assert_awaited_once()
		# expire called
		mock_redis.expire.assert_awaited_once()

	@pytest.mark.asyncio
	async def test_append_title_generation(self, mock_redis: AsyncMock, store: RedisStore) -> None:
		"""Title derived from first user message content."""
		mock_redis.hgetall.return_value = {}

		msgs = [
			{'role': 'user', 'content': 'consulta datos del contribuyente 20-32483779-6'},
			{'role': 'assistant', 'content': 'ok'},
		]
		await store.append_messages('t01', 'conv_t', msgs)

		hset_call = mock_redis.hset.call_args
		mapping = hset_call.kwargs['mapping']
		assert json.loads(mapping['title']) == 'consulta datos del contribuyente 20-32483779-6'

	@pytest.mark.asyncio
	async def test_append_title_truncated(self, mock_redis: AsyncMock, store: RedisStore) -> None:
		"""Title truncation when first user message exceeds 50 chars."""
		mock_redis.hgetall.return_value = {}

		long_msg = 'a' * 60
		msgs = [
			{'role': 'user', 'content': long_msg},
			{'role': 'assistant', 'content': 'ok'},
		]
		await store.append_messages('t01', 'conv_t', msgs)

		hset_call = mock_redis.hset.call_args
		mapping = hset_call.kwargs['mapping']
		title = json.loads(mapping['title'])
		assert len(title) == 53  # 50 + '...'
		assert title.endswith('...')

	@pytest.mark.asyncio
	async def test_append_refreshes_ttl(self, mock_redis: AsyncMock, store: RedisStore) -> None:
		"""TTL refreshed via expire() after append."""
		mock_redis.hgetall.return_value = {
			'id': json.dumps('conv_01'),
			'messages': json.dumps([{'role': 'user', 'content': 'hi'}]),
			'title': json.dumps('hi'),
			'created_at': json.dumps('2025-01-01T00:00:00'),
			'updated_at': json.dumps('2025-01-01T00:00:00'),
		}

		await store.append_messages('t01', 'conv_01', [{'role': 'user', 'content': 'more'}])

		mock_redis.expire.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════
# Phase 2 — history prepend tests
# ═══════════════════════════════════════════════════════════════════


class TestHistoryPrepend:
	"""History affects intent routing via detect()."""

	def test_history_prepend_adds_context(self) -> None:
		"""History text is prepended so detect() sees prior CUIT."""
		from fiscal_agent.chat.intent_router import detect

		# Without history → no CUIT in message alone
		_intent_no_history, cuit_no, _ = detect('y el calendario?')
		assert cuit_no is None

		# With history that includes a CUIT → detect() finds it
		context = 'consulta CUIT 20324837796\ny el calendario?'
		_intent_with, cuit_with, _ = detect(context)
		assert cuit_with is not None

	def test_history_empty_or_null_works(self, client: TestClient) -> None:
		"""Endpoint works when history is null."""
		resp = client.post(
			'/v1/chat/message',
			json={'message': 'hola', 'history': None},
		)
		assert resp.status_code == 200

		resp2 = client.post(
			'/v1/chat/message',
			json={'message': 'hola'},
		)
		assert resp2.status_code == 200

	def test_history_empty_list_works(self, client: TestClient) -> None:
		"""Endpoint works when history is empty list."""
		resp = client.post(
			'/v1/chat/message',
			json={'message': 'hola', 'history': []},
		)
		assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════
# Phase 2 — auto-persist tests
# ═══════════════════════════════════════════════════════════════════


class TestAutoPersist:
	"""Messages auto-persisted after each turn."""

	def test_sync_auto_persists(self, client: TestClient, app_with_store: FastAPI) -> None:
		"""Sync endpoint calls append_messages."""
		with patch('fiscal_agent.api.routes.chat._handle_taxpayer', return_value={'nombre': 'Test'}):
			resp = client.post(
				'/v1/chat/message',
				json={'message': 'consulta CUIT 20324837796'},
			)

		assert resp.status_code == 200
		store: MagicMock = app_with_store.state.store
		store.append_messages.assert_awaited()

	def test_sync_auto_persists_correct_args(self, client: TestClient, app_with_store: FastAPI) -> None:
		"""append_messages called with correct tenant_id, conversation_id, messages."""
		with patch('fiscal_agent.api.routes.chat._handle_taxpayer', return_value={'nombre': 'Test'}):
			resp = client.post(
				'/v1/chat/message',
				json={'message': 'consulta CUIT 20324837796', 'conversation_id': 'conv-a1'},
			)
		assert resp.status_code == 200
		store: MagicMock = app_with_store.state.store
		store.append_messages.assert_awaited_with(
			'test-tenant-id',
			'conv-a1',
			[
				{'role': 'user', 'content': 'consulta CUIT 20324837796'},
				{'role': 'assistant', 'content': ANY},
			],
		)

	def test_sync_no_cuit_persists(self, client: TestClient, app_with_store: FastAPI) -> None:
		"""Early return (no CUIT) also persists."""
		resp = client.post(
			'/v1/chat/message',
			json={'message': 'deuda'},
		)
		assert resp.status_code == 200
		store: MagicMock = app_with_store.state.store
		store.append_messages.assert_awaited()

	def test_sse_auto_persists_before_complete(self, client: TestClient, app_with_store: FastAPI) -> None:
		"""SSE endpoint persists before complete event."""
		with patch('fiscal_agent.api.routes.chat._handle_reporte_with_echo', return_value={'calendario': {}}):
			resp = client.post(
				'/v1/chat/message/stream',
				json={'message': 'reporte completo 20324837796'},
			)

		assert resp.status_code == 200
		store: MagicMock = app_with_store.state.store
		store.append_messages.assert_awaited()


# ═══════════════════════════════════════════════════════════════════
# Phase 2 — SSE conversation_start tests
# ═══════════════════════════════════════════════════════════════════


class TestSSEConversationStart:
	"""SSE conversation_start event is always first."""

	def _parse_sse_events(self, text: str) -> list[dict]:
		"""Parse raw SSE text into list of {event, data} dicts."""
		events = []
		for raw in text.strip().split('\n\n'):
			if not raw.strip():
				continue
			event = ''
			data = ''
			for line in raw.split('\n'):
				if line.startswith('event: '):
					event = line[7:]
				elif line.startswith('data: '):
					data = line[6:]
			if event or data:
				events.append({'event': event, 'data': json.loads(data) if data else {}})
		return events

	def test_sse_conversation_start_first(self, client: TestClient) -> None:
		"""First SSE event is conversation_start."""
		with patch('fiscal_agent.api.routes.chat._handle_reporte_with_echo', return_value={'calendario': {}}):
			resp = client.post(
				'/v1/chat/message/stream',
				json={'message': 'reporte completo 20324837796'},
			)

		assert resp.status_code == 200
		events = self._parse_sse_events(resp.text)
		assert len(events) >= 2  # at least conversation_start + complete
		assert events[0]['event'] == 'conversation_start'
		assert 'conversation_id' in events[0]['data']

	def test_sse_early_return_no_cuit_has_conversation_start(self, client: TestClient) -> None:
		"""No-CUIT early return still emits conversation_start first."""
		resp = client.post(
			'/v1/chat/message/stream',
			json={'message': 'deuda'},
		)

		assert resp.status_code == 200
		events = self._parse_sse_events(resp.text)
		assert len(events) == 2
		assert events[0]['event'] == 'conversation_start'
		assert events[1]['event'] == 'complete'

	def test_sse_unknown_intent_has_conversation_start(self, client: TestClient) -> None:
		"""Unknown intent early return emits conversation_start first."""
		resp = client.post(
			'/v1/chat/message/stream',
			json={'message': 'hola'},
		)

		assert resp.status_code == 200
		events = self._parse_sse_events(resp.text)
		assert len(events) == 2
		assert events[0]['event'] == 'conversation_start'
		assert events[1]['event'] == 'complete'

	def test_sse_unsupported_intent_has_conversation_start(self, client: TestClient) -> None:
		"""Non-report intent emits conversation_start first."""
		resp = client.post(
			'/v1/chat/message/stream',
			json={'message': 'consulta CUIT 20324837796'},
		)

		assert resp.status_code == 200
		events = self._parse_sse_events(resp.text)
		assert len(events) == 2
		assert events[0]['event'] == 'conversation_start'

	def test_conversation_id_in_event(self, client: TestClient) -> None:
		"""conversation_start event carries the conversation_id."""
		resp = client.post(
			'/v1/chat/message/stream',
			json={'message': 'reporte completo 20324837796', 'conversation_id': 'test-conv-sse'},
		)
		assert resp.status_code == 200
		events = self._parse_sse_events(resp.text)
		assert events[0]['data']['conversation_id'] == 'test-conv-sse'


# ═══════════════════════════════════════════════════════════════════
# Phase 2 — tenant scoping tests
# ═══════════════════════════════════════════════════════════════════


class TestTenantScoping:
	"""tenant_id extracted from request state and passed to store."""

	def test_tenant_id_passed_to_store(self, client: TestClient, app_with_store: FastAPI) -> None:
		"""tenant_id from middleware is passed to append_messages."""
		with patch('fiscal_agent.api.routes.chat._handle_taxpayer', return_value={'nombre': 'Test'}):
			client.post(
				'/v1/chat/message',
				json={'message': 'consulta CUIT 20324837796'},
			)

		store: MagicMock = app_with_store.state.store
		call_args = store.append_messages.call_args
		assert call_args is not None
		tenant_id = call_args[0][0]  # first positional arg
		assert tenant_id == 'test-tenant-id'

	def test_sse_tenant_id_passed_to_store(self, client: TestClient, app_with_store: FastAPI) -> None:
		"""SSE endpoint passes tenant_id to append_messages."""
		with patch('fiscal_agent.api.routes.chat._handle_reporte_with_echo', return_value={'calendario': {}}):
			client.post(
				'/v1/chat/message/stream',
				json={'message': 'reporte completo 20324837796'},
			)

		store: MagicMock = app_with_store.state.store
		call_args = store.append_messages.call_args
		assert call_args is not None
		tenant_id = call_args[0][0]
		assert tenant_id == 'test-tenant-id'
