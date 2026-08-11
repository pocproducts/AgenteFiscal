"""IIBB Jujuy extraction — STUB: login AFIP + report no implementada.

Placeholders: {cuit}, {clave}, {cliente_cuit}
"""

from __future__ import annotations

TEMPLATE_IIBB_JUJUY: str = """IIBB Jurisdicciones — DGR Jujuy (STUB)

--- PARTE 1: LOGIN ---

1. Abrí https://auth.afip.gob.ar/contribuyente_/login.xhtml
2. Ingresá CUIT: {cuit}
3. Click 'Siguiente'. Esperá campo contraseña.
4. Ingresá clave: {clave}
5. Click 'Ingresar'. Esperá redirección a URL con 'cloud.afip.gob.ar'.

SI VES: 'CUIT incorrecto', 'clave inválida' → reportá ERROR ARCA-4 y detené.
SI VES: 'código de verificación', '2FA' → reportá ERROR ARCA-6 y detené.

--- PARTE 2: STUB ---

6. DGR Jujuy no implementada aún.
   Reportá que la integración con DGR Jujuy está en desarrollo.
   No hay navegación a realizar.

--- PARTE 3: OUTPUT ---

7. Llamá al comando `done` con el JSON en el campo `text`:

done({{"text": "{{\\"iibb_jurisdicciones\\": [], \\"cuotas_vencidas\\": []}}", "success": true}})

No pongas texto adicional fuera del JSON.
"""

__all__ = ['TEMPLATE_IIBB_JUJUY']
