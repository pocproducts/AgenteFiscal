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


# ─── Browser tools: formatters por tool ─────────────────────────────────────
# Cada ``format_<tool>_response(data, cuit)`` recibe el dict plano del handler
# (``DeudaOutput.model_dump()`` para Phase-1; output de motor para Phase-2) y
# devuelve markdown en español. Rama de error primero (BROWSER_ERROR → motivo
# corto; códigos de motor → `{code}` — detail), luego secciones sobre los keys
# existentes. Estilo espejo de ``format_registro_response`` (chat.py).


def _error_reply(data: dict[str, Any] | None, cuit: str, tool_label: str) -> str | None:
	"""Devuelve la respuesta corta de error si no hay datos o vienen con error."""
	if data is None:
		# El handler no devolvió nada (p.ej. sin credenciales/token ARCA).
		return f'No pude consultar {tool_label} para el CUIT {cuit}.\n\n**Motivo:** No se obtuvo respuesta del backend'
	if not data.get('error'):
		return None
	err = data.get('error')
	label = f'No pude consultar {tool_label} para el CUIT {cuit}.'
	if err == 'BROWSER_ERROR':
		return f'{label}\n\n**Motivo:** Error de conexión'
	detail = data.get('detail') or 'Error desconocido'
	return f'{label}\n\n**Motivo:** `{err}` — {detail}'


def _bullet(items: list[str]) -> str:
	"""Une items no vacíos como lista de markdown (``- item``)."""
	return '\n'.join(f'- {i}' for i in items if i and str(i).strip())


def format_deuda_response(data: dict[str, Any] | None, cuit: str) -> str:
	"""Formatea deuda y vencimientos (ctacte.cloud) del DeudaOutput."""
	error = _error_reply(data, cuit, 'la deuda')
	if error:
		return error

	lines = [f'**Deuda y vencimientos (ARCA)** — CUIT {cuit}', '']

	deuda_actual = (data or {}).get('deuda_actual')
	if isinstance(deuda_actual, (int, float)) and deuda_actual >= 0:
		lines.append(f'- **Deuda actual:** $ {deuda_actual:,.2f}')

	vencimientos = (data or {}).get('vencimientos') or []
	if vencimientos:
		lines.append('- **Vencimientos:**')
		for v in vencimientos[:10]:
			detalle = ' — '.join(
				str(x)
				for x in [
					v.get('impuesto') or '',
					v.get('concepto') or '',
					(v.get('periodo') or ''),
					f"vence {v.get('fecha_vencimiento')}" if v.get('fecha_vencimiento') else '',
				]
				if str(x).strip()
			)
			lines.append(f'  - {detalle}')

	deudas = (data or {}).get('deudas') or []
	if deudas:
		lines.append('- **Deudas en mora:**')
		for d in deudas[:10]:
			saldo = d.get('saldo') or 0.0
			detalle = ' — '.join(
				str(x)
				for x in [
					d.get('impuesto') or '',
					d.get('concepto') or '',
					f'$ {saldo:,.2f}',
					f"vence {d.get('vencimiento')}" if d.get('vencimiento') else '',
				]
				if str(x).strip()
			)
			lines.append(f'  - {detalle}')

	if not (isinstance(deuda_actual, (int, float)) or vencimientos or deudas):
		lines.append('No se encontraron deudas o vencimientos activos.')

	lines.append('')
	lines.append('_Datos obtenidos de AFIP en vivo (CUIT coherente)._')
	return '\n'.join(lines)


def format_facilidades_response(data: dict[str, Any] | None, cuit: str) -> str:
	"""Formatea los planes de Mis Facilidades del DeudaOutput."""
	error = _error_reply(data, cuit, 'Mis Facilidades')
	if error:
		return error

	facilidades = (data or {}).get('facilidades') or []
	lines = [f'**Mis Facilidades (ARCA)** — CUIT {cuit}', '']

	for plan in facilidades[:10]:
		nombre = plan.get('plan') or 'Plan'
		nro = plan.get('nro_plan')
		estado = plan.get('estado') or ''
		header = f'- **{nombre}**' + (f' (N° {nro})' if nro else '')
		if estado:
			header += f' — {estado}'
		lines.append(header)
		detalles: list[str] = []
		if plan.get('cantidad_cuotas'):
			detalles.append(f'{plan["cantidad_cuotas"]} cuotas, {plan.get("cuotas_pagas") or 0} pagas')
		if plan.get('saldo'):
			detalles.append(f'saldo $ {plan["saldo"]:,.2f}')
		proximo = plan.get('proximo_vencimiento')
		if isinstance(proximo, dict) and proximo.get('fecha'):
			detalles.append(f'próximo vencimiento {proximo["fecha"]}')
		if detalles:
			lines.append(f'  - {" | ".join(detalles)}')

	if not facilidades:
		lines.append('No se encontraron planes de pago activos.')

	lines.append('')
	lines.append('_Datos obtenidos de Mis Facilidades ARCA en vivo._')
	return '\n'.join(lines)


