"""FiscalMemoryClient — Engram persistence + Redis cache for pipeline results."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import redis
import requests

from fiscal_agent.adapters.memory.config import MemoryConfig
from fiscal_agent.domain.models import PipelineRun

logger = logging.getLogger(__name__)

# ── Cache TTLs (seconds) ─────────────────────────────────────────────────────────
_TTL_PADRON: int = 86400  # 24 h
_TTL_EXTRACTION: int = 604800  # 7 d
_TTL_PIPELINE: int = 3600  # 1 h


class FiscalMemoryClient:
	"""Lightweight sync client for Engram memory with Redis read cache.

	Each CUIT gets its own permanent Engram session (``cuit-{cuit}``) so
	every contribuyente has an isolated "brain" of observations. Sessions
	are created on first write and never closed.

	Best-effort semantics: every public method swallows exceptions and
	logs a warning instead of raising. Designed for pipeline observability,
	not transactional guarantees.
	"""

	def __init__(self, config: MemoryConfig | None = None) -> None:
		self.config = config or MemoryConfig()
		self._redis: redis.Redis | None = None
		# Track which CUIT sessions we've already ensured exist.
		self._session_cache: set[str] = set()

	# ── Session management (per CUIT) ───────────────────────────────────────

	@staticmethod
	def cuit_session_id(cuit: str) -> str:
		"""Return the stable Engram session ID for *cuit*."""
		return f'cuit-{cuit}'

	def _ensure_cuit_session(self, cuit: str) -> str:
		"""Create a permanent Engram session for *cuit* if not already done.

		Returns the ``session_id`` to use for all observations of this CUIT.
		Idempotent: only POSTs to Engram once per CUIT per client lifetime.
		"""
		session_id = self.cuit_session_id(cuit)
		if session_id in self._session_cache:
			return session_id

		try:
			self._engram_post(
				'/sessions',
				{
					'id': session_id,
					'project': 'fiscal-agent',
					'directory': f'/app/cuits/{cuit}',
				},
			)
			logger.info('[memory] 🧠 Cerebro creado para CUIT %s', cuit)
		except Exception:
			logger.warning('[memory] ⚠️ Engram no disponible, la memoria se habilita cuando Engram esté corriendo')

		self._session_cache.add(session_id)
		return session_id

	# ── Engram observation helpers ────────────────────────────────────────────

	@staticmethod
	def _obs_content(**fields: Any) -> str:
		"""Build structured Markdown content from keyword fields (What/Why/Where/Learned style)."""
		parts = [f'**{k.replace("_", " ").title()}**: {v}' for k, v in fields.items()]
		return '\n'.join(parts)

	# ── Public: WRITE ─────────────────────────────────────────────────────────

	def save_padron_result(self, cuit: str, padron_data: dict, status: str) -> None:
		"""Persist the WS ARCA padron lookup result for *cuit*."""
		try:
			session_id = self._ensure_cuit_session(cuit)
			self._engram_post(
				'/observations',
				{
					'session_id': session_id,
					'title': f'Padrón A5: {cuit}',
					'type': 'padron',
					'content': self._obs_content(
						cuit=cuit,
						status=status,
						data=json.dumps(padron_data, default=str),
						timestamp=datetime.now(timezone.utc).isoformat(),
					),
					'project': 'fiscal-agent',
					'scope': 'project',
				},
			)
		except Exception:
			logger.warning('[memory] ⚠️ No se pudo guardar padrón para CUIT %s — Engram no disponible', cuit)

	def save_extraction_result(self, cuit: str, extraction_type: str, data: dict, status: str) -> None:
		"""Persist a browser-extraction result (deuda, facilidades, registro)."""
		try:
			session_id = self._ensure_cuit_session(cuit)
			self._engram_post(
				'/observations',
				{
					'session_id': session_id,
					'title': f'Extracción {extraction_type}: {cuit}',
					'type': extraction_type,
					'content': self._obs_content(
						cuit=cuit,
						extraction_type=extraction_type,
						status=status,
						data=json.dumps(data, default=str),
						timestamp=datetime.now(timezone.utc).isoformat(),
					),
					'project': 'fiscal-agent',
					'scope': 'project',
				},
			)
		except Exception:
			logger.warning(
				'[memory] ⚠️ No se pudo guardar extracción %s para CUIT %s — Engram no disponible', extraction_type, cuit
			)

	def save_pdf_sent(self, cuit: str, pdf_path: str, email_sent_to: str, status: str) -> None:
		"""Record that a PDF was generated and emailed for *cuit*."""
		try:
			session_id = self._ensure_cuit_session(cuit)
			self._engram_post(
				'/observations',
				{
					'session_id': session_id,
					'title': f'PDF {status}: {cuit}',
					'type': 'pdf',
					'content': self._obs_content(
						cuit=cuit,
						pdf_path=pdf_path,
						email_sent_to=email_sent_to,
						status=status,
						timestamp=datetime.now(timezone.utc).isoformat(),
					),
					'project': 'fiscal-agent',
					'scope': 'project',
				},
			)
		except Exception:
			logger.warning('[memory] ⚠️ No se pudo guardar PDF para CUIT %s — Engram no disponible', cuit)

	def save_pipeline_run(self, cuit: str, run: PipelineRun) -> None:
		"""Persist a ``PipelineRun`` observation in Engram under *cuit*'s session.

		Writes a ``pipeline_run`` observation with structured Markdown content
		so it appears in the CUIT's brain and is searchable via Engram queries.
		Best-effort semantics: swallows exceptions.
		"""
		try:
			session_id = self._ensure_cuit_session(cuit)
			self._engram_post(
				'/observations',
				{
					'session_id': session_id,
					'title': f'Pipeline {run.status}: {cuit}',
					'type': 'pipeline_run',
					'content': self._obs_content(
						cuit=cuit,
						status=run.status,
						stages=', '.join(run.stages_completed) if run.stages_completed else 'none',
						duration=f'{run.duration_seconds:.2f}s',
						error=run.error or '',
						timestamp=run.timestamp.isoformat(),
					),
					'project': 'fiscal-agent',
					'scope': 'project',
				},
			)
		except Exception:
			logger.warning('[memory] ⚠️ No se pudo guardar PipelineRun para CUIT %s — Engram no disponible', cuit)

	def save_pipeline_error(self, cuit: str, stage: str, error_message: str) -> None:
		"""Record a pipeline error for *cuit* at a specific *stage*."""
		try:
			session_id = self._ensure_cuit_session(cuit)
			self._engram_post(
				'/observations',
				{
					'session_id': session_id,
					'title': f'Error {stage}: {cuit}',
					'type': 'error',
					'content': self._obs_content(
						cuit=cuit,
						stage=stage,
						error=error_message,
						timestamp=datetime.now(timezone.utc).isoformat(),
					),
					'project': 'fiscal-agent',
					'scope': 'project',
				},
			)
		except Exception:
			logger.warning('[memory] ⚠️ No se pudo guardar error para CUIT %s — Engram no disponible', cuit)

	def save_observation(
		self,
		cuit: str,
		title: str,
		obs_type: str,
		content: str,
	) -> None:
		"""Save an arbitrary observation for *cuit* in Engram.

		Generic method used by API and MCP tools for observations that don't
		fit the structured save_* methods. Wraps _ensure_cuit_session +
		_engram_post + _session_cache in a single public call.

		Best-effort semantics: swallows exceptions.
		"""
		try:
			session_id = self._ensure_cuit_session(cuit)
			self._engram_post(
				'/observations',
				{
					'session_id': session_id,
					'title': title,
					'type': obs_type,
					'content': content,
					'project': 'fiscal-agent',
					'scope': 'project',
				},
			)
		except Exception:
			logger.warning(
				'[memory] ⚠️ No se pudo guardar observación %s para CUIT %s — Engram no disponible',
				obs_type,
				cuit,
			)

	# ── Public: READ ──────────────────────────────────────────────────────────

	def _search_observations(self, cuit: str, obs_type: str | None = None, limit: int = 10) -> list[dict]:
		"""Search Engram for observations matching *cuit* (and optionally *obs_type*).

		Scoped to the CUIT's session (``cuit-{cuit}``) so each contribuyente
		only sees their own brain. Results are newest first.
		"""
		session_id = self.cuit_session_id(cuit)
		query_parts = [cuit]
		if obs_type:
			query_parts.append(obs_type)
		query = ' '.join(query_parts)
		data = self._engram_get(
			f'/search?q={query}&project=fiscal-agent&session_id={session_id}&limit={limit}',
		)
		if isinstance(data, list):
			return data
		if isinstance(data, dict):
			return data.get('results', data.get('observations', []))
		return []

	def get_padron_history(self, cuit: str, limit: int = 3) -> list[dict]:
		"""Return last *limit* padron results for *cuit*.

		Results are cached in Redis for 24 h on first read.
		"""
		cache_key = f'memory:{cuit}:padron'
		try:
			cached = self._cache_get(cache_key)
			if cached is not None:
				return json.loads(cached)

			results = self._search_observations(cuit, obs_type='padron', limit=limit)
			self._cache_set(cache_key, json.dumps(results), ttl=_TTL_PADRON)
			return results
		except Exception:
			return []

	def get_extraction_history(self, cuit: str, extraction_type: str, limit: int = 3) -> list[dict]:
		"""Return last *limit* extraction results of *extraction_type* for *cuit*.

		Cached in Redis for 7 d.
		"""
		cache_key = f'memory:{cuit}:extraction:{extraction_type}'
		try:
			cached = self._cache_get(cache_key)
			if cached is not None:
				return json.loads(cached)

			results = self._search_observations(cuit, obs_type=extraction_type, limit=limit)
			self._cache_set(cache_key, json.dumps(results), ttl=_TTL_EXTRACTION)
			return results
		except Exception:
			return []

	def get_pipeline_history(self, cuit: str, limit: int = 10) -> list[dict]:
		"""Return last *limit* pipeline events for *cuit*.

		Cached in Redis for 1 h.
		"""
		cache_key = f'memory:{cuit}:pipeline'
		try:
			cached = self._cache_get(cache_key)
			if cached is not None:
				return json.loads(cached)

			results = self._search_observations(cuit, limit=limit)
			self._cache_set(cache_key, json.dumps(results), ttl=_TTL_PIPELINE)
			return results
		except Exception:
			return []

	def get_last_error(self, cuit: str, stage: str) -> dict | None:
		"""Return the most recent error for *cuit* at *stage*, or ``None``."""
		try:
			results = self._search_observations(cuit, obs_type='error', limit=5)
			# Filter by stage in content
			for obs in results:
				content = obs.get('content', '')
				if f'**Stage**: {stage}' in content or f'stage: {stage}' in content:
					return obs
			return None
		except Exception:
			return None

	# ── Helpers ───────────────────────────────────────────────────────────────

	def is_available(self) -> bool:
		"""Check if Engram is reachable via ``GET /health``.

		Returns ``True`` on a 2xx response, ``False`` otherwise.
		"""
		try:
			resp = requests.get(
				f'{self.config.engram_url}/health',
				timeout=self.config.engram_timeout,
			)
			return resp.ok
		except Exception:
			logger.warning('[memory] ⚠️ Engram no está disponible — levantá el contenedor con: docker compose up -d engram')
			return False

	def _redis_has_space(self) -> bool:
		"""Check that Redis ``used_memory`` is below ``redis_max_mb``."""
		try:
			info = self._redis_client.info('memory')
			used_mb = info.get('used_memory', 0) / (1024 * 1024)
			return used_mb < self.config.redis_max_mb
		except Exception:
			return True

	# ── Private: Engram HTTP helpers (sync) ──────────────────────────────────

	def _engram_post(self, path: str, data: dict) -> dict | None:
		"""POST JSON *data* to Engram *path*. Returns parsed JSON or ``None``."""
		resp = requests.post(
			f'{self.config.engram_url}{path}',
			json=data,
			timeout=self.config.engram_timeout,
		)
		resp.raise_for_status()
		return resp.json() if resp.content else None

	def _engram_get(self, path: str) -> dict | None:
		"""GET from Engram *path*. Returns parsed JSON or ``None``."""
		resp = requests.get(
			f'{self.config.engram_url}{path}',
			timeout=self.config.engram_timeout,
		)
		resp.raise_for_status()
		return resp.json() if resp.content else None

	# ── Private: Redis cache helpers (sync) ──────────────────────────────────

	def _cache_get(self, key: str) -> str | None:
		"""Read value from Redis cache. Returns ``None`` if missing or error."""
		try:
			val = self._redis_client.get(key)
			return val.decode('utf-8') if val is not None else None
		except Exception:
			return None

	def _cache_set(self, key: str, value: str, ttl: int) -> None:
		"""Write *value* to Redis cache with *ttl* seconds.

		Skips write if Redis exceeds the configured memory limit.
		"""
		try:
			if not self._redis_has_space():
				logger.warning('[memory] ⚠️ Redis cerca del límite de 25MB, saltando cache temporal')
				return
			self._redis_client.setex(key, ttl, value)
		except Exception:
			pass

	@property
	def _redis_client(self) -> redis.Redis:
		"""Lazy-initialised sync Redis client."""
		if self._redis is None:
			self._redis = redis.Redis.from_url(self.config.redis_cache_url)
		return self._redis
