"""MCP tool: get_calendar — calcula calendario de vencimientos.

Scope (HTTP): calendar:read
"""

from __future__ import annotations

from datetime import datetime

from mcp.server.fastmcp import Context

from fiscal_agent.arca_ws import consultar_cuit
from fiscal_agent.config import REPRESENTANTE_CUIT
from fiscal_agent.mcp.server import mcp
from fiscal_agent.models import ApiError, UnifiedResponse


@mcp.tool()
async def get_calendar(
	cuit: str,
	mes: int | None = None,
	anio: int | None = None,
	provincias: list[str] | None = None,
	ctx: Context = None,
) -> str:
	"""Calcular el calendario de vencimientos fiscales para un contribuyente.

	Consulta el Padrón A5 de ARCA y aplica las reglas fiscales para generar
	la lista de vencimientos del período.

	Args:
	    cuit: CUIT del contribuyente (11 dígitos).
	    mes: Mes a calcular (1-12). Default: mes actual.
	    anio: Año (ej: 2026). Default: año actual.
	    provincias: Provincias donde opera (para Convenio Multilateral).

	Returns:
	    UnifiedResponse con RulesOutput (vencimientos + observaciones).
	"""
	svc = ctx.request_context.lifespan_context
	token, sign = svc.get('ta_cache', (None, None))

	if not token or not sign:
		return UnifiedResponse(
			status='error',
			error=ApiError(code='TA_NOT_AVAILABLE', cause='Ticket de Acceso no disponible'),
		).model_dump_json()

	now = datetime.now()
	mes = mes or now.month
	anio = anio or now.year
	provincias = provincias or []

	try:
		padron_result = consultar_cuit(cuit, token, sign, REPRESENTANTE_CUIT)
		output = padron_result.to_output()

		if output.errorConstancia:
			return UnifiedResponse(
				status='error',
				error=ApiError(
					code='CONSTANCIA_ERROR',
					cause='; '.join(output.errorConstancia.error),
				),
			).model_dump_json()

		engine = svc['engine']
		result = engine.calcular(output, mes, anio, provincias=provincias)

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
			error=ApiError(code='ARCA_ERROR', cause=str(exc)),
		).model_dump_json()
