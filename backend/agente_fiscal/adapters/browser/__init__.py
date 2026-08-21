"""Browser automation layer for ARCA extraction.

Providers implement the ``BrowserPort`` contract (``ports/browser.py``) and
are resolved by name through ``build_browser_provider`` (``BROWSER_PROVIDER``
env, default ``composio``):

    - ``composio``    → ComposioBrowser: Composio Browser Tool, instrucciones NL
      en lugar de Playwright + YAML (cloud REST API).
    - ``browserbase`` → BrowserbaseBrowser: Browserbase Agents API (runs + live
      session URL), segundo provider real.
    - ``mock``        → MockBrowser: deterministic local fixtures, sin cloud
      (test/demo only).
"""

from agente_fiscal.adapters.browser.browserbase import BrowserbaseBrowser
from agente_fiscal.adapters.browser.composio import ComposioBrowser
from agente_fiscal.adapters.browser.factory import build_browser_tasks
from agente_fiscal.adapters.browser.mock import MockBrowser
from agente_fiscal.adapters.browser.provider import PROVIDERS, build_browser_provider
from agente_fiscal.adapters.browser.task import (
	BrowserTask,
	FacilidadesTask,
	IIBBTask,
	LoginTask,
	RegistroTask,
	VencimientosDeudasTask,
)

__all__ = [
	'build_browser_tasks',
	'build_browser_provider',
	'BrowserbaseBrowser',
	'ComposioBrowser',
	'BrowserTask',
	'FacilidadesTask',
	'IIBBTask',
	'LoginTask',
	'MockBrowser',
	'PROVIDERS',
	'RegistroTask',
	'VencimientosDeudasTask',
]
