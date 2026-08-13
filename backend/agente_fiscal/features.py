"""Feature-flag gateway for the fiscal integrations.

Each external integration runs behind an env-driven kill-switch so a disabled
integration returns a clean ``INTEGRATION_DISABLED`` failure instead of
crashing or touching the network:

  - ``arca``    → ``ARCA_ENABLED``    (arca_ws: WSAA SOAP + Padrón A5, external)
  - ``browser`` → ``BROWSER_ENABLED`` (ComposioBrowser cloud, external)
  - ``pdf``     → ``PDF_ENABLED``     (PdfGenerator, purely local, on by default)

Flags are read from the ``AppSettings`` singleton (``config.get_settings()``)
on every access. Callers that already hold a settings object (e.g. the worker,
which reads ``get_settings()`` for credentials) can pass it explicitly so tests
flip flags via the existing ``get_settings`` monkeypatch seam without global
mutation.
"""

from __future__ import annotations

from agente_fiscal.config import get_settings

#: Integration name → ``AppSettings`` field holding its enable flag.
_FLAG_ATTRS: dict[str, str] = {
	'arca': 'arca_enabled',
	'browser': 'browser_enabled',
	'pdf': 'pdf_enabled',
}

_MESSAGES: dict[str, str] = {
	'arca': 'La integración ARCA está deshabilitada. Activá ARCA_ENABLED=true para habilitarla',
	'browser': 'La integración de browser (Composio) está deshabilitada. Activá BROWSER_ENABLED=true para habilitarla',
	'pdf': 'La generación de PDF está deshabilitada. Activá PDF_ENABLED=true para habilitarla',
}


class IntegrationDisabledError(RuntimeError):
	"""Typed failure raised when a disabled integration is requested.

	Carries the integration name (``arca``, ``browser``, ``pdf``) so callers
	can surface ``INTEGRATION_DISABLED`` with a precise cause.
	"""

	def __init__(self, integration: str) -> None:
		if integration not in _MESSAGES:
			raise ValueError(f'Unknown integration: {integration!r}')
		self.integration = integration
		super().__init__(_MESSAGES[integration])


def _settings_or_default(settings=None):
	"""Return ``settings`` or the shared ``AppSettings`` singleton."""
	if settings is None:
		return get_settings()
	return settings


def integration_enabled(name: str, settings=None) -> bool:
	"""Return whether ``name`` is enabled, from ``settings`` or the singleton.

	Unknown integration names raise ``ValueError``.
	"""
	if name not in _FLAG_ATTRS:
		raise ValueError(f'Unknown integration: {name!r}')
	return bool(getattr(_settings_or_default(settings), _FLAG_ATTRS[name], False))


def require_integration(name: str, settings=None) -> None:
	"""Raise ``IntegrationDisabledError`` when ``name`` is disabled."""
	if not integration_enabled(name, settings):
		raise IntegrationDisabledError(name)


def arca_enabled() -> bool:
	"""Shortcut for ``integration_enabled('arca')``."""
	return integration_enabled('arca')


def browser_enabled() -> bool:
	"""Shortcut for ``integration_enabled('browser')``."""
	return integration_enabled('browser')


def pdf_enabled() -> bool:
	"""Shortcut for ``integration_enabled('pdf')``."""
	return integration_enabled('pdf')


def effective_flags() -> dict[str, bool]:
	"""Return the current effective flags as ``{name_enabled: bool}``."""
	settings = get_settings()
	return {
		f'{name}_enabled': bool(getattr(settings, attr, False))
		for name, attr in _FLAG_ATTRS.items()
	}
