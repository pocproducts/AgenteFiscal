"""Login en ARCA — instrucción NL para Composio Browser Tool.

Placeholders: ``{cuit}``, ``{clave}``
"""

from __future__ import annotations

from agente_fiscal.adapters.browser.workflows._login_fragment import LOGIN_STEPS

TEMPLATE_LOGIN: str = LOGIN_STEPS + """

La autenticación es exitosa solamente cuando la URL contiene 'cloud.afip.gob.ar' y no hay
mensajes de error visibles en la página. Si pasaron más de 15 segundos y la URL
sigue sin contener 'cloud.afip.gob.ar', asumí que falló y reportá error.
"""
