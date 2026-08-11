"""Fiscal Agent FastAPI server.

Run with::

	uv run uvicorn fiscal_agent.api.server:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from fiscal_agent.api.middleware import (
	AuthMiddleware,
	RateLimitMiddleware,
	RequestMetricsMiddleware,
	RequestMetricsStore,
	TenantContextMiddleware,
)
from fiscal_agent.api.routes import admin, calendar, chat, conversations, extract, health, memory, monitor, report
from fiscal_agent.api.store import RedisStore, TenantStore
from fiscal_agent.config import get_settings
from fiscal_agent.models import ApiError, UnifiedResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
	"""Connect Redis, seed defaults on empty store, close on shutdown."""
	settings = get_settings()
	redis_client = redis.from_url(settings.redis.url, decode_responses=True)
	store = RedisStore(redis_client)
	tenant_store = TenantStore(redis_client)
	app.state.redis = redis_client
	app.state.store = store
	app.state.tenant_store = tenant_store

	# Seed if empty
	await store.seed_defaults()
	await tenant_store.seed_defaults()

	yield  # Server is now serving

	# Clean shutdown
	await redis_client.aclose()


app = FastAPI(
	title='Fiscal Agent API',
	version='2.0.0',
	lifespan=lifespan,
	description='Vertical AI Agent Fiscal — API REST para agentes e integraciones',
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
		title='Fiscal Agent API',
		version='2.0.0',
		description='Vertical AI Agent Fiscal — API REST para agentes e integraciones',
		routes=app.routes,
	)

	# Contacto
	openapi_schema['info']['contact'] = {
		'name': 'Fiscal Agent Team',
		'url': 'https://fiscal-agent.ar',
		'email': 'dev@fiscal-agent.ar',
	}

	# Servidores
	openapi_schema['servers'] = [
		{'url': 'http://localhost:8000', 'description': 'Desarrollo local'},
		{'url': 'https://api.fiscal-agent.ar', 'description': 'Producción'},
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
app.include_router(extract.router, tags=['extract'])
app.include_router(memory.router, tags=['memory'])
app.include_router(admin.router, tags=['admin'])
app.include_router(monitor.router, tags=['system'])
app.include_router(chat.router, tags=['chat'])
app.include_router(conversations.router)