def format_rentas_response(data: dict[str, Any] | None, cuit: str) -> str:
	"""Formatea IIBB (rentas Córdoba) desde el registro del DeudaOutput."""
	error = _error_reply(data, cuit, 'las rentas')
	if error:
		return error

	registro = (data or {}).get('registro') or {}
	jurisdicciones = registro.get('iibb_jurisdicciones') or []
	cuotas = registro.get('iibb_cuotas_vencidas') or []

	lines = [f'**Rentas Córdoba (IIBB)** — CUIT {cuit}', '']

	if jurisdicciones:
		lines.append('- **Inscripciones IIBB:**')
		for j in jurisdicciones[:10]:
			item = ' — '.join(
				str(x)
				for x in [j.get('provincia') or '', f"Insc: {j.get('inscripcion')}" if j.get('inscripcion') else '', j.get('estado') or '']
				if str(x).strip()
			)
			lines.append(f'  - {item}')

	if cuotas:
		lines.append('- **Cuotas vencidas:**')
		for c in cuotas[:10]:
			saldo = c.get('saldo')
			item = ' — '.join(
				str(x)
				for x in [
					c.get('periodo') or '',
					c.get('impuesto') or '',
					f'$ {saldo:,.2f}' if isinstance(saldo, (int, float)) else '',
					c.get('estado') or '',
				]
				if str(x).strip()
			)
			lines.append(f'  - {item}')

	if not jurisdicciones and not cuotas:
		lines.append('No se encontró registro IIBB para la provincia de Córdoba.')

	lines.append('')
	lines.append('_Datos obtenidos del registro tributario ARCA en vivo._')
	return '\n'.join(lines)


def format_consultaarca_response(data: dict[str, Any] | None, cuit: str) -> str:
	"""Formatea la consulta al padrón A5 (determinista, sin browser).

	Renderiza la sección **Obligaciones** (keys del mock TS `ejecutarConsultaArca`
	o los impuestos del padrón ``impuestos_rg``/``impuestos_mt``) más los datos
	básicos del contribuyente.
	"""
	error = _error_reply(data, cuit, 'el padrón ARCA')
	if error:
		return error

	data = data or {}
	lines = [f'**Consulta ARCA (Padrón A5)** — CUIT {cuit}', '']

	denominacion = (
		data.get('razon_social')
		or f"{data.get('apellido', '')} {data.get('nombre', '')}".strip()
		or data.get('denominacion')
		or ''
	)
	if denominacion:
		lines.append(f'- **Denominación:** {denominacion}')

	tipo = data.get('tipo')
	if tipo:
		lines.append(f'- **Condición frente al IVA:** {tipo}')

	estado = data.get('estado') or data.get('estado_clave')
	if estado:
		lines.append(f'- **Estado de la clave:** {estado}')

	dom = data.get('domicilio_fiscal')
	if isinstance(dom, dict):
		partes = [dom.get('direccion'), dom.get('localidad'), dom.get('ciudad'), dom.get('provincia')]
		if dom.get('codPostal'):
			partes.append(f"CP {dom.get('codPostal')}")
		domicilio = ', '.join(p for p in partes if p)
		if domicilio:
			lines.append(f'- **Domicilio fiscal:** {domicilio}')

	# Obligaciones: shape del mock TS (obligaciones[].impuesto/codigo/estado) o
	# los impuestos del padrón (impuestos_rg + impuestos_mt).
	obligaciones = data.get('obligaciones')
	if isinstance(obligaciones, list) and obligaciones:
		lines.append('- **Obligaciones:**')
		for ob in obligaciones[:12]:
			item = ' — '.join(
				str(x)
				for x in [ob.get('impuesto') or '', ob.get('codigo') or '', ob.get('estado') or '']
				if str(x).strip()
			)
			lines.append(f'  - {item}')
	else:
		impuestos = (data.get('impuestos_rg') or []) + (data.get('impuestos_mt') or [])
		if impuestos:
			lines.append('- **Obligaciones:**')
			for imp in impuestos[:12]:
				desc = imp.get('descripcionImpuesto') or imp.get('idImpuesto') or 'Impuesto'
				est = imp.get('estadoImpuesto') or ''
				lines.append(f'  - {desc}' + (f' — {est}' if est else ''))

	if not denominacion and not obligaciones and not (data.get('impuestos_rg') or data.get('impuestos_mt')):
		lines.append('No se encontraron datos para el CUIT consultado.')

	lines.append('')
	lines.append('_Datos del padrón ARCA (consulta determinista, sin browser)._')
	return '\n'.join(lines)


def format_calendario_response(data: dict[str, Any] | None, cuit: str) -> str:
	"""Formatea el calendario de vencimientos (RulesOutput, determinista)."""
	error = _error_reply(data, cuit, 'el calendario')
	if error:
		return error

	data = data or {}
	periodo = data.get('periodo') or ''
	header = f'**Calendario de vencimientos (ARCA)** — CUIT {cuit}'
	if periodo:
		header += f' ({periodo})'
	lines = [header, '']

	vencimientos = data.get('vencimientos') or []
	observaciones = data.get('observaciones') or []

	if vencimientos:
		for v in vencimientos[:20]:
			fecha = v.get('fecha') or ''
			concepto = v.get('concepto') or ''
			importe = v.get('importe')
			line = f'- **{fecha}** — {concepto}'
			if isinstance(importe, (int, float)):
				line += f' ($ {importe:,.2f})'
			lines.append(line)

	if observaciones:
		lines.append('')
		lines.append('**Obligaciones informativas:**')
		lines.append(_bullet([str(o) for o in observaciones]))

	if not vencimientos and not observaciones:
		lines.append('No se encontraron vencimientos para el período.')

	feriados = data.get('feriados_presentes') or []
	if feriados:
		lines.append('')
		lines.append(f'_Período con {len(feriados)} feriados en los vencimientos calculados._')

	lines.append('')
	lines.append('_Calendario calculado con el motor de reglas fiscales (sin browser)._')
	return '\n'.join(lines)
