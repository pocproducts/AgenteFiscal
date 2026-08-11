"""Workflow templates for Composio Browser Tool.

Separados por etapa del pipeline ARCA:
    - login.py:  autenticación en AFIP con detección ARCA-4/ARCA-6
    - extract.py: extracción de deuda de Mis Facilidades (legacy)
    - full.py: pipeline completo login + switch + extract (ctacte.cloud)
    - facilidades.py: planes de pago vigentes y caducos recientes
    - iibb/: jurisdicciones IIBB desde el RUT (por provincia)
"""

from fiscal_agent.adapters.browser.workflows.extract import TEMPLATE_EXTRACT
from fiscal_agent.adapters.browser.workflows.facilidades import TEMPLATE_FACILIDADES
from fiscal_agent.adapters.browser.workflows.full import TEMPLATE_FULL
from fiscal_agent.adapters.browser.workflows.iibb import TEMPLATE_IIBB_CORDOBA, TEMPLATE_IIBB_JUJUY
from fiscal_agent.adapters.browser.workflows.login import TEMPLATE_LOGIN
from fiscal_agent.adapters.browser.workflows.registro import TEMPLATE_REGISTRO

# Backward-compatible alias — old code using `from workflows import TEMPLATE_IIBB`
# still works. Same string object (is check passes).
TEMPLATE_IIBB = TEMPLATE_IIBB_CORDOBA

__all__ = [
	'TEMPLATE_EXTRACT',
	'TEMPLATE_FACILIDADES',
	'TEMPLATE_FULL',
	'TEMPLATE_IIBB',
	'TEMPLATE_IIBB_CORDOBA',
	'TEMPLATE_IIBB_JUJUY',
	'TEMPLATE_LOGIN',
	'TEMPLATE_REGISTRO',
]
