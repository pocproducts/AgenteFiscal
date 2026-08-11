"""Browser automation layer for ARCA extraction.

Composio Browser Tool — instrucciones NL en lugar de Playwright + YAML.
"""

from fiscal_agent.adapters.browser.composio import ComposioBrowser
from fiscal_agent.adapters.browser.factory import build_browser_tasks
from fiscal_agent.adapters.browser.task import (
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
