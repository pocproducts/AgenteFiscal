"""IIBB Córdoba extraction — instrucción NL para Composio Browser Tool.

Extrae jurisdicciones IIBB de Rentas Córdoba desde el RUT de ARCA.

Placeholders: ``{cuit}``, ``{clave}``, ``{cliente_cuit}``
"""

from __future__ import annotations

from agente_fiscal.adapters.browser.workflows._login_fragment import LOGIN_STEPS

TEMPLATE_IIBB_CORDOBA: str = LOGIN_STEPS + """

--- PARTE 2: NAVEGAR A DGR Provincia de Córdoba---

6. En el portal cloud, buscá en el campo de búsqueda "DGR Provincia de Córdoba".
   Hacé clic en el resultado que aparezca.
7. Se abre una nueva pestaña/ventana. Cambiá a ella.
   La URL debería contener "https://www.rentascordoba.gob.ar/emision/perfil/impuestos".
8. En la página de Rentas Cordoba, buscá el campo para seleccionar en la parte superior
   Clickearlo y apretar en "Representados", esperar que cargue la pagina, escrolear si es necesario hasta identificar {cliente_cuit} y una vez identificado cambiar al {cliente_cuit}

--- PARTE 3: ENTRAR AL RUT ---

9. Una vez cargado el contribuyente, buscá en la pagina
   "Pagos Mensuales" y desplegar solamente "Ingresos Brutos"
   
10. En la misma pagina se listaran **Todos los pagos**
    que corresponda a todos los impuestos de Ingresos Brutos de la Provincia de Cordoba.
11. Esperá que la página cargue COMPLETAMENTE (puede tardar).
12. Si en "Pagos Mensuales" no hay existencia alguna de "Ingresos Brutos"
    entonces el contribuyente no deudas de "Ingresos Brutos" a pagar

--- PARTE 4: EXTRAER JURISDICCIONES IIBB ---

12. Una vez cargada la página del RUT, reconoce la pagina y la seccion "Pagos Mensuales"
13. Desplega ls seccion de "Ingresos Brutos" y si no hay una seccion de Ingresos Brutos entonces el contribuyente no tiene deudas por ende la navegacion termina y se avisa en el PDF que Ingresos Brutos de la Provincia de Cordoba no tiene deudas, de lo contrario te aparecera el paso 14.
14. Para CADA impuesto de ingresos brutos que aparece desplegado, extraé:
    - provincia (nombre de la provincia)
    - inscripción (número de inscripción IIBB)
    - estado (Activo, Suspendido, Baja, etc.)
    - fecha_alta (si visible, formato YYYY-MM-DD)
    - fecha_baja (si visible, formato YYYY-MM-DD, null si no aplica)

--- PARTE 5: EXTRAER CUOTAS VENCIDAS ---

15. En la misma pagina de "Pagos Mensuales" ya cargada con "Ingresos Brutos"
    desplegado, buscá la lista de pagos/cuotas que aparecen.

16. IMPORTANTE: Si no hay cuotas/pagos listados, devolvé "cuotas_vencidas": []

17. Para CADA cuota/pago visible, extraé:
    - "periodo": texto con el período, ej: "2026/3"
    - "impuesto": texto, ej: "Ingresos Brutos Local - Régimen Mensual"
    - "vencimiento": fecha en formato YYYY-MM-DD
    - "saldo": número decimal (sin $) o null si es 0
    - "recargo": número decimal (sin $) o null si no aplica
    - "estado": texto, ej: "EN MORA", "PAGADO", "VENCIDO"
    - "apto_plan": booleano, true si dice "Apta plan", false si dice "No apta plan"

18. Fijate si hay un checkbox o indicador visual de "EN MORA" al lado de la cuota.
    Si la cuota está vencida, el estado es "EN MORA".

Armá este JSON exacto con los datos extraídos:

{
  "iibb_jurisdicciones": [
    {
      "provincia": "<nombre>",
      "inscripcion": "<número>",
      "estado": "<estado>",
      "fecha_alta": "<YYYY-MM-DD o null>",
      "fecha_baja": "<YYYY-MM-DD o null>"
    }
  ],
  "cuotas_vencidas": [
    {
      "periodo": "2026/3",
      "impuesto": "Ingresos Brutos Local - Régimen Mensual",
      "vencimiento": "2026-04-16",
      "saldo": 15000.00,
      "recargo": null,
      "estado": "EN MORA",
      "apto_plan": false
    }
  ]
}
--- FINAL ---

19. Llamá al comando `done` con el JSON en el campo `text`.

Ejemplo:
done({"text": "{\\"iibb_jurisdicciones\\": [], \\"cuotas_vencidas\\": []}", "success": true})

Si no hay datos de IIBB, devolvé el array vacío y el mensaje "DGR Pronviancia de Cortdoba no hay deudas y se encuentra al dia".
NO pongas texto adicional fuera del JSON.
"""

__all__ = ['TEMPLATE_IIBB_CORDOBA']
