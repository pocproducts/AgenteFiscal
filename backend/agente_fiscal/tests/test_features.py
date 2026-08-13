"""Tests for the integration feature flags (kill-switches).

Covers:
  - default values and env parsing of ``ARCA_ENABLED`` / ``BROWSER_ENABLED`` /
    ``PDF_ENABLED`` in ``AppSettings``
  - the ``agente_fiscal.features`` API (``integration_enabled``,
    ``require_integration``, ``IntegrationDisabledError``, ``effective_flags``)
  - the guarded PDF generator returned by ``get_pdf_gen()`` while disabled
  - HTTP behavior: ``POST /v1/extract`` → 503 ``INTEGRATION_DISABLED``,
    ``v1/system/features`` reporting the three flags, and the health TA /
    Composio checks reporting *disabled* instead of an error.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from agente_fiscal.api.deps import _DisabledPdfGenerator, get_pdf_gen
from agente_fiscal.api.routes.extract import router as extract_router
from agente_fiscal.api.routes.monitor import router as monitor_router
from agente_fiscal.api.routes.health import _check_composio, _check_ta
from agente_fiscal.config import AppSettings
from agente_fiscal.domain.models import UnifiedResponse
from agente_fiscal.features import (
	IntegrationDisabledError,
	effective_flags,
	integration_enabled,
	require_integration,
)


# ── Config: defaults + env parsing ─────────────────────────────────────────


def test_feature_flags_default_values() -> None:
	settings = AppSettings()
	assert settings.arca_enabled is False
	assert settings.browser_enabled is False
	assert settings.pdf_enabled is True


def test_feature_flags_parse_env(monkeypatch) -> None:
	monkeypatch.setenv('ARCA_ENABLED', 'true')
	monkeypatch.setenv('BROWSER_ENABLED', '1')
	monkeypatch.setenv('PDF_ENABLED', 'false')
	settings = AppSettings()
	assert settings.arca_enabled is True
	assert settings.browser_enabled is True
	assert settings.pdf_enabled is False


# ── Config: CERT_DIR cert path resolution ───────────────────────────────────


def test_cert_dir_default_value() -> None:
	assert AppSettings().cert_dir == '.certificados-arca'


def test_resolve_cert_paths_explicit_override() -> None:
	from agente_fiscal.config import resolve_cert_paths

	cert_dir, cert_path, key_path = resolve_cert_paths('/tmp/custom-certs')
	assert cert_dir == Path('/tmp/custom-certs')
	assert cert_path == Path('/tmp/custom-certs/produccion.crt')
	assert key_path == Path('/tmp/custom-certs/produccion.key')


def test_resolve_cert_paths_honors_cert_dir_env(monkeypatch) -> None:
	"""The (previously dead) ``CERT_DIR`` env key now drives cert paths."""
	from agente_fiscal.config import get_settings, resolve_cert_paths

	get_settings.cache_clear()
	monkeypatch.setenv('CERT_DIR', '.certs-staging')
	try:
		assert get_settings().cert_dir == '.certs-staging'
		cert_dir, cert_path, key_path = resolve_cert_paths()
		assert cert_dir == Path('.certs-staging')
		assert cert_path == Path('.certs-staging/produccion.crt')
		assert key_path == Path('.certs-staging/produccion.key')
	finally:
		get_settings.cache_clear()
		monkeypatch.delenv('CERT_DIR', raising=False)


# ── features module ────────────────────────────────────────────────────────


class _FakeSettings:
	"""Stand-in settings exposing only the flag attributes."""

	def __init__(self, *, arca=False, browser=False, pdf=True) -> None:
		self.arca_enabled = arca
		self.browser_enabled = browser
		self.pdf_enabled = pdf


@pytest.mark.parametrize(
	('name', 'settings', 'expected'),
	[
		('arca', _FakeSettings(arca=True), True),
		('arca', _FakeSettings(arca=False), False),
		('browser', _FakeSettings(browser=True), True),
		('browser', _FakeSettings(browser=False), False),
		('pdf', _FakeSettings(pdf=True), True),
		('pdf', _FakeSettings(pdf=False), False),
	],
)
def test_integration_enabled_with_explicit_settings(name, settings, expected) -> None:
	assert integration_enabled(name, settings) is expected


def test_integration_enabled_unknown_name_raises() -> None:
	with pytest.raises(ValueError):
		integration_enabled('googledrive')


def test_require_integration_disabled_raises() -> None:
	with pytest.raises(IntegrationDisabledError) as exc_info:
		require_integration('arca', _FakeSettings(arca=False))
	assert exc_info.value.integration == 'arca'
	assert 'deshabilitada' in str(exc_info.value)


def test_require_integration_enabled_passes() -> None:
	require_integration('arca', _FakeSettings(arca=True))


def test_require_integration_unknown_name_raises() -> None:
	with pytest.raises(ValueError):
		require_integration('wat', _FakeSettings())


def test_effective_flags_shape(monkeypatch) -> None:
	monkeypatch.setattr(
		'agente_fiscal.features.get_settings',
		lambda: _FakeSettings(arca=False, browser=False, pdf=True),
	)
	flags = effective_flags()
	assert flags == {'arca_enabled': False, 'browser_enabled': False, 'pdf_enabled': True}


# ── get_pdf_gen guarded instance ───────────────────────────────────────────


def test_disabled_pdf_generator_raises_on_use() -> None:
	gen = _DisabledPdfGenerator()
	with pytest.raises(IntegrationDisabledError):
		gen.generar('nombre', 'cuit', [], 1, 2026)


def test_get_pdf_gen_disabled_returns_guard(monkeypatch) -> None:
	monkeypatch.setattr('agente_fiscal.api.deps.pdf_enabled', lambda: False)
	monkeypatch.setattr('agente_fiscal.api.deps._pdf_gen', None)
	gen = get_pdf_gen()
	assert isinstance(gen, _DisabledPdfGenerator)
	with pytest.raises(IntegrationDisabledError):
		gen.generar('nombre', 'cuit', [], 1, 2026)


def test_get_pdf_gen_enabled_returns_real(monkeypatch) -> None:
	from agente_fiscal.adapters.pdf_generator import PdfGenerator

	monkeypatch.setattr('agente_fiscal.api.deps.pdf_enabled', lambda: True)
	monkeypatch.setattr('agente_fiscal.api.deps._pdf_gen', None)
	assert isinstance(get_pdf_gen(), PdfGenerator)


# ── HTTP level: extract + system/features ──────────────────────────────────


def _build_app(routers: list) -> FastAPI:
	"""Minimal FastAPI app with the UnifiedResponse HTTPException handler."""
	app = FastAPI()

	@app.exception_handler(HTTPException)
	async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
		detail = exc.detail
		return JSONResponse(
			status_code=exc.status_code,
			content=detail
			if isinstance(detail, dict)
			else UnifiedResponse(
				status='error',
				error={'code': 'HTTP_ERROR', 'cause': str(detail)},
			).model_dump(),
		)

	for router in routers:
		app.include_router(router)
	return app


async def test_extract_503_when_browser_disabled(monkeypatch) -> None:
	app = _build_app([extract_router])
	monkeypatch.setattr('agente_fiscal.features.get_settings', lambda: _FakeSettings(browser=False))

	transport = ASGITransport(app=app)
	async with AsyncClient(transport=transport, base_url='http://test') as client:
		resp = await client.post(
			'/v1/extract',
			json={'cuit': '20000000001', 'tasks': ['deuda']},
		)
	assert resp.status_code == 503
	body = resp.json()
	assert body['error']['code'] == 'INTEGRATION_DISABLED'
	assert 'browser' in body['error']['cause'].lower()


async def test_system_features_endpoint(monkeypatch) -> None:
	app = _build_app([monitor_router])
	monkeypatch.setattr(
		'agente_fiscal.features.get_settings',
		lambda: _FakeSettings(arca=False, browser=False, pdf=True),
	)

	transport = ASGITransport(app=app)
	async with AsyncClient(transport=transport, base_url='http://test') as client:
		resp = await client.get('/v1/system/features')
	assert resp.status_code == 200
	body = resp.json()
	assert body['result'] == {'arca_enabled': False, 'browser_enabled': False, 'pdf_enabled': True}


# ── Health checks report disabled instead of erroring ──────────────────────


async def test_health_check_ta_disabled(monkeypatch) -> None:
	monkeypatch.setattr('agente_fiscal.features.get_settings', lambda: _FakeSettings(arca=False))
	status = await _check_ta()
	assert status.name == 'ta'
	assert status.status == 'healthy'
	assert status.version == 'disabled'
	assert 'deshabilitada' in status.error


async def test_health_check_composio_disabled(monkeypatch) -> None:
	monkeypatch.setattr('agente_fiscal.features.get_settings', lambda: _FakeSettings(browser=False))
	status = await _check_composio()
	assert status.name == 'composio'
	assert status.status == 'healthy'
	assert status.version == 'disabled'
	assert 'deshabilitada' in status.error