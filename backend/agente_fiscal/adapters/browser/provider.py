"""Browser provider registry + factory (hexagonal plug-in structure).

The extraction layer consumes ``BrowserPort`` (``ports/browser.py``). Concrete
providers implement that port and are selected by name via ``BROWSER_PROVIDER``
env (``AppSettings.browser_provider``):

    - ``composio``    → ``ComposioBrowser`` (Composio cloud REST API)
    - ``browserbase`` → ``BrowserbaseBrowser`` (Browserbase Agents API)
    - ``mock``        → ``MockBrowser`` (deterministic local fixtures, no cloud)

New providers plug in by registering a ``{name: builder}`` entry in
``PROVIDERS`` — no metaclass, no plugin system.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from agente_fiscal import config as config_module
from agente_fiscal.adapters.browser.browserbase import BrowserbaseBrowser
from agente_fiscal.adapters.browser.composio import ComposioBrowser
from agente_fiscal.adapters.browser.mock import MockBrowser
from agente_fiscal.config import REPRESENTANTE_CUIT
from agente_fiscal.ports.browser import BrowserPort

logger = logging.getLogger(__name__)


def _build_composio(
	settings, *, headed: bool = False, session_store: Optional[object] = None, binding: Optional[object] = None
) -> Optional[BrowserPort]:
	"""Construct ComposioBrowser from settings, or ``None`` when creds are missing.

	``session_store``/``binding`` se ignoran: el reuso de contexto es solo de
	Browserbase (firma uniforme para el registry).
	"""
	creds = settings.credentials
	if not creds.composio_api_key or not creds.clave_fiscal:
		logger.debug('Composio provider skipped: falta COMPOSIO_API_KEY o ESTUDIO_CLAVE_FISCAL')
		return None
	return ComposioBrowser(
		composio_api_key=creds.composio_api_key,
		estudio_cuit=REPRESENTANTE_CUIT,
		estudio_clave=creds.clave_fiscal,
		headed=headed,
		tenant=None,
		default_max_retries=None,
	)


def _build_browserbase(
	settings, *, headed: bool = False, session_store: Optional[object] = None, binding: Optional[object] = None
) -> Optional[BrowserPort]:
	"""Construct BrowserbaseBrowser from settings, or ``None`` when the key is missing.

	``session_store`` (repositorio de sesiones persistidas) y ``binding``
	(sesión ya adquirida) solo se propagan cuando existen.
	"""
	creds = settings.credentials
	if not getattr(creds, 'browserbase_api_key', ''):
		logger.debug('Browserbase provider skipped: falta BROWSERBASE_API_KEY')
		return None
	return BrowserbaseBrowser(
		api_key=creds.browserbase_api_key,
		project_id=getattr(creds, 'browserbase_project_id', None) or None,
		headed=headed,
		session_store=session_store,
		binding=binding,
	)


def _build_mock(
	settings, *, headed: bool = False, session_store: Optional[object] = None, binding: Optional[object] = None
) -> BrowserPort:
	"""Construct MockBrowser — deterministic local testing, no cloud creds needed."""
	return MockBrowser()


#: Provider name → builder. Future providers register here (e.g. Browserbase).
PROVIDERS: dict[str, Callable[..., Optional[BrowserPort]]] = {
	'composio': _build_composio,
	'browserbase': _build_browserbase,
	'mock': _build_mock,
}

#: Allowed names, derived from the registry so the error stays in sync.
ALLOWED_PROVIDERS = frozenset(PROVIDERS)


def build_browser_provider(
	settings: Optional[object] = None,
	*,
	headed: bool = False,
	session_store: Optional[object] = None,
	binding: Optional[object] = None,
) -> Optional[BrowserPort]:
	"""Resolve and build the env-selected browser provider, or ``None``.

	Returns ``None`` (never raises) when the browser integration is disabled
	(``settings.browser_enabled`` False) or the selected provider's credentials
	are missing. Raises ``ValueError`` for an unknown provider name only when
	the feature would otherwise be used (integration enabled) — a disabled
	integration short-circuits to ``None`` regardless of the provider name.

	``session_store``/``binding`` (reuso de sesión persistida de Browserbase)
	se propagan al builder solo cuando existen — callers que no los pasan
	siguen funcionando igual.
	"""
	if settings is None:
		# Resolve via the module attribute so tests that monkeypatch
		# ``agente_fiscal.config.get_settings`` (the established seam) take effect.
		settings = config_module.get_settings()

	if not getattr(settings, 'browser_enabled', False):
		return None

	name = getattr(settings, 'browser_provider', 'composio')
	builder = PROVIDERS.get(name)
	if builder is None:
		raise ValueError(f'Unknown browser provider: {name!r}. Allowed: {sorted(ALLOWED_PROVIDERS)}')

	extra: dict[str, object] = {}
	if session_store is not None:
		extra['session_store'] = session_store
	if binding is not None:
		extra['binding'] = binding
	return builder(settings, headed=headed, **extra)
