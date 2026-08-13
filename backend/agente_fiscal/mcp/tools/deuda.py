"""MCP tool: extract_deuda — extrae deuda real vía Composio Browser.

Scope (HTTP): taxpayer:read
Requires COMPOSIO_API_KEY configurada en .env.
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
async def extract_deuda(cuit: str, ctx: Context = None) -> str:
	"""Extraer la deuda real de un contribuyente desde ctacte.cloud vía browser automation.

	Requiere COMPOSIO_API_KEY configurada en el entorno. La extracción
	navega el sistema ARCA usando las credenciales del estudio contable.

	Args:
	    cuit: CUIT del contribuyente (11 dígitos).

	Returns:
	    UnifiedResponse con DeudaOutput (vencimientos + deudas detalladas).
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
			with_deuda=True,
		)
		output = await asyncio.to_thread(browser.run_single, None, tasks=tasks)

		if output.error:
			if memory:
				memory.save_extraction_result(cuit, 'deuda', {'error': output.error}, 'error')
			error_tag = 'BROWSER_TIMEOUT' if 'Timeout' in output.error else 'BROWSER_ERROR'
			return UnifiedResponse(
				status='error',
				error=ApiError(code=error_tag, cause=output.error),
			).model_dump_json()

		if memory:
			memory.save_extraction_result(cuit, 'deuda', {'status': 'success'}, 'success')
		return UnifiedResponse(
			status='success',
			result=output.model_dump(),
		).model_dump_json()

	except Exception as exc:
		if memory:
			memory.save_pipeline_error(cuit, 'mcp_deuda', str(exc))
		return UnifiedResponse(
			status='error',
			error=ApiError(code='BROWSER_ERROR', cause=str(exc)),
		).model_dump_json()
