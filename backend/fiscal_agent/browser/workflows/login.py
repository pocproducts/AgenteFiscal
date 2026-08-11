"""Login en ARCA — instrucción NL para Composio Browser Tool.

Placeholders: ``{cuit}``, ``{clave}``
"""

from __future__ import annotations

TEMPLATE_LOGIN: str = """Sesión de ARCA — Iniciar sesión como estudio contable

1. Navegá a https://auth.afip.gob.ar/contribuyente_/login.xhtml
2. Esperá que cargue completamente la página de login.
3. En el campo de texto 'CUIT' ingresá exactamente: {cuit}
4. Hacé clic en el botón 'Siguiente'.
5. Esperá que aparezca el campo de contraseña (hasta 5 segundos).
6. En el campo de contraseña ingresá: {clave}
7. Hacé clic en el botón 'Ingresar' (el input type='submit' del formulario).
8. Esperá la redirección. La URL debería contener 'impuestos' si la autenticación fue exitosa.

CRITERIOS DE ERROR — DETENER la tarea inmediatamente si:

- ARCA-4 (Credenciales inválidas): Si ves en pantalla mensajes como 'CUIT incorrecto',
  'clave fiscal incorrecta', 'credenciales inválidas', 'usuario y/o clave incorrectos',
  o similar, DETENÉ la tarea y reportá EXACTAMENTE: 'ERROR ARCA-4: Credenciales inválidas'

- ARCA-6 (2FA / Doble Factor): Si aparece una pantalla pidiendo 'código de verificación',
  'token', 'doble factor de autenticación', '2FA', 'código SMS', o similar,
  DETENÉ la tarea y reportá EXACTAMENTE: 'ERROR ARCA-6: 2FA requerido — no se puede automatizar'

La autenticación es exitosa solamente cuando la URL contiene 'impuestos' y no hay
mensajes de error visibles en la página. Si pasaron más de 15 segundos y la URL
sigue sin contener 'impuestos', asumí que falló y reportá error.
"""
