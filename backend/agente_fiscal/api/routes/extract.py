"""POST /v1/extract — extraer datos vía Composio Browser."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agente_fiscal.api.deps import REPRESENTANTE_CUIT, get_memory
from agente_fiscal.config import get_settings
from agente_fiscal.domain.models import ApiError, DeudaOutput, UnifiedResponse
from agente_fiscal.features import integration_enabled

router = APIRouter()


def _browser_disabled_error() -> HTTPException:
	"""Clean 503 when the browser integration is disabled (kill-switch)."""
	return HTTPException(
		status_code=503,
		detail=UnifiedResponse(
			status='error',
			error=ApiError(
				code='INTEGRATION_DISABLED',
				cause='La integración de browser (Composio) está deshabilitada. Activá BROWSER_ENABLED=true para habilitarla',
			),
		).model_dump(),
	)


class ExtractRequest(BaseModel):
	"""Solicitud de extracción de datos vía navegador."""

	cuit: str = Field(
		description='CUIT del contribuyente sin guiones',
		examples=['20301234561'],
	)
	tasks: List[str] = Field(
		description='Tareas a ejecutar: "deuda", "facilidades", "registro"',
		examples=[['deuda', 'facilidades']],
	)
	idempotency_key: Optional[str] = Field(
		default=None,
		description='Key de idempotencia',
		examples=['ext-2026-06-abc123'],
	)


@router.post(
	'/v1/extract',
	response_model=UnifiedResponse[DeudaOutput],
	summary='Extraer datos por navegador automatizado',
)
async def extract(
	request: ExtractRequest,
):
	"""Extrae datos del contribuyente usando navegador automatizado (Composio).
	Soporta: deuda (ctacte.cloud), facilidades (Mis Facilidades) y registro (RUT).
	"""
	if not integration_enabled('browser'):
		raise _browser_disabled_error()

	cuit = request.cuit
	creds = get_settings().credentials
	estudio_clave = creds.clave_fiscal
	memory = get_memory()

	from agente_fiscal.adapters.browser.provider import build_browser_provider
	from agente_fiscal.adapters.browser import FacilidadesTask, RegistroTask, VencimientosDeudasTask
	from agente_fiscal.domain.models import ClientConfig

	browser = build_browser_provider()
	if browser is None:
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='COMPOSIO_KEY_MISSING',
				cause='COMPOSIO_API_KEY no configurada en .env',
			),
		)

	# Build task list from request
	available_tasks = {
		'deuda': VencimientosDeudasTask,
		'facilidades': FacilidadesTask,
		'registro': RegistroTask,
	}

	task_names_run: list[str] = []
	task_instances = []
	for task_name in request.tasks:
		task_cls = available_tasks.get(task_name)
		if task_cls is None:
			return UnifiedResponse(
				status='error',
				error=ApiError(
					code='INVALID_TASK',
					cause=f'Task desconocida: {task_name}',
					remediation='Usar: deuda, facilidades, registro',
				),
			)
		task_names_run.append(task_name)
		task_instances.append(
			task_cls(
				cuit=REPRESENTANTE_CUIT,
				clave=estudio_clave,
				cliente_cuit=cuit,
			)
		)

	cliente = ClientConfig(cuit=cuit)

	try:
		deuda_output = browser.run_single(cliente, tasks=task_instances)
	except Exception as exc:
		memory.save_pipeline_error(cuit, 'browser_extract', str(exc))
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='BROWSER_EXTRACTION_FAILED',
				cause=str(exc),
				remediation='Verificar que Composio esté disponible y las credenciales sean válidas',
			),
		)

	if deuda_output.error:
		for t in task_names_run:
			memory.save_extraction_result(cuit, t, {'error': deuda_output.error}, 'error')
		error_tag = 'TIMEOUT' if 'Timeout' in deuda_output.error else 'EXTRACTION_ERROR'
		return UnifiedResponse(
			status='error',
			error=ApiError(code=error_tag, cause=deuda_output.error),
		)

	# Save each extraction type to memory
	for t in task_names_run:
		memory.save_extraction_result(cuit, t, {'status': 'success'}, 'success')

	return UnifiedResponse(status='success', result=deuda_output)
