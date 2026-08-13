"""MCP tool: get_report_pdf — genera PDF de reporte fiscal.

Scope (HTTP): report:read
Genera un PDF con el calendario de vencimientos y opcionalmente deuda.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import Context

from agente_fiscal.adapters.arca_ws import consultar_cuit
from agente_fiscal.config import REPRESENTANTE_CUIT
from agente_fiscal.config import get_settings
from agente_fiscal.mcp.server import mcp
from agente_fiscal.domain.models import ApiError, UnifiedResponse


@mcp.tool()
async def get_report_pdf(
	cuit: str,
	mes: int | None = None,
	anio: int | None = None,
	con_deuda: bool = False,
	ctx: Context = None,
) -> str:
	"""Generar un PDF con el reporte fiscal de un contribuyente.

	Calcula el calendario de vencimientos y opcionalmente incluye
	la deuda real (requiere COMPOSIO_API_KEY). El PDF se guarda
	en el directorio storage/.

	Args:
	    cuit: CUIT del contribuyente.
	    mes: Mes a calcular. Default: mes actual.
	    anio: Año. Default: año actual.
	    con_deuda: Incluir deuda real en el PDF (requiere browser).

	Returns:
	    UnifiedResponse con ruta al PDF generado y cantidad de páginas.
	"""
	svc = ctx.request_context.lifespan_context
	token, sign = svc.get('ta_cache', (None, None))
	memory = svc.get('memory')

	if not token or not sign:
		return UnifiedResponse(
			status='error',
			error=ApiError(code='TA_NOT_AVAILABLE', cause='Ticket de Acceso no disponible'),
		).model_dump_json()

	now = datetime.now()
	mes = mes or now.month
	anio = anio or now.year

	browser = svc.get('browser')
	if con_deuda and browser is None:
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='BROWSER_NOT_CONFIGURED',
				cause='COMPOSIO_API_KEY no configurada',
				remediation='Agregar COMPOSIO_API_KEY en .env',
			),
		).model_dump_json()

	try:
		# 1. Consultar padrón
		padron_result = consultar_cuit(cuit, token, sign, REPRESENTANTE_CUIT)
		output = padron_result.to_output()
		if memory:
			memory.save_padron_result(cuit, padron_result.to_dict(), 'success')

		if output.errorConstancia:
			return UnifiedResponse(
				status='error',
				error=ApiError(
					code='CONSTANCIA_ERROR',
					cause='; '.join(output.errorConstancia.error),
				),
			).model_dump_json()

		# 2. Calcular calendario
		engine = svc['engine']
		calendario = engine.calcular(output, mes, anio)

		# 3. Browser extraction (opcional)
		deuda_output = None
		import asyncio

		if con_deuda and browser is not None:
			from agente_fiscal.adapters.browser import VencimientosDeudasTask

			estudio_clave = get_settings().credentials.clave_fiscal
			task = VencimientosDeudasTask(
				cuit=REPRESENTANTE_CUIT,
				clave=estudio_clave,
				cliente_cuit=cuit,
			)
			deuda_output = await asyncio.to_thread(browser.run_single, None, tasks=[task])
			if memory and deuda_output:
				if deuda_output.error:
					memory.save_extraction_result(cuit, 'deuda', {'error': deuda_output.error}, 'error')
				else:
					memory.save_extraction_result(cuit, 'deuda', {'status': 'success'}, 'success')

		# 4. Generar PDF
		pdf_gen = svc['pdf_gen']
		periodo_str = f'{anio:04d}-{mes:02d}'
		output_dir = Path('storage') / periodo_str

		pdf_path = pdf_gen.generar(
			nombre=cuit,
			cuit=cuit,
			vencimientos=calendario.vencimientos,
			mes=mes,
			anio=anio,
			observaciones=calendario.observaciones or None,
			deuda=deuda_output,
			output_dir=output_dir,
		)

		if memory:
			memory.save_pdf_sent(cuit, str(pdf_path), '', 'generated')

		# Count pages (approximate)
		pages = 1  # minimum
		if deuda_output and (deuda_output.deudas or deuda_output.facilidades or deuda_output.registro):
			pages = 7  # full pipeline page count

		return UnifiedResponse(
			status='success',
			result={
				'pdf_path': str(pdf_path),
				'pages': pages,
				'periodo': periodo_str,
			},
		).model_dump_json()

	except Exception as exc:
		if memory:
			memory.save_pipeline_error(cuit, 'mcp_report_pdf', str(exc))
		return UnifiedResponse(
			status='error',
			error=ApiError(code='PDF_ERROR', cause=str(exc)),
		).model_dump_json()
