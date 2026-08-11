"""Tests for the memory package — FiscalMemoryClient + MemoryConfig."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import fakeredis
import pytest
import redis as redis_lib

from fiscal_agent.memory import FiscalMemoryClient, MemoryConfig


# ═════════════════════════════════════════════════════════════════════════════════
# MemoryConfig — defaults & env override
# ═════════════════════════════════════════════════════════════════════════════════


class TestMemoryConfig:
	"""Task 4.1: config defaults and env override."""

	def test_defaults(self) -> None:
		"""Default values match the spec."""
		config = MemoryConfig()
		assert config.engram_url == 'http://localhost:7437'
		assert config.redis_cache_url == 'redis://localhost:6379/0'
		assert config.redis_max_mb == 25
		assert config.engram_timeout == 10

	def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
		"""Setting ``MEMORY_*`` env vars overrides defaults."""
		monkeypatch.setenv('MEMORY_ENGRAM_URL', 'http://custom:9999')
		monkeypatch.setenv('MEMORY_REDIS_CACHE_URL', 'redis://custom:6380/1')
		monkeypatch.setenv('MEMORY_REDIS_MAX_MB', '50')
		monkeypatch.setenv('MEMORY_ENGRAM_TIMEOUT', '30')

		config = MemoryConfig()
		assert config.engram_url == 'http://custom:9999'
		assert config.redis_cache_url == 'redis://custom:6380/1'
		assert config.redis_max_mb == 50
		assert config.engram_timeout == 30

	def test_partial_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
		"""Only the overridden var changes; rest stay at defaults."""
		monkeypatch.setenv('MEMORY_ENGRAM_URL', 'http://custom:7437')
		config = MemoryConfig()
		assert config.engram_url == 'http://custom:7437'
		assert config.redis_max_mb == 25  # default


# ═════════════════════════════════════════════════════════════════════════════════
# FiscalMemoryClient — WRITE methods
# ═════════════════════════════════════════════════════════════════════════════════


class TestWriteMethods:
	"""Task 4.2: mock ``requests.post``, verify payload, session_id and type."""

	@pytest.fixture
	def client(self) -> FiscalMemoryClient:
		client = FiscalMemoryClient()
		# Pre-populate session cache so _ensure_cuit_session doesn't POST
		client._session_cache.add('cuit-20324837796')
		return client

	def _assert_observation_posted(
		self,
		mock_post: MagicMock,
		expected_cuit: str,
		expected_type: str,
	) -> None:
		"""Shared assertion for POST /observations calls."""
		# All POST calls go to /observations (session already cached)
		mock_post.assert_called_once()
		args, kwargs = mock_post.call_args
		url: str = args[0]
		assert '/observations' in url
		body = kwargs['json']
		assert expected_cuit in body['content']
		assert body['type'] == expected_type
		assert body['project'] == 'fiscal-agent'
		assert body['session_id'] == f'cuit-{expected_cuit}'

	def test_save_padron_result(self, client: FiscalMemoryClient) -> None:
		"""``save_padron_result`` posts to /observations with type=padron."""
		with patch('fiscal_agent.memory.client.requests.post') as mock_post:
			mock_post.return_value = MagicMock(ok=True, status_code=200, content=b'{}', json=lambda: {'ok': True})

			client.save_padron_result('20324837796', {'nombre': 'Test', 'tipo': 'responsable_inscripto'}, 'success')

			self._assert_observation_posted(mock_post, '20324837796', 'padron')

	def test_save_extraction_result(self, client: FiscalMemoryClient) -> None:
		"""``save_extraction_result`` posts to /observations with type=extraction_type."""
		with patch('fiscal_agent.memory.client.requests.post') as mock_post:
			mock_post.return_value = MagicMock(ok=True, status_code=200, content=b'{}', json=lambda: {'ok': True})

			client.save_extraction_result('20324837796', 'deuda', {'saldos': []}, 'success')

			self._assert_observation_posted(mock_post, '20324837796', 'deuda')

	def test_save_pdf_sent(self, client: FiscalMemoryClient) -> None:
		"""``save_pdf_sent`` posts to /observations with type=pdf."""
		with patch('fiscal_agent.memory.client.requests.post') as mock_post:
			mock_post.return_value = MagicMock(ok=True, status_code=200, content=b'{}', json=lambda: {'ok': True})

			client.save_pdf_sent('20324837796', '/tmp/output.pdf', 'cliente@example.com', 'sent')

			self._assert_observation_posted(mock_post, '20324837796', 'pdf')
			args, kwargs = mock_post.call_args
			body = kwargs['json']
			assert '/tmp/output.pdf' in body['content']
			assert 'cliente@example.com' in body['content']

	def test_save_pipeline_error(self, client: FiscalMemoryClient) -> None:
		"""``save_pipeline_error`` posts to /observations with type=error."""
		with patch('fiscal_agent.memory.client.requests.post') as mock_post:
			mock_post.return_value = MagicMock(ok=True, status_code=200, content=b'{}', json=lambda: {'ok': True})

			client.save_pipeline_error('20324837796', 'browser', 'Timeout connecting to Composio')

			self._assert_observation_posted(mock_post, '20324837796', 'error')
			args, kwargs = mock_post.call_args
			body = kwargs['json']
			assert 'browser' in body['content']
			assert 'Timeout' in body['content']


class TestSessionCreation:
	"""Cada CUIT recibe su propia sesión Engram al primer write."""

	def test_session_created_on_first_write(self) -> None:
		"""Primer write de un CUIT crea su sesión (cuit-{cuit})."""
		client = FiscalMemoryClient()
		with patch('fiscal_agent.memory.client.requests.post') as mock_post:

			def side_effect(url, *a, **kw):
				if '/sessions' in url:
					return MagicMock(ok=True, status_code=200, content=b'{}', json=lambda: {})
				if '/observations' in url:
					return MagicMock(ok=True, status_code=200, content=b'{}', json=lambda: {})
				return MagicMock(ok=True, status_code=200, content=b'{}')

			mock_post.side_effect = side_effect

			client.save_pipeline_error('20324837796', 'test', 'primer error')

			# Debería haber llamado primero a /sessions y luego a /observations
			assert mock_post.call_count == 2
			session_call = mock_post.call_args_list[0]
			assert '/sessions' in session_call[0][0]
			assert session_call[1]['json']['id'] == 'cuit-20324837796'

			obs_call = mock_post.call_args_list[1]
			assert '/observations' in obs_call[0][0]
			assert obs_call[1]['json']['session_id'] == 'cuit-20324837796'

	def test_session_cached_after_first_write(self) -> None:
		"""Segundo write del mismo CUIT no crea la sesión de nuevo."""
		client = FiscalMemoryClient()
		with patch('fiscal_agent.memory.client.requests.post') as mock_post:

			def side_effect(url, *a, **kw):
				if '/sessions' in url:
					return MagicMock(ok=True, status_code=200, content=b'{}', json=lambda: {})
				if '/observations' in url:
					return MagicMock(ok=True, status_code=200, content=b'{}', json=lambda: {})
				return MagicMock(ok=True, status_code=200, content=b'{}')

			mock_post.side_effect = side_effect

			# Primer write — crea sesión + observation
			client.save_pipeline_error('20324837796', 'test', 'error 1')
			assert mock_post.call_count == 2

			# Segundo write — solo observation
			client.save_pipeline_error('20324837796', 'test', 'error 2')
			assert mock_post.call_count == 3  # solo 1 call más (observation nada más)
			last_call = mock_post.call_args_list[2]
			assert '/observations' in last_call[0][0]


# ═════════════════════════════════════════════════════════════════════════════════
# FiscalMemoryClient — READ methods
# ═════════════════════════════════════════════════════════════════════════════════


class TestReadMethods:
	"""Task 4.3: mock ``requests.get``, verify parse and return structure."""

	@pytest.fixture
	def client(self) -> FiscalMemoryClient:
		return FiscalMemoryClient()

	def _mock_search_results(self, results: list | None = None) -> MagicMock:
		"""Return a mock response for Engram /search returning a list."""
		payload = results or []
		mock_resp = MagicMock()
		mock_resp.json.return_value = payload
		mock_resp.content = json.dumps(payload).encode()
		mock_resp.ok = True
		return mock_resp

	def _assert_search_url(self, url: str, cuit: str, obs_type: str | None = None) -> None:
		"""Verify the search URL includes CUIT, project, session_id, and optional type."""
		assert cuit in url
		assert 'project=fiscal-agent' in url
		assert f'session_id=cuit-{cuit}' in url
		if obs_type:
			assert obs_type in url

	def test_get_padron_history(self, client: FiscalMemoryClient) -> None:
		"""Returns list of padron results from Engram search."""
		expected = [
			{
				'id': 1,
				'title': 'Padrón A5: 20324837796',
				'type': 'padron',
				'content': '**Cuit**: 20324837796\n**Status**: success',
			}
		]
		with patch('fiscal_agent.memory.client.requests.get') as mock_get:
			mock_get.return_value = self._mock_search_results(expected)

			result = client.get_padron_history('20324837796')

			assert result == expected
			mock_get.assert_called_once()
			args, _ = mock_get.call_args
			self._assert_search_url(args[0], '20324837796', 'padron')

	def test_get_extraction_history(self, client: FiscalMemoryClient) -> None:
		"""Returns list of extraction results filtered by type."""
		expected = [{'id': 2, 'type': 'deuda', 'title': 'Extracción deuda: 20324837796'}]
		with patch('fiscal_agent.memory.client.requests.get') as mock_get:
			mock_get.return_value = self._mock_search_results(expected)

			result = client.get_extraction_history('20324837796', 'deuda')

			assert result == expected
			args, _ = mock_get.call_args
			self._assert_search_url(args[0], '20324837796', 'deuda')

	def test_get_pipeline_history(self, client: FiscalMemoryClient) -> None:
		"""Returns list of pipeline events."""
		expected = [{'id': 3, 'type': 'padron'}, {'id': 4, 'type': 'error'}]
		with patch('fiscal_agent.memory.client.requests.get') as mock_get:
			mock_get.return_value = self._mock_search_results(expected)

			result = client.get_pipeline_history('20324837796')

			assert result == expected
			args, _ = mock_get.call_args
			self._assert_search_url(args[0], '20324837796')

	def test_get_last_error_found(self, client: FiscalMemoryClient) -> None:
		"""Returns the error observation whose content matches the stage."""
		expected = {'id': 5, 'type': 'error', 'content': '**Cuit**: 20324837796\n**Stage**: browser\n**Error**: Timeout'}
		with patch('fiscal_agent.memory.client.requests.get') as mock_get:
			# Return multiple errors — should filter by stage=browser
			results = [
				{'id': 4, 'type': 'error', 'content': '**Cuit**: 20324837796\n**Stage**: pdf\n**Error**: OOM'},
				expected,
			]
			mock_get.return_value = self._mock_search_results(results)

			result = client.get_last_error('20324837796', 'browser')

			assert result == expected

	def test_get_last_error_none(self, client: FiscalMemoryClient) -> None:
		"""Returns ``None`` when no errors exist."""
		with patch('fiscal_agent.memory.client.requests.get') as mock_get:
			mock_get.return_value = self._mock_search_results([])

			result = client.get_last_error('20324837796', 'browser')

			assert result is None


# ═════════════════════════════════════════════════════════════════════════════════
# Cache TTLs — fakeredis
# ═════════════════════════════════════════════════════════════════════════════════


class TestCacheTTLs:
	"""Task 4.4: ``fakeredis``, verify reads cache and writes bypass cache."""

	@pytest.fixture
	def client(self) -> FiscalMemoryClient:
		client = FiscalMemoryClient()
		client._redis = fakeredis.FakeRedis()
		client._session_cache.add('cuit-20324837796')
		client._session_cache.add('cuit-30716395541')
		return client

	def test_read_caches_padron(self, client: FiscalMemoryClient) -> None:
		"""First read hits Engram, second read uses Redis cache."""
		expected = [{'id': 1, 'type': 'padron', 'title': 'Padrón A5: 20324837796', 'content': '**Cuit**: 20324837796'}]
		with patch('fiscal_agent.memory.client.requests.get') as mock_get:
			mock_resp = MagicMock()
			mock_resp.json.return_value = expected  # /search returns list
			mock_resp.content = json.dumps(expected).encode()
			mock_resp.ok = True
			mock_get.return_value = mock_resp

			# First call — should hit Engram
			r1 = client.get_padron_history('20324837796')
			assert r1 == expected
			assert mock_get.call_count == 1

			# Second call — should use cache
			r2 = client.get_padron_history('20324837796')
			assert r2 == expected
			assert mock_get.call_count == 1  # not called again

			# Verify cache entry exists with correct prefix
			cached = client._redis.get('memory:20324837796:padron')
			assert cached is not None
			assert json.loads(cached) == expected

	def test_write_does_not_cache(self, client: FiscalMemoryClient) -> None:
		"""WRITE methods do NOT populate the Redis cache."""
		with patch('fiscal_agent.memory.client.requests.post') as mock_post:
			mock_post.return_value = MagicMock(ok=True, status_code=200, content=b'{}')

			client.save_padron_result('20324837796', {'nombre': 'Test'}, 'success')

			# No cache key should exist for padron writes
			assert client._redis.get('memory:20324837796:padron') is None

	def test_cache_expiration(self, client: FiscalMemoryClient) -> None:
		"""Cache entries have the configured TTL."""
		with patch('fiscal_agent.memory.client.requests.get') as mock_get:
			mock_resp = MagicMock()
			mock_resp.json.return_value = [{'data': 'test'}]
			mock_resp.content = b'[{"data": "test"}]'
			mock_resp.ok = True
			mock_get.return_value = mock_resp

			client.get_padron_history('20324837796')

			# Check TTL is ~86400s (24h)
			ttl = client._redis.ttl('memory:20324837796:padron')
			assert 86000 <= ttl <= 86400, f'Expected TTL ~86400s, got {ttl}'

	def test_different_cuits_have_separate_cache(self, client: FiscalMemoryClient) -> None:
		"""Cache keys are scoped by CUIT."""
		with patch('fiscal_agent.memory.client.requests.get') as mock_get:
			mock_resp = MagicMock()
			mock_resp.json.return_value = []
			mock_resp.content = b'[]'
			mock_resp.ok = True
			mock_get.return_value = mock_resp

			client.get_padron_history('20324837796')
			client.get_padron_history('30716395541')

			assert mock_get.call_count == 2  # no cache hit across CUITs


# ═════════════════════════════════════════════════════════════════════════════════
# Best-effort — error swallowing
# ═════════════════════════════════════════════════════════════════════════════════


class TestBestEffort:
	"""Task 4.5: mock to raise ``ConnectionError``, verify None without exception."""

	@pytest.fixture
	def client(self) -> FiscalMemoryClient:
		return FiscalMemoryClient()

	def test_write_silent_on_connection_error(self, client: FiscalMemoryClient) -> None:
		"""WRITE methods swallow ``ConnectionError`` and return None."""
		with patch('fiscal_agent.memory.client.requests.post', side_effect=ConnectionError('No route to host')):
			# Must not raise
			client.save_padron_result('20324837796', {}, 'success')
			client.save_extraction_result('20324837796', 'deuda', {}, 'success')
			client.save_pdf_sent('20324837796', '/tmp/p.pdf', 'a@b.com', 'sent')
			client.save_pipeline_error('20324837796', 'pipeline', 'error')

	def test_read_returns_default_on_connection_error(self, client: FiscalMemoryClient) -> None:
		"""READ methods return empty list / None on connection error."""
		with patch('fiscal_agent.memory.client.requests.get', side_effect=ConnectionError('No route to host')):
			assert client.get_padron_history('20324837796') == []
			assert client.get_extraction_history('20324837796', 'deuda') == []
			assert client.get_pipeline_history('20324837796') == []
			assert client.get_last_error('20324837796', 'browser') is None

	def test_requests_timeout(self, client: FiscalMemoryClient) -> None:
		"""Timeout raises ``requests.Timeout`` which is also swallowed."""
		with patch('fiscal_agent.memory.client.requests.post', side_effect=requests.Timeout('timed out')):
			client.save_padron_result('20324837796', {}, 'success')  # must not raise

	def test_is_available_false_on_error(self, client: FiscalMemoryClient) -> None:
		"""``is_available`` returns False on connection error."""
		with patch('fiscal_agent.memory.client.requests.get', side_effect=ConnectionError('No route to host')):
			assert client.is_available() is False

	def test_is_available_true_on_200(self, client: FiscalMemoryClient) -> None:
		"""``is_available`` returns True on HTTP 200."""
		with patch('fiscal_agent.memory.client.requests.get') as mock_get:
			mock_get.return_value = MagicMock(ok=True, status_code=200)
			assert client.is_available() is True

	def test_is_available_false_on_non_200(self, client: FiscalMemoryClient) -> None:
		"""``is_available`` returns False on non-2xx status."""
		with patch('fiscal_agent.memory.client.requests.get') as mock_get:
			mock_get.return_value = MagicMock(ok=False, status_code=503)
			assert client.is_available() is False


# ═════════════════════════════════════════════════════════════════════════════════
# Redis space check
# ═════════════════════════════════════════════════════════════════════════════════


class TestRedisHasSpace:
	"""Task 4.6: ``_redis_has_space`` with fakeredis + INFO memory mock."""

	@pytest.fixture
	def client(self) -> FiscalMemoryClient:
		client = FiscalMemoryClient()
		client._redis = fakeredis.FakeRedis()
		return client

	def test_has_space_by_default(self, client: FiscalMemoryClient) -> None:
		"""A fresh fake Redis has space under the 25 MB limit."""
		assert client._redis_has_space() is True

	def test_above_limit_returns_false(self, client: FiscalMemoryClient) -> None:
		"""When used_memory exceeds ``redis_max_mb``, returns False."""
		# Mock redis info to return a high used_memory value
		original_info = client._redis.info

		def mock_info(section: str = '') -> dict:
			if section == 'memory':
				return {'used_memory': 50 * 1024 * 1024}  # 50 MB — above 25 MB limit
			return original_info(section)

		with patch.object(client._redis, 'info', side_effect=mock_info):
			assert client._redis_has_space() is False

	def test_exception_falls_back_to_true(self, client: FiscalMemoryClient) -> None:
		"""If ``INFO memory`` fails, ``_redis_has_space`` returns True (best-effort)."""
		with patch.object(client._redis, 'info', side_effect=redis_lib.ResponseError('not supported')):
			assert client._redis_has_space() is True

	def test_cache_set_skips_when_full(self, client: FiscalMemoryClient) -> None:
		"""Cache SET is skipped when Redis is above the memory limit."""
		# Force the space check to return False
		original_info = client._redis.info

		def mock_info(section: str = '') -> dict:
			if section == 'memory':
				return {'used_memory': 50 * 1024 * 1024}  # 50 MB
			return original_info(section)

		with (
			patch.object(client._redis, 'info', side_effect=mock_info),
			patch.object(client._redis, 'setex', wraps=client._redis.setex) as mock_setex,
			patch('fiscal_agent.memory.client.requests.get') as mock_get,
		):
			mock_get.return_value = MagicMock(
				ok=True,
				status_code=200,
				json=lambda: [{'data': 'test'}],
				content=b'[{"data": "test"}]',
			)

			# Read triggers a cache write — but should be skipped due to no space
			client.get_padron_history('20324837796')

			# setex should NOT have been called
			mock_setex.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════════
# Integration-style: lazy Redis init
# ═════════════════════════════════════════════════════════════════════════════════


class TestLazyRedis:
	"""Redis client is lazily initialised on first use."""

	def test_redis_not_initialised_on_construction(self) -> None:
		"""``_redis`` is ``None`` after ``__init__``."""
		client = FiscalMemoryClient()
		assert client._redis is None

	def test_redis_initialised_on_access(self) -> None:
		"""``_redis_client`` creates the connection on first access."""
		client = FiscalMemoryClient()
		rc = client._redis_client
		assert rc is not None
		assert client._redis is rc  # cached

	def test_redis_from_url_config(self) -> None:
		"""``_redis_client`` uses ``redis_cache_url`` from config."""
		client = FiscalMemoryClient()
		rc = client._redis_client
		assert rc.connection_pool.connection_kwargs['host'] == 'localhost'
