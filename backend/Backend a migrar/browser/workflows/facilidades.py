"""Planes de pago — instrucción NL para Composio Browser Tool.

Extrae planes de pago de Mis Facilidades ARCA para un contribuyente representado.
Para cada plan filtrado (vigentes + caducos recientes), navega al detalle para
extraer pagos, cuotas, próximo vencimiento y datos del plan (CBU, consolidación).

Placeholders: ``{cuit}``, ``{clave}``, ``{cliente_cuit}``
"""

from __future__ import annotations

TEMPLATE_FACILIDADES: str = """Mis Facilidades — Extraer planes de pago con detalle de cuotas y datos del plan

PARTE 1 — LOGIN EN ARCA

1. Navegá a https://auth.afip.gob.ar/contribuyente_/login.xhtml
2. Esperá que cargue completamente la página de login.
3. En el campo 'CUIT' ingresá: {cuit}
4. Hacé clic en 'Siguiente'
5. Esperá que aparezca el campo de contraseña (máx. 5 segundos).
6. Ingresá clave fiscal: {clave}
7. Hacé clic en 'Ingresar'
8. Esperá la redirección al portal cloud de AFIP (URL que contenga 'cloud.afip.gob.ar').

ERRORES — Detené la tarea y reportá:
  ERROR ARCA-4 si ves 'CUIT incorrecto', 'clave inválida' o similar
  ERROR ARCA-6 si ves 'código de verificación', '2FA', 'token'

PARTE 2 — SALIR DEL PORTAL CLOUD E IR A MIS FACILIDADES

9. Después del login, estás en el portal cloud (URL con "cloud.afip.gob.ar").
   SALÍ del portal cloud primero. Buscá un botón/link que diga "Ir al portal AFIP",
   "Portal", "Salir", "Volver al portal", o similar. Hacé clic.

10. Una vez en el portal AFIP general (portal.afip.gob.ar), buscá el servicio
    "Mis Facilidades". Usá el buscador del portal (tiene un campo de búsqueda)
    o navegá por los menús: "Tramites" → "Mis Facilidades".

11. El paso 10 abrira otra pagina, tienes que navegar hacia ella y esperar que cargue, el contexto de la url de la pagina es el siguiente "https://serviciossegsoc.afip.gob.ar/tramites_con_clave_fiscal/MisFacilidadesNet/app/login/IndexContribuyente.aspx"

12. Una vez que estés en Mis Facilidades, esperá que cargue la página COMPLETAMENTE
    (hasta que se cargue).

13. Buscá en la página un menú desplegable (select / combobox) que contenga
    una lista de CUITs representados por el estudio.
    Seleccioná la opción cuyo valor sea EXACTAMENTE: {cliente_cuit}

14. Al seleccionarlo, la página se envía automáticamente (onchange submit).
    Esperá que la página recargue con los datos del nuevo representado (hasta que cargue).

15. Verificá que el menú desplegable muestre ahora seleccionado el CUIT {cliente_cuit}.
    Si no es así, intentá de nuevo el paso 13.

PARTE 3 — LISTAR PLANES DE PAGO Y FILTRAR

16. Una vez cargada la página con el contribuyente seleccionado, buscá
    el listado de planes de pago.

17. La página puede tener múltiples páginas (paginación). Si hay más de una
    página, navegá a través de TODAS para no perder ningún plan.

18. Por cada plan en la lista, identificá su estado. Los estados posibles son:
    - VIGENTE: plan activo, en curso de pago
    - CADUCO: plan vencido, no se completó
    - CANCELADO / PAGADO TOTAL: pagado en su totalidad
    - REFINANCIADO: fue reemplazado por un plan nuevo

19. REGLA DE FILTRO — SOLO procesá (ingresando al detalle) los planes que
    cumplan ALGUNA de estas condiciones:

    A) Estado VIGENTE: procesálo SIEMPRE.

    B) Estado CADUCO: procesálo SOLO si es RECIENTE:
       - "fecha de presentación" del plan + (cantidad_cuotas × 30 días)
       - Si la fecha de hoy está a MENOS de 12 meses después de ese cálculo → EXTRAER
       - Si pasaron MÁS de 12 meses → OMITIR

    C) Estado CANCELADO / PAGADO TOTAL: NO lo proceses.

    D) Estado REFINANCIADO: NO lo proceses.

PARTE 4 — DETALLE DEL PLAN: PAGOS + DATOS DEL PLAN

Para CADA plan que pasó el filtro, ejecutá los siguientes pasos:

20. Hacé clic en el plan para ingresar a su pantalla de detalle.
    Esperá que cargue completamente (hasta 10 segundos).

21. DENTRO DEL PLAN — Buscá una sección, pestaña o botón que diga "Pagos"
    o "Cuotas" o "Detalle de pagos". Hacé clic para acceder.

22. REVISIÓN DE CUOTAS — Una vez en la sección de pagos/cuotas:
    - Buscá la tabla de cuotas con TODAS las columnas visibles.
    - Extraé el listado COMPLETO de cuotas, incluyendo cada columna:
      * "Cuota N°" → número de cuota
      * "Capital ($)" → monto de capital
      * "Interés Financiero ($)" → interés financiero
      * "Interés Resarcitorio ($)" → interés resarcitorio
      * "Total ($)" → monto total de la cuota
      * "Fecha Venc." → fecha de vencimiento
      * "Pago" → fecha en que se pagó (si está paga) o vacío
      * "Estado de Cuota" → "PAGA", "IMPARA", "DEBITADA", etc.
    - Identificá el estado de cada cuota:
      * "PAGA" o "DEBITADA": el pago se realizó correctamente.
      * "IMPARA" o "VENCIDA": no se pagó, está pendiente.
    - Determiná cuál es la PRÓXIMA cuota a vencer (si la hay):
      * Si hay cuotas IMPAGAS: la más próxima es el próximo vencimiento.
      * Si todas están pagas: el plan está al día, no hay próximo vencimiento.
    - Para la próxima cuota a vencer, extraé:
      * Número de cuota
      * Fecha de vencimiento
      * Monto
    - Si hay cuotas IMPAGAS, incluilas en el JSON con su detalle.

23. DATOS DEL PLAN — Buscá una sección, pestaña o botón que diga
    "Datos del Plan", "Resumen" o "Detalle del Plan". Hacé clic y extraé:
    - "fecha_consolidacion": la fecha de consolidación del plan
    - "cbu": el CBU asociado al plan (de quién se presenta)
    - "titular_cbu": titular de ese CBU (si está visible)
    - Cualquier otro dato relevante que veas en esta sección

24. VOLVÉ al listado de planes. Usá "Volver" o "Atrás" para regresar
    al listado principal. Si no encontrás el botón, repetí los pasos 9-15
    (salir del cloud, ir a Mis Facilidades, seleccionar contribuyente)
    para volver al listado.

25. Repetí los pasos 20-24 para cada plan que pasó el filtro.

RESULTADO FINAL — FORMATO DEL JSON

24. Para cada plan procesado, armá el siguiente JSON exacto.
    Los campos marcados con ``<...>`` son valores reales que extrajiste.
    Los strings van entre comillas dobles, los números sin comillas.
    ``null`` cuando no hay valor.

    {{
      "plan": "<nombre o identificador del plan>",
      "nro_plan": "<número de plan>",
      "estado": "VIGENTE" | "CADUCO",
      "fecha_presentacion": "<YYYY-MM-DD>",
      "cantidad_cuotas": <número>,
      "cuotas_pagas": <número>,
      "cuotas_impagas": <número>,
      "saldo": <número>,
      "concepto": "<impuesto/s al que aplica>",

      "proximo_vencimiento": null
        o {{
          "nro_cuota": <número>,
          "fecha": "<YYYY-MM-DD>",
          "total": <número>
        }},

      "cuotas": [
        {{
          "numero": <número>,
          "capital": <número>,
          "interes_financiero": <número>,
          "interes_resarcitorio": <número>,
          "total": <número>,
          "vencimiento": "<YYYY-MM-DD>",
          "fecha_pago": "<YYYY-MM-DD>" o null,
          "estado": "PAGA" | "IMPARA" | "DEBITADA"
        }}
      ],

      "datos_plan": {{
        "fecha_consolidacion": "<YYYY-MM-DD>",
        "cbu": "<CBU>",
        "titular_cbu": "<nombre del titular>"
      }},

      "observacion": "<frase lista para email>"
    }}

    IMPORTANTE — La "observacion" debe ser una frase en lenguaje natural
    lista para usar directamente en un email. Por ejemplo:
    - "Plan al día. Próximo vencimiento N° de plan 123456 vence el 16/07/2026 por $45.530,48."
    - "Tiene 2 cuotas impagas por un total de $91.060,96. Consultar si desea generar VEP para cancelar."

26. Agregá cada plan procesado al array "planes".

27. Si después de aplicar todos los filtros no queda ningún plan,
    devolvé "planes": [].

CIERRE — IMPORTANTE

Cuando llames al comando `done`, el campo `text` DEBE contener ÚNICAMENTE el JSON completo.
No pongas resúmenes ni explicaciones. El sistema SOLO procesa el JSON que está en `text`.

Ejemplo de cómo llamar a `done`:
done({{"text": "{{\\"planes\\": []}}", "success": true}})

Si no hay planes: "planes": []
"""
