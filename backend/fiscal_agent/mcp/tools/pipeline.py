"""MCP tool: run_pipeline — ejecuta pipeline fiscal completo.

Scope (HTTP): report:write
Ejecuta el pipeline completo: WS API → Rules Engine → Composio Browser → PDF → Email.
"""

from __future__ import annotations

import os
from datetime import datetime

from mcp.server.fastmcp import Context

from fiscal_agent.config import REPRESENTANTE_CUIT
from fiscal_agent.pipeline.service import PipelineService
from fiscal_agent.mcp.server import mcp
from fiscal_agent.domain.models import ApiError, ClientConfig, UnifiedResponse


@mcp.tool()
async def run_pipeline(
	cuit: str,
	mes: int | None = None,
	anio: int | None = None,
	with_deuda: bool = False,
	with_facilidades: bool = False,
	with_registro: bool = False,
	send_email: bool = False,
	ctx: Context = None,
) -> str:
	"""Ejecutar el pipeline fiscal completo para un contribuyente.

	El pipeline incluye: consulta al Padrón A5, cálculo de vencimientos,
	extracción de deuda/planes/registro (opcional vía browser), generación
	de PDF, y envío de email (opcional).

	Args:
	    cuit: CUIT del contribuyente.
	    mes: Mes a calcular (1-12). Default: mes actual.
	    anio: Año. Default: año actual.
	    with_deuda: Extraer deuda real vía browser.
	    with_facilidades: Extraer planes de pago vía browser.
	    with_registro: Extraer registro tributario vía browser.
	    send_email: Enviar email al cliente con el PDF.

	Returns:
	    UnifiedResponse con resultado del pipeline (calendario, PDF, email).
	"""
	lifespan_ctx = ctx.request_context.lifespan_context
	token, sign = lifespan_ctx.get('ta_cache', (None, None))

	if not token or not sign:
		return UnifiedResponse(
			status='error',
			error=ApiError(code='TA_NOT_AVAILABLE', cause='Ticket de Acceso no disponible'),
		).model_dump_json()

	now = datetime.now()
	mes = mes or now.month
	anio = anio or now.year

	browser = lifespan_ctx.get('browser')
	usa_browser = with_deuda or with_facilidades or with_registro
	if usa_browser and browser is None:
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='BROWSER_NOT_CONFIGURED',
				cause='COMPOSIO_API_KEY no configurada',
				remediation='Agregar COMPOSIO_API_KEY en .env',
			),
		).model_dump_json()

	try:
		cliente = ClientConfig(cuit=cuit)
		service = PipelineService(lifespan_ctx['engine'], lifespan_ctx['pdf_gen'], lifespan_ctx.get('memory'))
		result = service.run_pipeline(
			cliente=cliente,
			token=token,
			sign=sign,
			mes=mes,
			anio=anio,
			browser=browser,
			with_deuda=with_deuda,
			with_facilidades=with_facilidades,
			with_registro=with_registro,
			send_email=send_email,
			config=None,
		)

		return UnifiedResponse(
			status='success',
			result=result.model_dump(),
		).model_dump_json()

	except Exception as exc:
		return UnifiedResponse(
			status='error',
			error=ApiError(code='PIPELINE_ERROR', cause=str(exc)),
		).model_dump_json()
