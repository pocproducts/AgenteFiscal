"""Format pipeline results into natural Spanish chat responses.

Each formatter receives the raw ``data`` dict from the handler (or ``None``)
and returns a human-readable string in Spanish with markdown formatting.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fiscal_agent.models import RegistroOutput


def format_taxpayer_response(data: dict[str, Any] | None, cuit: str) -> str:
	"""Format taxpayer query result."""
	if data is None:
		return f'No se pudo consultar el CUIT {cuit}. Verificá que los certificados ARCA estén configurados.'

	error = data.get('error')
	if error:
		return f'❌ Error al consultar CUIT {cuit}: {error}'

	nombre = data.get('nombre', '')
	tipo = data.get('tipo', '')
	tipo_persona = data.get('tipo_persona', '')

	lines = [f'**Datos del contribuyente — {cuit}**\n']
	if nombre:
		lines.append(f'• **Nombre**: {nombre}')
	if tipo:
		lines.append(f'• **Tipo**: {tipo}')
	if tipo_persona:
		lines.append(f'• **Persona**: {tipo_persona}')

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
