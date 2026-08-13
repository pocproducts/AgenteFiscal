"""Browser automation layer for ARCA extraction.

Composio Browser Tool — instrucciones NL en lugar de Playwright + YAML.
"""

from agente_fiscal.adapters.browser.composio import ComposioBrowser
from agente_fiscal.adapters.browser.factory import build_browser_tasks
from agente_fiscal.adapters.browser.task import (
	BrowserTask,
	FacilidadesTask,
	IIBBTask,
	LoginTask,
	RegistroTask,
	VencimientosDeudasTask,
)

# Backward compatibility alias
FullTask = VencimientosDeudasTask

__all__ = [
	'build_browser_tasks',
	'ComposioBrowser',
	'BrowserTask',
	'FacilidadesTask',
	'FullTask',  # alias backward-compatible
	'IIBBTask',
	'LoginTask',
	'RegistroTask',
	'VencimientosDeudasTask',
]
