"""MCP tool: get_taxpayer — consulta datos del contribuyente.

Scope (HTTP): taxpayer:read
"""

from __future__ import annotations

from mcp.server.fastmcp import Context

from fiscal_agent.arca_ws import consultar_cuit
from fiscal_agent.config import REPRESENTANTE_CUIT
from fiscal_agent.mcp.server import mcp
from fiscal_agent.models import ApiError, UnifiedResponse


@mcp.tool()
async def get_taxpayer(cuit: str, ctx: Context = None) -> str:
	"""Consultar los datos de un contribuyente en el Padrón A5 de ARCA.

	Devuelve información completa: datos generales, domicilio fiscal,
	impuestos inscriptos, actividades económicas, y régimen.

	Args:
	    cuit: CUIT del contribuyente (11 dígitos).

	Returns:
	    UnifiedResponse con PadronA5Output.
	"""
	svc = ctx.request_context.lifespan_context
	token, sign = svc.get('ta_cache', (None, None))

	if not token or not sign:
		return UnifiedResponse(
			status='error',
			error=ApiError(code='TA_NOT_AVAILABLE', cause='Ticket de Acceso no disponible'),
		).model_dump_json()

	try:
		result = consultar_cuit(cuit, token, sign, REPRESENTANTE_CUIT)
		output = result.to_output()

		if output.errorConstancia:
			return UnifiedResponse(
				status='error',
				error=ApiError(
					code='CUIT_NOT_FOUND',
					cause='; '.join(output.errorConstancia.error),
				),
			).model_dump_json()

		output_dict = result.to_dict()

		return UnifiedResponse(
			status='success',
			result=output_dict,
		).model_dump_json()

	except ValueError as exc:
		return UnifiedResponse(
			status='error',
			error=ApiError(code='INVALID_CUIT', cause=str(exc)),
		).model_dump_json()
	except Exception as exc:
		return UnifiedResponse(
			status='error',
			error=ApiError(code='ARCA_ERROR', cause=str(exc)),
		).model_dump_json()
