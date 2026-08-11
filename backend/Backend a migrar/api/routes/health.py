"""GET /v1/health — health check extendido del sistema.

Chequea Redis, Engram, TA ARCA, y Composio, retornando un
``SystemHealth`` con el estado global y el detalle por servicio.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Request

from fiscal_agent.api.deps import get_ta
from fiscal_agent.config import get_settings
from fiscal_agent.memory.config import MemoryConfig
from fiscal_agent.models import ApiError, ServiceStatus, SystemHealth, UnifiedResponse

router = APIRouter()


async def _check_redis(request: Request) -> ServiceStatus:
	"""Checkear Redis mediante ``ping()``. Mide latencia."""
	start = time.monotonic()
	try:
		redis = request.app.state.redis
		await redis.ping()
		latency = (time.monotonic() - start) * 1000
		return ServiceStatus(
			name='redis',
			status='healthy',
			last_check=datetime.now(timezone.utc),
			latency_ms=round(latency, 2),
		)
	except Exception as exc:
		latency = (time.monotonic() - start) * 1000
		return ServiceStatus(
			name='redis',
			status='down',
			last_check=datetime.now(timezone.utc),
			latency_ms=round(latency, 2),
			error=str(exc),
		)


async def _check_engram() -> ServiceStatus:
	"""Checkear Engram via GET /health a su URL."""
	mem_config = MemoryConfig()
	start = time.monotonic()
	try:
		resp = await httpx.AsyncClient().get(
			f'{mem_config.engram_url}/health',
			timeout=mem_config.engram_timeout,
		)
		latency = (time.monotonic() - start) * 1000
		if resp.is_success:
			body = resp.json()
			version = body.get('version') if isinstance(body, dict) else None
			return ServiceStatus(
				name='engram',
				status='healthy',
				last_check=datetime.now(timezone.utc),
				latency_ms=round(latency, 2),
				version=str(version) if version else None,
			)
		return ServiceStatus(
			name='engram',
			status='down',
			last_check=datetime.now(timezone.utc),
			latency_ms=round(latency, 2),
			error=f'HTTP {resp.status_code}',
		)
	except Exception as exc:
		latency = (time.monotonic() - start) * 1000
		return ServiceStatus(
			name='engram',
			status='down',
			last_check=datetime.now(timezone.utc),
			latency_ms=round(latency, 2),
			error=str(exc),
		)


async def _check_ta() -> ServiceStatus:
	"""Checkear TA ARCA: certificado presente y token no expirado."""
	from fiscal_agent.api.deps import CERT_PATH, KEY_PATH

	start = time.monotonic()
	certs_ok = CERT_PATH.exists() and KEY_PATH.exists()
	if not certs_ok:
		latency = (time.monotonic() - start) * 1000
		return ServiceStatus(
			name='ta',
			status='down',
			last_check=datetime.now(timezone.utc),
			latency_ms=round(latency, 2),
			error='Certificados ARCA no encontrados',
		)

	token, _ = get_ta()
	latency = (time.monotonic() - start) * 1000
	if token:
		return ServiceStatus(
			name='ta',
			status='healthy',
			last_check=datetime.now(timezone.utc),
			latency_ms=round(latency, 2),
		)
	return ServiceStatus(
		name='ta',
		status='down',
		last_check=datetime.now(timezone.utc),
		latency_ms=round(latency, 2),
		error='Ticket de Acceso no disponible o expirado',
	)


async def _check_composio() -> ServiceStatus:
	"""Checkear Composio: API key presente en settings."""
	start = time.monotonic()
	settings = get_settings()
	api_key = settings.credentials.composio_api_key
	latency = (time.monotonic() - start) * 1000
	if api_key:
		return ServiceStatus(
			name='composio',
			status='healthy',
			last_check=datetime.now(timezone.utc),
			latency_ms=round(latency, 2),
			version='configured',
		)
	return ServiceStatus(
		name='composio',
		status='down',
		last_check=datetime.now(timezone.utc),
		latency_ms=round(latency, 2),
		error='COMPOSIO_API_KEY no configurada',
	)


@router.get(
	'/v1/health',
	response_model=UnifiedResponse[SystemHealth],
	summary='Health check del sistema',
	responses={
		401: {'description': 'API key faltante o inválida', 'model': UnifiedResponse[ApiError]},
		403: {'description': 'Scope insuficiente o key inactiva', 'model': UnifiedResponse[ApiError]},
		429: {'description': 'Límite de tasa excedido', 'model': UnifiedResponse[ApiError]},
	},
)
async def health(request: Request) -> UnifiedResponse[SystemHealth]:
	"""Health check extendido del agente fiscal.

	Chequea Redis, Engram, TA ARCA (certificado + token vigente),
	y Composio (API key configurada). Retorna el estado global:
	- ``healthy``: todos los servicios OK
	- ``degraded``: 1-2 servicios caídos
	- ``down``: todo malo
	"""
	services = await asyncio.gather(
		_check_redis(request),
		_check_engram(),
		_check_ta(),
		_check_composio(),
	)

	healthy_count = sum(1 for s in services if s.status == 'healthy')
	total = len(services)
	if healthy_count == total:
		global_status = 'healthy'
	elif healthy_count >= total - 2:
		global_status = 'degraded'
	else:
		global_status = 'down'

	return UnifiedResponse(
		status='success',
		result=SystemHealth(
			status=global_status,
			services=services,
			timestamp=datetime.now(timezone.utc),
		),
	)
