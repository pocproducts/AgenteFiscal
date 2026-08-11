"""Pipeline completo — instrucción NL para Composio Browser Tool.

Placeholders: ``{cuit}``, ``{clave}``, ``{cliente_cuit}``
"""

from __future__ import annotations

TEMPLATE_FULL: str = """Sistema de Cuentas Tributarias — Extraer deuda y vencimientos

PARTE 1 — LOGIN EN ARCA

1. Abrí la URL:
   https://auth.afip.gob.ar
2. Esperá a que cargue completamente (máx 10s).
3. En el campo "CUIT" ingresá: {cuit}
4. Click en "Siguiente".
5. Esperá que aparezca el campo de contraseña (máx 5s).
6. En el campo de contraseña ingresá: {clave}
7. Click en "Ingresar".
8. Esperá redirección a una URL que contenga "cloud.afip.gob.ar" (máx 15s).

ERRORES — Detené la tarea y reportá:
  ERROR ARCA-4 si ves 'CUIT incorrecto', 'clave inválida' o similar
  ERROR ARCA-6 si ves 'código de verificación', '2FA', 'token'
  ERROR ARCA-1 si después de reintentar no redirige al cloud

PARTE 2 — CAMBIAR AL CONTRIBUYENTE REPRESENTADO

9. Navegá al portal de cuentas tributarias (buscá el enlace o usá la URL).
10. Esperá que cargue completamente (máx 15s).
11. Buscá el select/combobox que contiene los CUITs de representados.
12. Seleccioná EXACTAMENTE: {cliente_cuit}
13. La página se envía automáticamente. Esperá que recargue (máx 10s).
14. Verificá que el select muestre {cliente_cuit} como seleccionado.
    Si no se seleccionó, reportá ERROR ARCA-7 y detené.

ERRORES:
   ERROR ARCA-2 si no encontrás el select de representados en 15s
   ERROR ARCA-3 si la página muestra "no tenés representados"

PARTE 3 — EXTRAER VENCIMIENTOS

15. Una vez cargada la página con el contribuyente seleccionado, buscá
    la sección, pestaña o botón que diga "Vencimientos", "Calendario de
    Vencimientos", "Próximos Vencimientos" o similar. Hacé clic.

16. Esperá que cargue la tabla de vencimientos (hasta 10 segundos).
    Si hay un botón "Consultar" o "Buscar", hacé clic primero.

17. Una vez visible la tabla, extraé TODAS las filas visibles.
    Si hay paginación, navegá por todas las páginas.

18. Por cada fila de la tabla, extraé estos campos exactos:
    - "impuesto": texto (ej: "IVA", "Ganancias", "Ingresos Brutos", etc.)
    - "concepto": texto (ej: "SIR", "Declaración Jurada", etc.)
    - "subconcepto": texto o null
    - "periodo": número o null (ej: 202406)
    - "anticuota": número o null
    - "fecha_vencimiento": fecha en formato YYYY-MM-DD (ej: "2026-06-18")
    - "detalle": texto o null

19. Normalización:
    - Fechas: si ves "18/06/2026" convertilo a "2026-06-18"
    - Importes: sin $ ni puntos, como número decimal (ej: 150000.00)
    - Campos ausentes: null, no string vacío
    - Periodo y anticuota: como número entero, sin comillas

20. Guardá todas las filas en un array llamado "vencimientos".

21. Si la tabla muestra "no hay datos", "sin vencimientos", "no hay registros"
    → devolvé "vencimientos": []

PARTE 4 — EXTRAER DEUDA

22. Buscá la sección, pestaña o botón que diga "Deuda", "Consulta de Deuda",
    "Cuenta Tributaria", "Estado de Deuda", "Deuda Exigible" o similar.
    Hacé clic.

23. Esperá que cargue la tabla de deuda (hasta 10 segundos).
    Si hay un botón "Consultar" o "Buscar", hacé clic primero.

24. Una vez visible la tabla, extraé TODAS las filas visibles.
    Si hay paginación, navegá por todas las páginas.

25. Por cada fila de la tabla, extraé estos campos exactos:
    - "impuesto": texto (ej: "10 - GANANCIAS SOCIEDADES", "IVA", etc.)
    - "concepto": texto o null (ej: "Impuesto a las Ganancias")
    - "subconcepto": texto o null
    - "periodo": número entero o null (ej: 2026, 202406)
    - "anticuota": número entero o null (ej: 1, 2)
    - "vencimiento": fecha YYYY-MM-DD o null (ej: "2026-06-18")
    - "saldo": número decimal o null (sin $, sin comas)
    - "interes_resarcitorio": número decimal o null
    - "interes_punitorio": número decimal o null

26. Normalización:
    - Fechas: YYYY-MM-DD
    - Importes: número decimal, sin $ ni puntos (ej: 45530.48, 0.0)
    - Campos ausentes: null
    - Si algún importe es "0" o está vacío: 0.0 o null según corresponda

27. Guardá todas las filas en un array llamado "deudas" (cada fila es un objeto).

28. Si la tabla muestra "no hay deuda", "saldos en cero", "sin registros"
    → devolvé "deudas": []

RESULTADO FINAL — FORMATO DEL JSON

29. Construí un único objeto JSON con esta estructura exacta:

{
  "deudas": [
    {
      "impuesto": "10 - GANANCIAS SOCIEDADES",
      "concepto": "Impuesto a las Ganancias",
      "subconcepto": null,
      "periodo": 2026,
      "anticuota": 1,
      "vencimiento": "2026-06-18",
      "saldo": 45530.48,
      "interes_resarcitorio": 0.0,
      "interes_punitorio": 0.0
    }
  ],
  "vencimientos": [
    {
      "impuesto": "IVA",
      "concepto": "SIR",
      "subconcepto": null,
      "periodo": 202406,
      "anticuota": 1,
      "fecha_vencimiento": "2026-06-18",
      "detalle": null
    }
  ]
}

30. Si no hay deuda: "deudas": []
31. Si no hay vencimientos: "vencimientos": []

CIERRE — IMPORTANTE

32. Cuando tengas el JSON listo, llamá al comando `done`.
    El campo `text` DEBE contener ÚNICAMENTE el JSON completo.
    No pongas resúmenes ni explicaciones. El sistema SOLO procesa el JSON.

    Ejemplo de cómo llamar a `done`:
    done({"text": "{\"deudas\": [], \"vencimientos\": []}", "success": true})

33. Si hubo un error que no te deja continuar, devolvé:
    {
      "error_code": "ARCA-X",
      "error_message": "descripción del error",
      "deudas": [],
      "vencimientos": []
    }
"""
