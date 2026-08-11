"""Matching engine para detectar contribuyentes que requieren Rentas Córdoba.

Evalúa si un contribuyente con Convenio Multilateral IIBB y registro
en IIBB Córdoba (desde RUT) necesita integración con Rentas Córdoba.

Uso:
	from fiscal_agent.domain.matching import evaluar_rentas_cordoba

	resultado = evaluar_rentas_cordoba(
	    provincias=cliente.provincias,
	    impuestos_ws=padron.regimenGeneral.impuestos,
	    registro_impuestos=deuda_output.registro.impuestos,
	)
"""

from __future__ import annotations

import unicodedata
from typing import Optional

from fiscal_agent.domain.models import (
	IIBBJurisdiccionResultado,
	ImpuestoInscripto,
	RegistroIIBBJurisdiccion,
	RegistroImpuesto,
	RentasCordobaMatching,
)

#: idImpuesto del padrón que corresponden a IIBB
_IIBB_IDS: set[int] = {5904, 5902, 5905, 5906, 215}


def _normalize(text: str) -> str:
	"""Normaliza el texto: uppercase + remueve acentos para matching robusto."""
	text = text.upper()
	nfkd = unicodedata.normalize('NFKD', text)
	return nfkd.encode('ASCII', 'ignore').decode('ASCII')


def evaluar_rentas_cordoba(
	provincias: Optional[list[str]],
	impuestos_ws: Optional[list[ImpuestoInscripto]],
	registro_impuestos: Optional[list[RegistroImpuesto]],
) -> RentasCordobaMatching:
	"""Evalúa si un contribuyente requiere integración con Rentas Córdoba.

	La regla es conjuntiva — TODAS las condiciones deben cumplirse:

	1. **Convenio Multilateral**: 2+ provincias configuradas Y al menos un
	   ``idImpuesto`` IIBB (5904/5902/5905/5906/215) en ``impuestos_ws``.
	2. **IIBB Córdoba**: al menos un ``RegistroImpuesto`` cuyo campo
	   ``impuesto`` contenga "CORDOBA" (case-insensitive).

	Args:
		provincias: Provincias configuradas del cliente (ClientConfig).
		impuestos_ws: Impuestos del Padrón A5 (WS API).
		registro_impuestos: Impuestos del RegistroOutput (RUT browser task).

	Returns:
		RentasCordobaMatching con campos evaluados.
	"""
	# ── Convenio Multilateral check ───────────────────────────────
	tiene_convenio: bool = False
	if provincias is not None and len(provincias) >= 2 and impuestos_ws is not None:
		tiene_convenio = any(
			imp.idImpuesto is not None and imp.idImpuesto in _IIBB_IDS
			for imp in impuestos_ws
		)

	# ── IIBB Córdoba check ────────────────────────────────────────
	tiene_iibb_cordoba: bool | None = None
	if registro_impuestos is not None and len(registro_impuestos) > 0:
		tiene_iibb_cordoba = any(
			'CORDOBA' in _normalize(imp.impuesto or '') for imp in registro_impuestos
		)

	# ── Resultado ─────────────────────────────────────────────────
	requiere_integracion = tiene_convenio and (tiene_iibb_cordoba is True)

	if requiere_integracion:
		estado = 'pendiente'
		observacion = (
			'Contribuyente con Convenio Multilateral IIBB y registro en '
			'IIBB Córdoba. La integración con Rentas Córdoba está en desarrollo.'
		)
	elif tiene_iibb_cordoba is None:
		estado = 'sin_datos'
		observacion = (
			'No se pudo evaluar la necesidad de integración con Rentas Córdoba (faltan datos de registro tributario).'
		)
	else:
		estado = 'no_requerido'
		observacion = ''

	return RentasCordobaMatching(
		requiere_integracion=requiere_integracion,
		tiene_convenio_multilateral=tiene_convenio,
		tiene_iibb_cordoba=tiene_iibb_cordoba,
		estado=estado,
		observacion=observacion,
	)


# IIBB idImpuesto → provincia mapping
# Same set as rules_engine._IMPUESTO_TO_OBLIGACION IIBB keys
_IIBB_ID_TO_PROVINCIA: dict[int, str] = {
	5902: 'CABA',
	5904: 'Córdoba',
	5905: 'Buenos Aires',
	5906: 'Santa Fe',
	215: 'Acciones',
}


def evaluar_iibb(
	provincias_configuradas: Optional[list[str]],
	impuestos_ws: Optional[list[ImpuestoInscripto]],
	iibb_jurisdicciones: Optional[list[RegistroIIBBJurisdiccion]],
) -> list[IIBBJurisdiccionResultado]:
	"""Evalúa IIBB multi-jurisdicción: cruza config, WS API y RUT.

	Para cada jurisdicción IIBB detectada en el RUT, verifica:
	1. Si el cliente tiene esa provincia configurada
	2. Si el WS API reporta IIBB para esa provincia
	3. Resultado: match_total solo si coinciden las 3 fuentes

	Args:
	    provincias_configuradas: Provincias del ClientConfig.
	    impuestos_ws: Impuestos del Padrón A5 (WS API).
	    iibb_jurisdicciones: Jurisdicciones IIBB del RUT.

	Returns:
	    Lista de IIBBJurisdiccionResultado, una por jurisdicción detectada.
	"""
	if not iibb_jurisdicciones:
		return []

	provincias_set = set(p.lower() for p in (provincias_configuradas or []))
	ws_ids = set(imp.idImpuesto for imp in (impuestos_ws or []) if imp.idImpuesto is not None)

	resultados: list[IIBBJurisdiccionResultado] = []
	for ij in iibb_jurisdicciones:
		prov = ij.provincia
		prov_lower = prov.lower()

		configurada = prov_lower in provincias_set

		en_ws = any(
			mapping_provincia.lower() == prov_lower for _id, mapping_provincia in _IIBB_ID_TO_PROVINCIA.items() if _id in ws_ids
		)

		resultados.append(
			IIBBJurisdiccionResultado(
				provincia=prov,
				configurada_en_cliente=configurada,
				detectada_en_ws=en_ws,
				detectada_en_rut=True,
				inscripcion=ij.inscripcion,
				estado=ij.estado,
				match_total=configurada and en_ws,
			)
		)

	return resultados
