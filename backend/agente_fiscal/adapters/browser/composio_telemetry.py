"""Composio telemetry resolution — best-effort, never raises (ADR-7, AST-4).

The backend writes ``agent_sessions`` rows post-run (ADR-3) and fills the
Composio gap differently from Browserbase: the tool-execute API
(``/tools/execute``) does not return a stable session id, so this module
resolves it from the Composio APIs instead:

- ``POST /api/v3.1/logs/tool_execution`` — logs of executed tools; the run that
  created the browser session carries ``session_id`` (top-level or
  ``context.session_id``).
- ``POST /api/v3.1/project/usage/tool_calls`` — usage counters; ``event_count``
  ≈ number of tool executions in the window (task count).

Every public method is best-effort: any HTTP/parse failure → ``None`` /
``{}`` and a warning log. It NEVER raises, because telemetry must not break the
chat stream (same invariant as ``_persist_conversation``). The mock provider
keeps ``session_id`` NULL by design — only Composio resolves via this module.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

COMPOSIO_API_ROOT = 'https://backend.composio.dev/api/v3.1'
_LOGS_ENDPOINT = f'{COMPOSIO_API_ROOT}/logs/tool_execution'
_USAGE_ENDPOINT = f'{COMPOSIO_API_ROOT}/project/usage/tool_calls'

#: Slug of the tool that CREATES the browser task — its log entry holds the
#: session id of the run (ADR-7).
CREATE_TOOL_SLUG = 'BROWSER_TOOL_CREATE_TASK'

#: Default look-back window for the Logs/Usage queries. Best-effort: session
#: ids older than this (30 min) are outside the resolved run window.
DEFAULT_WINDOW_MINUTES = 30

#: Key pairs the responses may use (defensive parsing).
_SESSION_KEYS = ('session_id', 'sessionId')
_CONTEXT_SESSION_KEYS = ('context', )


def _now_iso() -> tuple[str, str]:
	"""ISO-8601 (Z) [start, end] window ending now, UTC."""
	now = datetime.now(timezone.utc)
	start = now - timedelta(minutes=DEFAULT_WINDOW_MINUTES)
	return start.isoformat(), now.isoformat()


def _deep_session_id(entry: dict[str, Any]) -> str | None:
	"""Session id from a log entry: top-level or nested under ``context``."""
	for key in _SESSION_KEYS:
		value = entry.get(key)
		if value:
			return str(value)
	context = entry.get('context') or {}
	if isinstance(context, dict):
		for key in _SESSION_KEYS:
			value = context.get(key)
			if value:
				return str(value)
	return None


class ComposioTelemetry:
	"""Best-effort resolution of Composio run telemetry (ADR-7).

	Usage::

	    resolver = ComposioTelemetry(api_key)
	    run = resolver.resolve_run(tool='informefiscal')
	    # run == {'session_id': '...', 'event_count': 12} | {}
	"""

	def __init__(self, api_key: str, *, timeout: float = 10.0) -> None:
		self._headers = {
			'x-api-key': api_key,
			'Content-Type': 'application/json',
		}
		self._timeout = timeout

	def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any] | None:
		"""POST + parse JSON. Never raises."""
		try:
			resp = requests.post(url, headers=self._headers, json=payload, timeout=self._timeout)
			resp.raise_for_status()
			return resp.json()
		except (requests.RequestException, ValueError) as exc:
			logger.warning('Composio telemetry %s falló: %s', url.rsplit('/', 1)[-1], exc)
			return None

	def fetch_session_id(self, *, tool: str = CREATE_TOOL_SLUG, start_time: str | None = None, end_time: str | None = None) -> str | None:
		"""Session id del run más reciente, desde Logs API (best-effort).

		Filtra por ``tool`` (la create-task que aloja la sesión) + ventana de
		tiempo. Lee ``session_id`` / ``context.session_id`` de la primer entrada
		que lo tenga. Retorna None si la API falla o no encuentra sesión (el
		caller guarda NULL — nunca diseña para un id inventado).
		"""
		start_time = start_time or _now_iso()[0]
		end_time = end_time or _now_iso()[1]
		body = self._post(
			_LOGS_ENDPOINT,
			{'tool': tool, 'start_time': start_time, 'end_time': end_time},
		)
		if not body:
			return None
		# Respuestas típicas: {"items":[...]} | {"data":[...]} | [...] | {"logs":[...]}
		for key in ('items', 'data', 'logs', 'executions'):
			entries = body.get(key)
			if isinstance(entries, list) and entries:
				break
		else:
			entries = body if isinstance(body, list) else None
		for entry in (entries or []):
			if isinstance(entry, dict):
				session_id = _deep_session_id(entry)
				if session_id:
					return session_id
		return None

	def fetch_event_count(self, *, start_time: str | None = None, end_time: str | None = None) -> int | None:
		"""Cantidad de tool-calls del proyecto desde Usage API (best-effort)."""
		start_time = start_time or _now_iso()[0]
		end_time = end_time or _now_iso()[1]
		body = self._post(
			_USAGE_ENDPOINT,
			{'start_time': start_time, 'end_time': end_time},
		)
		if not body:
			return None
		for key in ('event_count', 'eventCount', 'total_events'):
			value = body.get(key)
			if isinstance(value, (int, float)) and value > 0:
				return int(value)
		# "{"data": {"event_count": N}}" anidado.
		data = body.get('data')
		if isinstance(data, dict):
			for key in ('event_count', 'eventCount', 'total_events'):
				value = data.get(key)
				if isinstance(value, (int, float)) and value > 0:
					return int(value)
		return None

	def resolve_run(self, *, tool: str = CREATE_TOOL_SLUG) -> dict[str, int | str]:
		"""Resuelve ``session_id`` + ``event_count`` del run actual (best-effort).

		Combina las dos APIs en UNA llamada lógica; cualquier fallo individual
		devuelve el campo en None/ausente — NUNCA lanza. Idem ADR-7.
		"""
		resolved: dict[str, int | str] = {}
		try:
			session_id = self.fetch_session_id(tool=tool)
			if session_id:
				resolved['session_id'] = session_id
			event_count = self.fetch_event_count()
			if event_count:
				resolved['event_count'] = event_count
		except Exception as exc:  # pragma: no cover — última red de seguridad
			logger.warning('Composio telemetry resolve_run falló: %s', exc)
		return resolved


__all__ = ['ComposioTelemetry', 'resolve_run']


def resolve_run(api_key: str, *, tool: str = CREATE_TOOL_SLUG) -> dict[str, int | str]:
	"""Función helper de un-shot: ``ComposioTelemetry(api_key).resolve_run(...)``."""
	return ComposioTelemetry(api_key).resolve_run(tool=tool)