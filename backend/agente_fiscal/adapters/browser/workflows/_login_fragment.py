"""Shared PARTE 1 - LOGIN EN ARCA fragment for Composio/Browserbase NL instructions.

Every browser-tool workflow that authenticates reuses this exact block so a future
AFIP login change touches ONE place. The fragment carries the {cuit} and {clave}
placeholders; tool-specific parts (switch representado, extraction) append after
it and supply {cliente_cuit}.

Success signal: the post-login AFIP redirect lands on cloud.afip.gob.ar
(user-verified). The public www.afip.gob.ar/landing/default.asp is PRE-auth and
must NOT be used as a success criterion.
"""

from __future__ import annotations

LOGIN_STEPS: str = """PARTE 1 - LOGIN EN ARCA

1. Navega a https://auth.afip.gob.ar/contribuyente_/login.xhtml
2. Espera que cargue completamente la pagina de login.
3. En el campo 'CUIT' ingresa: {cuit}
4. Hace clic en 'Siguiente'.
5. Espera que aparezca el campo de contrasena (max 5 segundos).
6. En el campo de contrasena ingresa: {clave}
7. Hace clic en 'Ingresar'.
8. Espera la redireccion a una URL que contenga 'cloud.afip.gob.ar' (max 15s).

ERRORES - Detene la tarea y reporta:
  ERROR ARCA-4 si ves 'CUIT incorrecto', 'clave invalida' o similar
  ERROR ARCA-6 si ves 'codigo de verificacion', '2FA', 'token'
  ERROR ARCA-1 si despues de reintentar no redirige al cloud.afip.gob.ar
"""
