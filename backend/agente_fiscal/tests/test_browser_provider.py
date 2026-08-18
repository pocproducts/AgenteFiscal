"""Tests for the browser provider registry/factory (hexagonal plug-in).

Covers:
  - default provider is composio (with creds) and satisfies ``BrowserPort``
  - mock provider resolves offline and returns a deterministic DeudaOutput
  - disabled integration → ``None`` (never raises)
  - missing composio creds → ``None`` (never raises)
  - unknown provider name raises ``ValueError`` only when the feature is used
  - the ``PROVIDERS`` registry is extensible by registering new names
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from agente_fiscal.adapters.browser.composio import ComposioBrowser
from agente_fiscal.adapters.browser.mock import MOCK_LIVE_URL, MockBrowser
from agente_fiscal.adapters.browser.provider import ALLOWED_PROVIDERS, PROVIDERS, build_browser_provider
from agente_fiscal.domain.models import DeudaOutput
from agente_fiscal.ports.browser import BrowserPort


def _settings(provider: str = 'composio', *, enabled: bool = True, api_key: str = 'key', clave: str = 'clave') -> SimpleNamespace:
	return SimpleNamespace(
		browser_enabled=enabled,
		browser_provider=provider,
		credentials=SimpleNamespace(composio_api_key=api_key, clave_fiscal=clave),
	)


# ── Default provider (composio) ────────────────────────────────────────────


def test_default_provider_is_composio_with_creds() -> None:
	provider = build_browser_provider(_settings(provider='composio'))
	assert isinstance(provider, ComposioBrowser)
	assert isinstance(provider, BrowserPort)


def test_default_browser_provider_name_allowed() -> None:
	assert 'composio' in ALLOWED_PROVIDERS
	assert 'browserbase' in ALLOWED_PROVIDERS
	assert 'mock' in ALLOWED_PROVIDERS


# ── Mock provider (offline, deterministic) ─────────────────────────────────


def test_mock_provider_returns_deuda_output() -> None:
	provider = build_browser_provider(_settings(provider='mock', api_key='', clave=''))
	assert isinstance(provider, MockBrowser)

	out = provider.run_single(None)
	assert isinstance(out, DeudaOutput)
	assert out.error is None
	assert out.live_url == MOCK_LIVE_URL


def test_mock_provider_run_single_with_client_and_tasks() -> None:
	from agente_fiscal.domain.models import ClientConfig

	provider = build_browser_provider(_settings(provider='mock', api_key='', clave=''))
	cliente = ClientConfig(cuit='20301234561')
	out = provider.run_single(cliente, tasks=[object()])
	assert out.cuit == cliente.cuit
	assert out.error is None
	assert out.live_url == MOCK_LIVE_URL


# ── Disabled integration / missing creds → None (never raises) ─────────────


def test_disabled_flag_returns_none() -> None:
	assert build_browser_provider(_settings(enabled=False)) is None


def test_missing_composio_creds_returns_none() -> None:
	assert build_browser_provider(_settings(provider='composio', api_key='', clave='')) is None
	assert build_browser_provider(_settings(provider='composio', api_key='key', clave='')) is None


# ── Unknown provider name ──────────────────────────────────────────────────


def test_unknown_provider_raises_valueerror_when_active() -> None:
	with pytest.raises(ValueError, match='bogus'):
		build_browser_provider(_settings(provider='bogus'))


def test_unknown_provider_disabled_returns_none() -> None:
	"""Unknown name must NOT raise when the feature is disabled (short-circuit)."""
	assert build_browser_provider(_settings(provider='bogus', enabled=False)) is None


# ── Registry extensibility ─────────────────────────────────────────────────


def test_registry_is_extensible() -> None:
	class FakeProvider:
		def run_single(self, cliente=None, tasks=None, echo_func=None, on_live_url=None, on_step=None) -> DeudaOutput:
			return DeudaOutput(cuit='00000000000', extraido_el=datetime.utcnow(), live_url='https://fake.example')

		def run_all(self, clientes) -> list[DeudaOutput]:
			return []

		async def close(self) -> None:
			return None

	def _build_fake(settings, *, headed: bool = False):
		return FakeProvider()

	PROVIDERS['fake'] = _build_fake
	try:
		provider = build_browser_provider(_settings(provider='fake'))
		assert isinstance(provider, FakeProvider)
		assert isinstance(provider, BrowserPort)
	finally:
		PROVIDERS.pop('fake', None)