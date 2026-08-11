"""System monitoring endpoints — metrics, services, activity, errors.

Endpoints:
- ``GET /v1/system/metrics`` — métricas agregadas del pipeline
- ``GET /v1/system/services`` — estado de todos los servicios
- ``GET /v1/system/activity`` — feed de actividad reciente
- ``GET /v1/system/errors`` — lista de errores con filtros

Todos los endpoints cachean en Redis.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Query, Request

from fiscal_agent.api.deps import get_memory
from fiscal_agent.api.routes.health import _check_composio, _check_engram, _check_redis, _check_ta
from fiscal_agent.adapters.memory import FiscalMemoryClient
from fiscal_agent.domain.models import (
	ActivityEvent,
	ApiError,
	ErrorEvent,
	ServiceStatus,
	SystemHealth,
	SystemMetrics,
	UnifiedResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Cache helpers ────────────────────────────────────────────────────────


async def _cache_get(request: Request, key: str) -> str | None:
	"""Read from Redis cache, return None if missing/error."""
	try:
		val = await request.app.state.redis.get(key)
		return val if val else None
	except Exception:
		return None


async def _cache_set(request: Request, key: str, value: str, ttl: int) -> None:
	"""Write to Redis cache with TTL."""
	try:
		await request.app.state.redis.setex(key, ttl, value)
	except Exception:
		pass


_ERROR_TYPE_MAP = {
	'timeout': 'TimeoutException',
	'arca': 'ARCAError',
	'composio': 'ComposioError',
	'engram': 'EngramError',
	'redis': 'RedisError',
	'validation': 'ValidationError',
}


def _map_error_type(raw: str) -> str:
	"""Map raw error type strings to classified ErrorEvent types."""
	lower = raw.lower()
	for key, mapped in _ERROR_TYPE_MAP.items():
		if key in lower:
			return mapped
	return 'Unknown'


def _parse_engram_observations(observations: list[dict]) -> list[dict]:
	"""Parse raw Engram observation list into a normalized list of dicts.

	Engram returns observations with ``content`` as structured Markdown.
	This extracts key fields for system metrics.
	"""
	parsed = []
	for obs in observations:
		content = obs.get('content', '')
		# Try to extract structured fields from Markdown content
		fields = {}
		for line in content.split('\n'):
			if '**:' in line:
				key_end = line.find('**:')
				key = line[:key_end].strip('* ')
				value = line[key_end + 3 :].strip()
				if key and value:
					fields[key.lower()] = value
		parsed.append(
			{
				'id': obs.get('id'),
				'type': obs.get('type'),
				'title': obs.get('title'),
				'timestamp': obs.get('created_at') or obs.get('timestamp'),
				'content': content,
				'fields': fields,
			}
		)
	return parsed


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get(
	'/v1/system/metrics',
	response_model=UnifiedResponse[SystemMetrics],
	summary='Métricas del sistema',
)
async def get_system_metrics(
	request: Request,
	period: Literal['24h', '7d', '30d'] = Query(default='24h', description='Período de agregación'),
) -> UnifiedResponse[SystemMetrics]:
	"""Retorna métricas agregadas del pipeline.

	Agrega observaciones Engram de tipo ``pipeline_run`` del período
	seleccionado. Cacheado en Redis por 30 segundos.
	"""
	cache_key = f'system:metrics:{period}'
	cached = await _cache_get(request, cache_key)
	if cached:
		return UnifiedResponse(status='success', result=SystemMetrics(**json.loads(cached)))

	# Calculate period cutoff
	hours = {'24h': 24, '7d': 168, '30d': 720}[period]
	cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

	memory: FiscalMemoryClient = get_memory()

	# Query Engram for pipeline_run observations across all CUITs
	# We use the global search endpoint
	try:
		search_results = memory._engram_get(  # noqa: SLF001
			f'/search?q=pipeline_run&project=fiscal-agent&type=pipeline_run&limit=500'
		)
		observations = (
			search_results
			if isinstance(search_results, list)
			else (search_results.get('results', []) if isinstance(search_results, dict) else [])
		)
	except Exception:
		observations = []

	parsed = _parse_engram_observations(observations)

	# Filter by period
	recent = []
	for obs in parsed:
		ts_str = obs.get('timestamp')
		if ts_str:
			try:
				ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
				if ts >= cutoff:
					recent.append(obs)
			except (ValueError, TypeError):
				recent.append(obs)

	total_runs = len(recent)
	successful = sum(1 for r in recent if r['fields'].get('status') in ('success', 'partial'))
	failed = sum(1 for r in recent if r['fields'].get('status') == 'failed')
	failed = max(0, total_runs - successful) if total_runs > successful else failed
	error_rate = round(failed / total_runs, 4) if total_runs > 0 else 0.0

	# Unique CUITs
	cuits = {r['fields'].get('cuit') for r in recent if r['fields'].get('cuit')}

	# Recent errors from error observations
	try:
		errors_results = memory._engram_get(  # noqa: SLF001
			f'/search?q=error&project=fiscal-agent&type=error&limit=20'
		)
		error_obs = (
			errors_results
			if isinstance(errors_results, list)
			else (errors_results.get('results', []) if isinstance(errors_results, dict) else [])
		)
	except Exception:
		error_obs = []

	recent_errors = []
	for e in error_obs[:10]:
		content = e.get('content', '')
		fields = {}
		for line in content.split('\n'):
			if '**:' in line:
				key_end = line.find('**:')
				key = line[:key_end].strip('* ')
				value = line[key_end + 3 :].strip()
				if key and value:
					fields[key.lower()] = value
		recent_errors.append(
			ErrorEvent(
				id=str(e.get('id', uuid.uuid4())),
				type=_map_error_type(fields.get('stage', 'Unknown')),
				message=fields.get('error', e.get('title', '')),
				severity='error',
				service='pipeline',
				cuit=fields.get('cuit'),
				timestamp=datetime.now(timezone.utc),
				count=1,
				trend='stable',
			)
		)

	metrics = SystemMetrics(
		total_pipeline_runs=total_runs,
		successful_runs=successful,
		failed_runs=failed,
		error_rate=error_rate,
		total_cuits_processed=len(cuits),
		recent_errors=recent_errors,
		runs_by_hour=[],
	)

	# Cache for 30s
	await _cache_set(request, cache_key, metrics.model_dump_json(), ttl=30)

	return UnifiedResponse(status='success', result=metrics)


@router.get(
	'/v1/system/services',
	response_model=UnifiedResponse[list[ServiceStatus]],
	summary='Estado de servicios',
)
async def get_system_services(
	request: Request,
) -> UnifiedResponse[list[ServiceStatus]]:
	"""Retorna el estado de todos los servicios del sistema.

	Ejecuta health checks en vivo para Redis, Engram, TA ARCA,
	y Composio. Cacheado en Redis por 15 segundos.
	"""
	cache_key = 'system:services'
	cached = await _cache_get(request, cache_key)
	if cached:
		return UnifiedResponse(status='success', result=[ServiceStatus(**s) for s in json.loads(cached)])

	# API service is always healthy if this endpoint responds
	api_service = ServiceStatus(
		name='api',
		status='healthy',
		uptime='online',
		last_check=datetime.now(timezone.utc),
		version='1.0.0',
	)

	services = [api_service] + list(
		await asyncio.gather(
			_check_redis(request),
			_check_engram(),
			_check_ta(),
			_check_composio(),
		)
	)

	# Cache for 15s
	await _cache_set(
		request,
		cache_key,
		json.dumps([s.model_dump() for s in services]),
		ttl=15,
	)

	return UnifiedResponse(status='success', result=services)


@router.get(
	'/v1/system/activity',
	response_model=UnifiedResponse[list[ActivityEvent]],
	summary='Feed de actividad',
)
async def get_system_activity(
	request: Request,
	limit: int = Query(default=20, ge=1, le=200, description='Cantidad máxima de eventos'),
	offset: int = Query(default=0, ge=0, description='Desplazamiento para paginación'),
) -> UnifiedResponse[list[ActivityEvent]]:
	"""Retorna el feed de actividad reciente del sistema.

	Busca observaciones Engram de tipo ``pipeline_run`` y ``error``
	de todas las sesiones, ordenadas por fecha descendente.
	Cacheado en Redis por 10 segundos.
	"""
	cache_key = f'system:activity:{limit}:{offset}'
	cached = await _cache_get(request, cache_key)
	if cached:
		return UnifiedResponse(
			status='success',
			result=[ActivityEvent(**e) for e in json.loads(cached)],
		)

	memory: FiscalMemoryClient = get_memory()

	try:
		search_results = memory._engram_get(  # noqa: SLF001
			f'/search?q=pipeline_run error&project=fiscal-agent&limit={limit + offset}'
		)
		observations = (
			search_results
			if isinstance(search_results, list)
			else (search_results.get('results', []) if isinstance(search_results, dict) else [])
		)
	except Exception:
		observations = []

	# Sort by timestamp descending
	observations.sort(
		key=lambda o: (o.get('created_at') or o.get('timestamp') or '').replace('Z', '+00:00'),
		reverse=True,
	)

	# Paginate
	paginated = observations[offset : offset + limit]

	events = []
	for obs in paginated:
		content = obs.get('content', '')
		fields = {}
		for line in content.split('\n'):
			if '**:' in line:
				key_end = line.find('**:')
				key = line[:key_end].strip('* ')
				value = line[key_end + 3 :].strip()
				if key and value:
					fields[key.lower()] = value

		raw_type = obs.get('type', 'system')
		obs_type = raw_type if raw_type in ('pipeline_run', 'error', 'deployment', 'system') else 'system'
		ts_str = obs.get('created_at') or obs.get('timestamp') or ''
		try:
			ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00')) if ts_str else datetime.now(timezone.utc)
		except (ValueError, TypeError):
			ts = datetime.now(timezone.utc)

		events.append(
			ActivityEvent(
				id=str(obs.get('id', '')),
				type=obs_type,
				title=obs.get('title', ''),
				description=fields.get('error', ''),
				timestamp=ts,
				cuit=fields.get('cuit'),
				severity='error' if obs_type == 'error' else 'info',
			)
		)

	# Cache for 10s
	await _cache_set(
		request,
		cache_key,
		json.dumps([e.model_dump() for e in events]),
		ttl=10,
	)

	return UnifiedResponse(status='success', result=events)


@router.get(
	'/v1/system/errors',
	response_model=UnifiedResponse[list[ErrorEvent]],
	summary='Lista de errores',
)
async def get_system_errors(
	request: Request,
	severity: str | None = Query(default=None, description='Filtrar por severidad (error, warning, critical)'),
	service: str | None = Query(default=None, description='Filtrar por servicio (pipeline, browser)'),
	period: Literal['24h', '7d', '30d'] = Query(default='24h', description='Período'),
) -> UnifiedResponse[list[ErrorEvent]]:
	"""Retorna la lista de errores del sistema.

	Busca observaciones Engram de tipo ``error`` y las filtra por
	severidad, servicio y período. Cacheado en Redis por 30 segundos.
	"""
	cache_key = f'system:errors:{severity or "all"}:{service or "all"}:{period}'
	cached = await _cache_get(request, cache_key)
	if cached:
		return UnifiedResponse(
			status='success',
			result=[ErrorEvent(**e) for e in json.loads(cached)],
		)

	# Calculate period cutoff
	hours = {'24h': 24, '7d': 168, '30d': 720}[period]
	cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

	memory: FiscalMemoryClient = get_memory()

	try:
		search_results = memory._engram_get(  # noqa: SLF001
			f'/search?q=error&project=fiscal-agent&type=error&limit=200'
		)
		observations = (
			search_results
			if isinstance(search_results, list)
			else (search_results.get('results', []) if isinstance(search_results, dict) else [])
		)
	except Exception:
		observations = []

	error_events = []
	for obs in observations:
		content = obs.get('content', '')
		fields = {}
		for line in content.split('\n'):
			if '**:' in line:
				key_end = line.find('**:')
				key = line[:key_end].strip('* ')
				value = line[key_end + 3 :].strip()
				if key and value:
					fields[key.lower()] = value

		ts_str = obs.get('created_at') or obs.get('timestamp') or ''
		try:
			ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00')) if ts_str else datetime.now(timezone.utc)
		except (ValueError, TypeError):
			ts = datetime.now(timezone.utc)

		if ts < cutoff:
			continue

		sev = fields.get('severity', 'error')
		svc = fields.get('stage', 'pipeline')

		if severity and sev != severity:
			continue
		if service and svc != service:
			continue

		error_events.append(
			ErrorEvent(
				id=str(obs.get('id', '')),
				type=_map_error_type(fields.get('stage', 'Unknown')),
				message=fields.get('error', obs.get('title', '')),
				severity=sev,
				service=svc,
				cuit=fields.get('cuit'),
				timestamp=ts,
				count=1,
				trend='stable',
			)
		)

	# Cache for 30s
	await _cache_set(
		request,
		cache_key,
		json.dumps([e.model_dump() for e in error_events]),
		ttl=30,
	)

	return UnifiedResponse(status='success', result=error_events)
