"""GET /v1/taxpayer/{cuit} + POST /v1/report — perfil y pipeline completo."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from fiscal_agent.api.deps import CERT_PATH, KEY_PATH, REPRESENTANTE_CUIT, get_engine, get_memory, get_pdf_gen, get_ta
from fiscal_agent.arca_ws import consultar_cuit
from fiscal_agent.config import get_settings
from fiscal_agent.models import (
	ApiError,
	AppConfig,
	ClientConfig,
	PadronA5Output,
	RulesOutput,
	UnifiedResponse,
)
from fiscal_agent.pipeline.service import PipelineService, _completar_cliente_desde_padron

router = APIRouter()


@router.get(
	'/v1/taxpayer/{cuit}',
	response_model=UnifiedResponse[PadronA5Output],
	summary='Consultar contribuyente en ARCA',
)
async def get_taxpayer(
	cuit: str,
):
	"""Obtiene el perfil completo de un contribuyente desde el Padrón A5 de ARCA.
	Incluye domicilio fiscal, actividades económicas, impuestos inscriptos y categoría.
	"""
	memory = get_memory()
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

	try:
		padron_result = consultar_cuit(cuit, token, sign, REPRESENTANTE_CUIT)
		output = padron_result.to_output()
		memory.save_padron_result(cuit, padron_result.to_dict(), 'success')
	except Exception as exc:
		memory.save_pipeline_error(cuit, 'padron_query', str(exc))
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='TAXPAYER_QUERY_FAILED',
				cause=str(exc),
				remediation='Verificar que el CUIT sea válido',
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

	return UnifiedResponse(
		status='success',
		result=output,
	)


class ReportRequest(BaseModel):
	"""Solicitud de pipeline fiscal completo."""

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
	with_deuda: bool = Field(
		default=False,
		description='Incluir extracción de deuda vía navegador',
		examples=[True],
	)
	with_facilidades: bool = Field(
		default=False,
		description='Incluir consulta de Mis Facilidades',
		examples=[False],
	)
	with_registro: bool = Field(
		default=False,
		description='Incluir consulta de Registro Tributario',
		examples=[False],
	)
	send_email: bool = Field(
		default=False,
		description='Enviar el reporte por email al cliente',
		examples=[False],
	)
	idempotency_key: Optional[str] = Field(
		default=None,
		description='Key de idempotencia',
		examples=['rpt-2026-06-abc123'],
	)


@router.post(
	'/v1/report',
	response_model=UnifiedResponse[dict],
	summary='Ejecutar pipeline fiscal completo',
)
async def report(
	request: ReportRequest,
):
	"""Ejecuta el pipeline fiscal completo para un CUIT y período:
	calcula calendario, genera PDF, extrae datos vía navegador y envía
	email si está configurado.
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

	# Build a minimal ClientConfig for the pipeline
	cliente = ClientConfig(cuit=request.cuit)
	try:
		cliente = _completar_cliente_desde_padron(cliente, token, sign, REPRESENTANTE_CUIT)
	except Exception as exc:
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='TAXPAYER_QUERY_FAILED',
				cause=str(exc),
			),
		)

	# Init engine + pdf
	engine = get_engine()
	pdf_gen = get_pdf_gen()

	# Browser (lazy import, solo si es necesario)
	browser = None
	usa_browser = request.with_deuda or request.with_facilidades or request.with_registro
	if usa_browser:
		creds = get_settings().credentials
		composio_key = creds.composio_api_key
		estudio_clave = creds.clave_fiscal
		if not composio_key or not estudio_clave:
			return UnifiedResponse(
				status='error',
				error=ApiError(
					code='BROWSER_CONFIG_MISSING',
					cause='Falta COMPOSIO_API_KEY o ESTUDIO_CLAVE_FISCAL en .env',
				),
			)
		from fiscal_agent.browser import ComposioBrowser

		browser = ComposioBrowser(
			composio_api_key=composio_key,
			estudio_cuit=REPRESENTANTE_CUIT,
			estudio_clave=estudio_clave,
		)

	# Embed the flags into a _procesar_cliente_pipeline compatible way
	# We build a minimal AppConfig for SMTP access
	from pathlib import Path
	import yaml

	config_raw = {}
	config_path = Path('clients.yaml')
	if config_path.exists():
		config_raw = yaml.safe_load(config_path.read_text())
		config = AppConfig(**config_raw) if config_raw.get('smtp') else None
	else:
		config = None

	memory = get_memory()
	svc = PipelineService(engine, pdf_gen, memory)
	result_obj = svc.run_pipeline(
		cliente=cliente,
		token=token,
		sign=sign,
		mes=request.mes,
		anio=request.anio,
		browser=browser,
		with_deuda=request.with_deuda,
		with_facilidades=request.with_facilidades,
		with_registro=request.with_registro,
		send_email=request.send_email,
		config=config,
	)
	resultado = result_obj.model_dump()

	if resultado.get('error'):
		return UnifiedResponse(
			status='error',
			error=ApiError(code='PIPELINE_FAILED', cause=resultado['error']),
		)

	next_actions = []
	if not request.send_email and resultado.get('pdf_path'):
		if cliente.email:
			next_actions.append('send_email')
		else:
			next_actions.append('configure_email')

	return UnifiedResponse(
		status='success',
		result={
			'pdf_path': str(resultado.get('pdf_path')) if resultado.get('pdf_path') else None,
			'email_sent': resultado.get('email', False),
			'ws_api': resultado.get('ws_api', False),
			'calendario': resultado.get('calendario', False),
		},
		next_actions=next_actions,
		human_approval_required=bool(next_actions),
	)
