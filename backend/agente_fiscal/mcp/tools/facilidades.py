"""MCP tool: extract_facilidades — extrae planes de pago.

Scope (HTTP): taxpayer:read
Requiere COMPOSIO_API_KEY configurada en .env.
"""

from __future__ import annotations

import asyncio

from mcp.server.fastmcp import Context

from agente_fiscal.adapters.browser.factory import build_browser_tasks
from agente_fiscal.config import REPRESENTANTE_CUIT
from agente_fiscal.config import get_settings
from agente_fiscal.mcp.server import mcp
from agente_fiscal.domain.models import ApiError, UnifiedResponse


@mcp.tool()
async def extract_facilidades(cuit: str, ctx: Context = None) -> str:
	"""Extraer los planes de pago (Mis Facilidades) de un contribuyente.

	Navega el sistema ARCA via browser automation para obtener los
	planes de pago activos e históricos del contribuyente.

	Args:
	    cuit: CUIT del contribuyente (11 dígitos).

	Returns:
	    UnifiedResponse con lista de FacilidadPlan.
	"""
	svc = ctx.request_context.lifespan_context
	browser = svc.get('browser')
	memory = svc.get('memory')

	if browser is None:
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='BROWSER_NOT_CONFIGURED',
				cause='COMPOSIO_API_KEY no configurada',
				remediation='Agregar COMPOSIO_API_KEY en .env',
			),
		).model_dump_json()

	estudio_clave = get_settings().credentials.clave_fiscal

	try:
		tasks = build_browser_tasks(
			cuit=REPRESENTANTE_CUIT,
			clave=estudio_clave,
			cliente_cuit=cuit,
			with_facilidades=True,
		)
		output = await asyncio.to_thread(browser.run_single, None, tasks=tasks)

		if output.error:
			if memory:
				memory.save_extraction_result(cuit, 'facilidades', {'error': output.error}, 'error')
			error_tag = 'BROWSER_TIMEOUT' if 'Timeout' in output.error else 'BROWSER_ERROR'
			return UnifiedResponse(
				status='error',
				error=ApiError(code=error_tag, cause=output.error),
			).model_dump_json()

		if memory:
			memory.save_extraction_result(cuit, 'facilidades', {'status': 'success'}, 'success')
		return UnifiedResponse(
			status='success',
			result={'facilidades': [f.model_dump() for f in output.facilidades]},
		).model_dump_json()

	except Exception as exc:
		if memory:
			memory.save_pipeline_error(cuit, 'mcp_facilidades', str(exc))
		return UnifiedResponse(
			status='error',
			error=ApiError(code='BROWSER_ERROR', cause=str(exc)),
		).model_dump_json()
