"""MCP tool: match_rentas_cordoba — evalúa integración con Rentas Córdoba.

Scope (HTTP): calendar:read
Determina si un contribuyente con Convenio Multilateral IIBB
requiere integrarse con Rentas Córdoba.
"""

from __future__ import annotations

from mcp.server.fastmcp import Context

from fiscal_agent.arca_ws import consultar_cuit
from fiscal_agent.config import REPRESENTANTE_CUIT
from fiscal_agent.mcp.server import mcp
from fiscal_agent.models import ApiError, UnifiedResponse


@mcp.tool()
async def match_rentas_cordoba(
	cuit: str,
	provincias: list[str] | None = None,
	ctx: Context = None,
) -> str:
	"""Evaluar si un contribuyente requiere integración con Rentas Córdoba.

	Analiza si el contribuyente tiene Convenio Multilateral IIBB y
	está inscripto en IIBB Córdoba, lo que requeriría integración
	con el sistema Rentas Córdoba para consultar deuda provincial.

	Args:
	    cuit: CUIT del contribuyente.
	    provincias: Provincias donde opera el contribuyente.

	Returns:
	    UnifiedResponse con RentasCordobaMatching.
	"""
	svc = ctx.request_context.lifespan_context
	token, sign = svc.get('ta_cache', (None, None))

	if not token or not sign:
		return UnifiedResponse(
			status='error',
			error=ApiError(code='TA_NOT_AVAILABLE', cause='Ticket de Acceso no disponible'),
		).model_dump_json()

	provincias = provincias or []

	try:
		padron_result = consultar_cuit(cuit, token, sign, REPRESENTANTE_CUIT)
		output = padron_result.to_output()

		if output.errorConstancia:
			return UnifiedResponse(
				status='error',
				error=ApiError(
					code='CUIT_NOT_FOUND',
					cause='; '.join(output.errorConstancia.error),
				),
			).model_dump_json()

		from fiscal_agent.matching import evaluar_rentas_cordoba

		impuestos_ws = output.regimenGeneral.impuestos if output.regimenGeneral else None
		result = evaluar_rentas_cordoba(
			provincias=provincias,
			impuestos_ws=impuestos_ws,
			registro_impuestos=None,
		)

		return UnifiedResponse(
			status='success',
			result=result.model_dump(),
		).model_dump_json()

	except ValueError as exc:
		return UnifiedResponse(
			status='error',
			error=ApiError(code='INVALID_CUIT', cause=str(exc)),
		).model_dump_json()
	except Exception as exc:
		return UnifiedResponse(
			status='error',
			error=ApiError(code='MATCHING_ERROR', cause=str(exc)),
		).model_dump_json()
