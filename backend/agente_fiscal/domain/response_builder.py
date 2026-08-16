"""Format pipeline results into natural Spanish chat responses.

Each formatter receives the raw ``data`` dict from the handler (or ``None``)
and returns a human-readable string in Spanish with markdown formatting.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from agente_fiscal.domain.models import RegistroOutput


def format_taxpayer_response(data: dict[str, Any] | None, cuit: str) -> str:
	"""Format taxpayer query result with the full Padrón A5 data."""
	if data is None:
		return f'No se pudo consultar el CUIT {cuit}. Verificá que los certificados ARCA estén configurados.'

	error = data.get('error')
	if error:
		return f'❌ Error al consultar CUIT {cuit}: {error}'

	# Error de constancia reportado por ARCA (persona no encontrada / baja).
	constancia_err = data.get('error_constancia')
	if isinstance(constancia_err, dict) and constancia_err.get('error'):
		errores = constancia_err['error']
		if isinstance(errores, list):
			return f'❌ CUIT {cuit}: ' + '; '.join(str(e) for e in errores)
		return f'❌ CUIT {cuit}: {errores}'

	# Denominación: razón social, o apellido+nombre, o denominación plana.
	denominacion = (
		data.get('razon_social')
		or f"{data.get('apellido', '')} {data.get('nombre', '')}".strip()
		or data.get('denominacion')
		or ''
	)

	lines = [f'**Datos del contribuyente — CUIT {cuit}**\n']

	if denominacion:
		lines.append(f'• **Denominación**: {denominacion}')

	estado = data.get('estado') or data.get('estado_clave')
	if estado:
		lines.append(f'• **Estado de la clave**: {estado}')

	tipo_persona = data.get('tipo_persona')
	if tipo_persona:
		label = 'Jurídica' if tipo_persona == 'juridica' else 'Física'
		lines.append(f'• **Tipo de persona**: {label}')

	tipo = data.get('tipo')
	if tipo:
		_tipo_map = {
			'responsable_inscripto': 'Responsable Inscripto',
			'monotributo': 'Monotributo',
			'autonomo': 'Autónomo',
		}
		lines.append(f'• **Condición frente al IVA**: {_tipo_map.get(tipo, tipo)}')

	# Domicilio fiscal
	dom = data.get('domicilio_fiscal')
	if isinstance(dom, dict):
		partes = [dom.get('direccion'), dom.get('localidad'), dom.get('ciudad'), dom.get('provincia')]
		if dom.get('codPostal'):
			partes.append(f"CP {dom.get('codPostal')}")
		domicilio = ', '.join(p for p in partes if p)
		if domicilio:
			lines.append(f'• **Domicilio fiscal**: {domicilio}')

	# Impuestos (Régimen General)
	impuestos = data.get('impuestos_rg') or []
	if impuestos:
		lines.append('\n**Impuestos (Régimen General)**')
		for imp in impuestos:
			desc = imp.get('descripcionImpuesto') or imp.get('idImpuesto') or 'Impuesto'
			est = imp.get('estadoImpuesto') or ''
			lines.append(f'  • {desc}' + (f' — {est}' if est else ''))

	# Actividades económicas
	actividades = data.get('actividades') or []
	if actividades:
		lines.append('\n**Actividades económicas**')
		for act in actividades:
			desc = act.get('descripcionActividad') or act.get('idActividad') or 'Actividad'
			cod = act.get('idActividad')
			lines.append(f'  • {desc}' + (f' (cód. {cod})' if cod else ''))

	# Monotributo
	cat_mt = data.get('categoria_monotributo')
	if isinstance(cat_mt, dict) and cat_mt.get('descripcionCategoria'):
		lines.append(f'\n• **Categoría Monotributo**: {cat_mt.get("descripcionCategoria")}')
	act_mt = data.get('actividad_monotributo')
	if isinstance(act_mt, dict) and act_mt.get('descripcionActividad'):
		lines.append(f'• **Actividad Monotributo**: {act_mt.get("descripcionActividad")}')

	# Categorías de autónomo
	cat_aut = data.get('categorias_autonomo') or []
	if cat_aut:
		lines.append('\n**Categorías Autónomo**')
		for c in cat_aut:
			desc = c.get('descripcionCategoria') or c.get('idCategoriaAutonomo') or 'Categoría'
			lines.append(f'  • {desc}')

	# Regímenes
	regimenes = data.get('regimenes') or []
	if regimenes:
		lines.append('\n**Regímenes**')
		for r in regimenes:
			desc = r.get('descripcionRegimen') or r.get('idRegimen') or 'Régimen'
			lines.append(f'  • {desc}')

	# Metadatos de la consulta
	metadata = data.get('metadata')
	if isinstance(metadata, dict) and metadata.get('fechaHora'):
		lines.append(f'\n_Consulta realizada: {metadata.get("fechaHora")}_')

	return '\n'.join(lines)


def format_reporte_response(data: dict[str, Any] | None, cuit: str, arca_error: str = '') -> str:
	"""Format a complete fiscal report result into Spanish text.

	Args:
		data: The pipeline result dict from ``_procesar_cliente_pipeline()``.
		cuit: The CUIT that was queried.
		arca_error: Human-readable ARCA error reason, if applicable.

	Returns:
		Human-readable response in Spanish with markdown formatting.
	"""
	if data is None:
		if arca_error:
			return f'⚠️ {arca_error}'
		return f'No se pudo generar el reporte para CUIT {cuit}. Verificá que los certificados ARCA estén configurados.'

	error = data.get('error')
	if error:
		return f'❌ Error al generar reporte para CUIT {cuit}: {error}'

	cliente = data.get('cliente', cuit)
	lines = [f'**Reporte fiscal para {cliente} ({cuit})**\n']

	# Padrón A5
	if data.get('ws_api'):
		lines.append('✅ Datos del Padrón A5 consultados')

	# Calendario
	if data.get('calendario'):
		lines.append('✅ Calendario fiscal calculado')

	# PDF
	if data.get('pdf'):
		pdf_path = data.get('pdf_path', '')
		lines.append('✅ PDF generado exitosamente')
		if pdf_path:
			filename = Path(pdf_path).name
			lines.append(f'📄 [Descargar reporte]({_pdf_download_url(filename)})')

	# Email
	if data.get('email'):
		lines.append('✅ Email enviado al cliente')

	return '\n'.join(lines)


def _pdf_download_url(filename: str) -> str:
	"""Build the PDF download URL path."""
	return f'/v1/chat/reports/{filename}'


def format_registro(registro: Optional[RegistroOutput], cuit: str) -> str:
	"""Formatea el registro tributario para respuesta de chat.

	Args:
	    registro: RegistroOutput del pipeline (o None).
	    cuit: CUIT del contribuyente.

	Returns:
	    Texto plano legible con los datos del registro.
	"""
	if registro is None:
		return f'No se encontró registro tributario para CUIT {cuit}.'

	lines: list[str] = [f'Registro Tributario — CUIT {cuit}', '']

	if registro.jurisdiccion:
		lines.append(f'Jurisdicción: {registro.jurisdiccion}')
		lines.append('')

	if registro.domicilios:
		lines.append('Domicilios:')
		for d in registro.domicilios:
			parts = []
			if d.tipo:
				parts.append(d.tipo)
			if d.direccion:
				parts.append(d.direccion)
			if d.localidad:
				parts.append(d.localidad)
			if d.provincia:
				parts.append(d.provincia)
			if d.codigo_postal:
				parts.append(f'CP {d.codigo_postal}')
			lines.append(f'  • {", ".join(parts)}')
		lines.append('')

	if registro.actividades:
		lines.append('Actividades:')
		for a in registro.actividades:
			act_str = a.actividad
			if a.codigo:
				act_str += f' ({a.codigo})'
			if a.estado:
				act_str += f' — {a.estado}'
			lines.append(f'  • {act_str}')
		lines.append('')

	if registro.impuestos:
		lines.append('Impuestos:')
		for imp in registro.impuestos:
			imp_str = imp.impuesto
			if imp.categoria:
				imp_str += f' ({imp.categoria})'
			if imp.estado:
				imp_str += f' — {imp.estado}'
			lines.append(f'  • {imp_str}')
		lines.append('')

	if registro.iibb_jurisdicciones:
		lines.append('IIBB por jurisdicción:')
		for ij in registro.iibb_jurisdicciones:
			ij_str = f'  • {ij.provincia}'
			if ij.inscripcion:
				ij_str += f' — Insc: {ij.inscripcion}'
			if ij.estado:
				ij_str += f' ({ij.estado})'
			lines.append(ij_str)
		lines.append('')

	return '\n'.join(lines)
