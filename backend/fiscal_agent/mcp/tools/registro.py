"""MCP tool: extract_registro — extrae registro tributario.

Scope (HTTP): taxpayer:read
Requiere COMPOSIO_API_KEY configurada en .env.
"""

from __future__ import annotations

import asyncio

from mcp.server.fastmcp import Context

from fiscal_agent.browser.factory import build_browser_tasks
from fiscal_agent.config import REPRESENTANTE_CUIT
from fiscal_agent.config import get_settings
from fiscal_agent.mcp.server import mcp
from fiscal_agent.models import ApiError, UnifiedResponse


@mcp.tool()
async def extract_registro(cuit: str, ctx: Context = None) -> str:
	"""Extraer el registro tributario de un contribuyente desde ARCA.

	Obtiene domicilios, actividades económicas, impuestos inscriptos,
	y puntos de venta registrados.

	Args:
	    cuit: CUIT del contribuyente (11 dígitos).

	Returns:
	    UnifiedResponse con RegistroOutput.
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
			with_registro=True,
		)
		output = await asyncio.to_thread(browser.run_single, None, tasks=tasks)

		if output.error:
			if memory:
				memory.save_extraction_result(cuit, 'registro', {'error': output.error}, 'error')
			error_tag = 'BROWSER_TIMEOUT' if 'Timeout' in output.error else 'BROWSER_ERROR'
			return UnifiedResponse(
				status='error',
				error=ApiError(code=error_tag, cause=output.error),
			).model_dump_json()

		if memory:
			memory.save_extraction_result(cuit, 'registro', {'status': 'success'}, 'success')
		registro = output.registro
		return UnifiedResponse(
			status='success',
			result=registro.model_dump() if registro else {},
		).model_dump_json()

	except Exception as exc:
		if memory:
			memory.save_pipeline_error(cuit, 'mcp_registro', str(exc))
		return UnifiedResponse(
			status='error',
			error=ApiError(code='BROWSER_ERROR', cause=str(exc)),
		).model_dump_json()
