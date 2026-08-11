"""POST /v1/calendar — generar calendario fiscal para un CUIT + período."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fiscal_agent.api.deps import REPRESENTANTE_CUIT, get_engine, get_ta
from fiscal_agent.adapters.arca_ws import consultar_cuit
from fiscal_agent.domain.models import ApiError, RulesOutput, UnifiedResponse

router = APIRouter()


class CalendarRequest(BaseModel):
	"""Solicitud de generación de calendario fiscal."""

	cuit: str = Field(
		description='CUIT del contribuyente sin guiones',
		examples=['20301234561'],
	)
	mes: int = Field(
		description='Mes del período fiscal (1-12)',
		ge=1,
		le=12,
		examples=[6],
	)
	anio: int = Field(
		description='Año del período fiscal (YYYY)',
		ge=2020,
		le=2099,
		examples=[2026],
	)
	idempotency_key: Optional[str] = Field(
		default=None,
		description='Key de idempotencia para evitar procesamiento duplicado',
		examples=['cal-2026-06-abc123'],
	)


@router.post(
	'/v1/calendar',
	response_model=UnifiedResponse[RulesOutput],
	summary='Generar calendario fiscal',
)
async def calendar(
	request: CalendarRequest,
):
	"""Genera el calendario fiscal para un CUIT y período determinados.
	Consulta el Padrón A5 de ARCA y aplica las reglas de vencimientos fiscales.
	"""
	token, sign = get_ta()
	if not token or not sign:
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='TA_UNAVAILABLE',
				cause='No se pudo obtener Ticket de Acceso de ARCA',
				remediation='Verificar certificados en .certificados-arca/',
			),
		)

	# 1. Consultar padrón A5
	try:
		padron_result = consultar_cuit(request.cuit, token, sign, REPRESENTANTE_CUIT)
		output = padron_result.to_output()
	except Exception as exc:
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='TAXPAYER_QUERY_FAILED',
				cause=str(exc),
				remediation='Verificar que el CUIT sea válido y que el servicio ARCA esté disponible',
			),
		)

	if output.errorConstancia:
		errors = '; '.join(output.errorConstancia.error)
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='TAXPAYER_NOT_FOUND',
				cause=errors,
				remediation='Verificar el CUIT consultado',
			),
		)

	# 2. Calcular calendario
	engine = get_engine()
	try:
		calendario = engine.calcular(output, request.mes, request.anio)
	except Exception as exc:
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='CALENDAR_FAILED',
				cause=str(exc),
				remediation='Error interno del motor de reglas',
			),
		)

	return UnifiedResponse(
		status='success',
		result=calendario,
	)
