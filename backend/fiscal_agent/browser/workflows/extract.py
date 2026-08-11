"""Extraer deuda de Mis Facilidades — instrucción NL para Composio Browser Tool.

Placeholders: ``{cliente_cuit}``
"""

from __future__ import annotations

TEMPLATE_EXTRACT: str = """Extraer deuda de Mis Facilidades — ARCA

Contexto: Ya estás autenticado como estudio contable en la sesión activa.
El cliente a consultar tiene CUIT: {cliente_cuit}

Instrucciones:

1. Navegá a https://auth.afip.gob.ar/contribuyente_/representados.xhtml
2. Esperá que cargue la página de representados.
3. Hacé clic en el botón o enlace que dice 'Cambiar Representado'.
4. En el campo de CUIT ingresá: {cliente_cuit}
5. Confirmá el cambio. Esperá que la pantalla muestre el nuevo representado.
6. Navegá a https://www.afip.gob.ar/misFacilidades/default.asp
7. Esperá hasta 10 segundos a que cargue la tabla de deuda.
8. Extraé la información de deuda en el siguiente formato JSON exacto:

{
    "deuda_actual": <monto total como número>,
    "saldos": [
        {
            "concepto": "<nombre del concepto>",
            "importe": <monto como número>,
            "vencimiento": "<fecha YYYY-MM-DD>"
        }
    ],
    "plan_pagos": <objeto con detalles del plan de pagos si existe, o null>
}

REGLAS:
- Si no hay deuda, devolvé deuda_actual: 0 y saldos: []
- Si hay plan de pagos activo, incluí los detalles relevantes
- Los importes SIEMPRE como números, no strings
- Las fechas en formato ISO (YYYY-MM-DD)
- Devolvé SOLO el JSON, sin texto adicional ni explicaciones
- Si la tabla no carga después de 10 segundos, intentá refrescar la página
"""
