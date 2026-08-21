"""Registro tributario — instrucción NL para Composio Browser Tool.

Extrae domicilios, actividades, impuestos y puntos de venta del Registro
Único Tributario (RUT) de ARCA para un contribuyente representado.

Placeholders: ``{cuit}``, ``{clave}``, ``{cliente_cuit}``
"""

from __future__ import annotations

from agente_fiscal.adapters.browser.workflows._login_fragment import LOGIN_STEPS

TEMPLATE_REGISTRO: str = LOGIN_STEPS + """

--- PARTE 2: NAVEGAR A SISTEMA REGISTRAL ---

6. En el portal cloud, buscá en el campo de búsqueda "Sistema Registral".
   Hacé clic en el resultado que aparezca.
7. Se abre una nueva pestaña/ventana. Cambiá a ella.
   La URL debería contener "seti.afip.gob.ar".
8. En la página de Sistema Registral, buscá el campo para seleccionar
   el contribuyente representado. Ingresá: {cliente_cuit}

--- PARTE 3: ENTRAR AL RUT ---

9. Una vez cargado el contribuyente, buscá en el menú/navbar la opción
   "Registro Tributario". Hacé clic.
10. En la siguiente pantalla, buscá y hacé clic en el botón "Ingresar"
    que corresponda a "Registro Único Tributario".
11. Esperá que la página cargue COMPLETAMENTE (puede tardar). NO toques nada
    hasta que veas toda la información del RUT en pantalla.

--- PARTE 4: EXTRAER DATOS ---

12. Una vez cargada la página del RUT, scrolleá hasta el FINAL de la página.
13. Después del scroll, EXTRAÉ estos datos:

    A) DOMICILIOS: tipo, provincia, localidad, dirección, código postal
    B) JURISDICCIÓN: provincia de IIBB (si visible, si no → null)
    C) ACTIVIDADES: nombre, código, estado
    D) IMPUESTOS: nombre, categoría, estado
    E) PUNTOS DE VENTA: punto, tipo, estado
    F) IIBB JURISDICCIONES: buscar la sección de Ingresos Brutos.
       Para CADA provincia donde el contribuyente esté inscripto,
       extraer: provincia, número de inscripción, estado, fecha de alta,
       fecha de baja (si visible).

14. Armá este JSON exacto con los datos extraídos:

{
  "domicilios": [
    {"tipo": "Fiscal", "provincia": "CABA", "localidad": "CABA", "direccion": "Av. Ejemplo 123", "codigo_postal": "1000"}
  ],
  "jurisdiccion": "CABA",
  "actividades": [
    {"actividad": "Comercio", "codigo": "123456", "estado": "Activo"}
  ],
  "impuestos": [
    {"impuesto": "IVA", "categoria": "Responsable Inscripto", "estado": "Activo"}
  ],
  "puntos_de_venta": [
    {"punto": "0001", "tipo": "Emitir", "estado": "Activo"}
  ],
  "iibb_jurisdicciones": [
    {"provincia": "CABA", "inscripcion": "901-123456-7", "estado": "Activo", "fecha_alta": "2020-01-01", "fecha_baja": null},
    {"provincia": "Córdoba", "inscripcion": "123-456789-0", "estado": "Activo", "fecha_alta": "2019-06-15", "fecha_baja": null}
  ]
}

--- FINAL ---

15. Llamá al comando `done` con el JSON en el campo `text`.

Ejemplo:
done({"text": "{\\"domicilios\\": [], \\"jurisdiccion\\": null, \\"actividades\\": [], \\"impuestos\\": [], \\"puntos_de_venta\\": [], \\"iibb_jurisdicciones\\": []}", "success": true})

Si una sección no tiene datos, dejá el array vacío.
NO pongas texto adicional fuera del JSON.
"""
