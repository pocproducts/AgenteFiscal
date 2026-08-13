"""Agente Fiscal FastAPI server.

Run with::

	uv run uvicorn agente_fiscal.api.server:app --reload
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from agente_fiscal.adapters.db_api_keys import PostgresApiKeyPort
from agente_fiscal.adapters.db_clients import PostgresClientRepository
from agente_fiscal.api.middleware import (
	AuthMiddleware,
	RateLimitMiddleware,
	RequestMetricsMiddleware,
	RequestMetricsStore,
	TenantContextMiddleware,
)
from agente_fiscal.api.routes import (
	admin,
	calendar,
	chat,
	clients,
	conversations,
	extract,
	health,
	memory,
	monitor,
	report,
	report_runs,
)
from agente_fiscal.api.store import RedisStore
from agente_fiscal.config import get_settings
from agente_fiscal.db.session import async_session_factory, engine
from agente_fiscal.domain.models import ApiError, UnifiedResponse
from agente_fiscal.worker.runner import start_worker

logger = logging.getLogger(__name__)

#: How often the background task re-attempts Redis when boot was degraded.
_REDIS_RECONNECT_INTERVAL = 30


async def _redis_reconnect_loop(settings, app: FastAPI) -> None:
	"""Retry connecting Redis every ``_REDIS_RECONNECT_INTERVAL`` seconds.

	Spawned only when the initial (boot) connection failed. ``redis.from_url``
	is lazy — it does NOT open a socket — so connectivity is always verified
	with an explicit ``ping()``. Each attempt is wrapped so a failure never
	propagates and kills the lifespan; the loop only exits on success or
	cancellation.
	"""
	while True:
		client: redis.Redis | None = None
		try:
			client = redis.from_url(settings.redis.url, decode_responses=True)
			await client.ping()
			store = RedisStore(client)
			app.state.redis = client
			app.state.store = store
			logger.warning('Redis reconectado — rate limiting y conversaciones activos')
			return
		except asyncio.CancelledError:
			raise
		except Exception as exc:
			if client is not None:
				try:
					await client.aclose()
				except Exception:
					pass
			logger.warning(
				'Reintento de Redis falló (%s) — reintentando en %ss',
				exc,
				_REDIS_RECONNECT_INTERVAL,
			)
			await asyncio.sleep(_REDIS_RECONNECT_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
	"""Connect Redis (degraded-tolerant, auto-reconnecting) + Postgres engine.

	Redis absence no longer blocks the app: boot degrades gracefully (auth keeps
	working via Postgres/Clerk, rate limiting becomes pass-through, caches stay
	empty) while a background task re-attempts the connection every 30s. When
	Redis comes back the task swaps in a live client/store — no restart needed.

	``redis.from_url`` is lazy, so the initial attempt verifies the connection
	with an explicit ``ping()`` before declaring success.
	"""
	settings = get_settings()

	redis_client: redis.Redis | None = None
	redis_connected = False
	try:
		redis_client = redis.from_url(settings.redis.url, decode_responses=True)
		await redis_client.ping()
		store = RedisStore(redis_client)
		app.state.redis = redis_client
		app.state.store = store
		redis_connected = True

		# NOTE (cutover Phase 5): Redis no longer holds business data (plans,
		# developers, apps, API keys, tenants, clients) — the source of truth
		# is Postgres. Redis keeps rate limiting + best-effort conversations.
		# ``RedisStore.seed_defaults()`` is archived.
	except Exception as exc:
		logger.warning('Redis init falló — arrancando degradado: %s', exc)
		if redis_client is not None:
			try:
				await redis_client.aclose()
			except Exception:
				pass
		app.state.redis = None
		app.state.store = None

	# Postgres (Fase 1) — lazy async engine, no eager connect.
	app.state.engine = engine
	app.state.session_factory = async_session_factory

	# Cutover Phase 5 — API key resolution/admin CRUD and client (CUIT) CRUD
	# go through the hexagonal ports (Postgres), never Redis.
	app.state.api_key_port = PostgresApiKeyPort(async_session_factory)
	app.state.client_repository = PostgresClientRepository(async_session_factory)

	# Fase 3 — in-process worker: polls queued report_runs and executes the
	# heavy pipeline in the background. Starts before serving, stops on shutdown.
	reconnect_task: asyncio.Task | None = None
	if not redis_connected:
		reconnect_task = asyncio.create_task(_redis_reconnect_loop(settings, app))

	async with start_worker(app):
		yield

	# Clean shutdown
	if reconnect_task is not None:
		reconnect_task.cancel()
		try:
			await reconnect_task
		except asyncio.CancelledError:
			pass
	active_client = getattr(app.state, 'redis', None)
	if active_client is not None:
		await active_client.aclose()
	await engine.dispose()


app = FastAPI(
	title='Agente Fiscal API',
	version='2.0.0',
	lifespan=lifespan,
	description='Agente Fiscal — API REST para agentes e integraciones',
)


# ── Global HTTP exception handler ───────────────────────────────────────


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
	"""Wrap all HTTP exceptions in UnifiedResponse format."""
	return JSONResponse(
		status_code=exc.status_code,
		content=exc.detail
		if isinstance(exc.detail, dict)
		else UnifiedResponse(
			status='error',
			error={'code': 'HTTP_ERROR', 'cause': str(exc.detail)},
		).model_dump(),
	)


# ── Metrics middleware (before rate limiter) ────────────────────────────


_metrics_store = None


def get_metrics_store() -> RequestMetricsStore:
	"""Return the singleton metrics store instance."""
	global _metrics_store
	if _metrics_store is None:
		_metrics_store = RequestMetricsStore()
	return _metrics_store


app.add_middleware(RequestMetricsMiddleware, store=get_metrics_store())

# ── Tenant context (after metrics, before auth) ─────────────────────────
# TenantContext needs request.state.api_key set by AuthMiddleware,
# which runs AFTER (outer to) this middleware.

app.add_middleware(TenantContextMiddleware)

# ── Auth middleware (after tenant, before rate-limit/CORS/routes) ────────

app.add_middleware(AuthMiddleware)

# ── Rate limiter (after auth + tenant, before routes) ───────────────────

app.add_middleware(RateLimitMiddleware)

# ── CORS — outermost, so even 401/403 from outer middleware get CORS headers ──

app.add_middleware(
	CORSMiddleware,
	allow_origins=get_settings().cors_origins,
	allow_credentials=True,
	allow_methods=['*'],
	allow_headers=['*'],
)


# ── OpenAPI custom schema ──────────────────────────────────────────────


def custom_openapi() -> dict:
	if app.openapi_schema:
		return app.openapi_schema

	openapi_schema = get_openapi(
		title='Agente Fiscal API',
		version='2.0.0',
		description='Agente Fiscal — API REST para agentes e integraciones',
		routes=app.routes,
	)

	# Contacto
	openapi_schema['info']['contact'] = {
		'name': 'Agente Fiscal Team',
		'url': 'https://agente-fiscal.ar',
		'email': 'dev@agente-fiscal.ar',
	}

	# Servidores
	openapi_schema['servers'] = [
		{'url': 'http://localhost:8000', 'description': 'Desarrollo local'},
		{'url': 'https://api.agente-fiscal.ar', 'description': 'Producción'},
	]

	# Sin esquemas de seguridad por ahora (migración de auth)
	openapi_schema['security'] = []

	# Tags con descripciones
	openapi_schema['tags'] = [
		{
			'name': 'health',
			'description': 'Endpoints de monitoreo y health check',
		},
		{
			'name': 'calendar',
			'description': 'Generación de calendarios fiscales por CUIT y período',
		},
		{
			'name': 'report',
			'description': 'Reportes fiscales completos e información de contribuyentes',
		},
		{
			'name': 'extract',
			'description': 'Extracción automatizada de datos vía navegador (Composio)',
		},
		{
			'name': 'admin',
			'description': 'Autogestión de desarrolladores, aplicaciones y API keys',
		},
		{
			'name': 'clients',
			'description': 'CRUD de clientes (CUIT) del tenant autenticado',
		},
		{
			'name': 'memory',
			'description': 'Memoria fiscal — observaciones de pipeline por CUIT',
		},
		{
			'name': 'system',
			'description': 'Monitoreo y métricas del sistema',
		},
		{
			'name': 'chat',
			'description': 'Asistente de chat en lenguaje natural para consultas fiscales',
		},
	]

	app.openapi_schema = openapi_schema
	return app.openapi_schema


app.openapi = custom_openapi


# ── Routers ─────────────────────────────────────────────────────────────

app.include_router(health.router, tags=['health'])
app.include_router(calendar.router, tags=['calendar'])
app.include_router(report.router, tags=['report'])
app.include_router(report_runs.router, tags=['report'])
app.include_router(extract.router, tags=['extract'])
app.include_router(memory.router, tags=['memory'])
app.include_router(admin.router, tags=['admin'])
app.include_router(clients.router, tags=['clients'])
app.include_router(monitor.router, tags=['system'])
app.include_router(chat.router, tags=['chat'])
app.include_router(conversations.router)
