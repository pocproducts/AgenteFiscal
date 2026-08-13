"""REST endpoints for memory operations — consultar y registrar observaciones.

Endpoints:
- ``GET /v1/memory/{cuit}`` — listar observaciones de un CUIT
- ``GET /v1/memory/{cuit}/{obs_type}`` — filtrar por tipo
- ``POST /v1/memory/observe`` — crear una nueva observación

Todos usan ``asyncio.to_thread`` para el bridge
sync→async con ``FiscalMemoryClient``.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from agente_fiscal.api.deps import get_memory
from agente_fiscal.adapters.memory import FiscalMemoryClient
from agente_fiscal.adapters.memory.models import MemoryObserveRequest
from agente_fiscal.domain.models import ApiError, UnifiedResponse

router = APIRouter()


def _validar_cuit(cuit: str) -> str | None:
	"""Validar formato de CUIT: 11 dígitos numéricos.

	Returns:
		``None`` si es válido, o un mensaje de error si no.
	"""
	if len(cuit) != 11 or not cuit.isdigit():
		return 'El CUIT debe tener exactamente 11 dígitos numéricos'
	return None


@router.get(
	'/v1/memory/{cuit}',
	response_model=UnifiedResponse[list],
	summary='Listar observaciones de un CUIT',
)
async def get_memory_history(
	cuit: str,
	limit: int = 10,
) -> UnifiedResponse[list]:
	"""Retorna las últimas observaciones de memoria fiscal para *cuit*.

	Incluye eventos de todo tipo: padrón, deuda, facilidades, registro,
	errores, PDFs enviados, etc. Los resultados vienen ordenados del más
	reciente al más antiguo (según Engram).
	"""
	if error := _validar_cuit(cuit):
		return UnifiedResponse(
			status='error',
			error=ApiError(code='INVALID_CUIT', cause=error),
		)

	memory: FiscalMemoryClient = get_memory()
	try:
		observations = await asyncio.to_thread(memory.get_pipeline_history, cuit, limit)
		return UnifiedResponse(status='success', result=observations)
	except Exception as exc:
		return UnifiedResponse(
			status='error',
			error=ApiError(code='MEMORY_QUERY_FAILED', cause=str(exc)),
		)


@router.get(
	'/v1/memory/{cuit}/{obs_type}',
	response_model=UnifiedResponse[list],
	summary='Filtrar observaciones por tipo',
)
async def get_memory_by_type(
	cuit: str,
	obs_type: str,
	limit: int = 10,
) -> UnifiedResponse[list]:
	"""Retorna observaciones de *cuit* filtradas por *obs_type*.

	Tipos comunes: ``padron``, ``deuda``, ``facilidades``, ``registro``,
	``pdf``, ``error``.
	"""
	if error := _validar_cuit(cuit):
		return UnifiedResponse(
			status='error',
			error=ApiError(code='INVALID_CUIT', cause=error),
		)

	memory: FiscalMemoryClient = get_memory()
	try:
		observations = await asyncio.to_thread(memory.get_extraction_history, cuit, obs_type, limit)
		return UnifiedResponse(status='success', result=observations)
	except Exception as exc:
		return UnifiedResponse(
			status='error',
			error=ApiError(code='MEMORY_QUERY_FAILED', cause=str(exc)),
		)


@router.post(
	'/v1/memory/observe',
	response_model=UnifiedResponse[dict],
	status_code=201,
	summary='Registrar una observación',
	responses={
		422: {'description': 'Error de validación', 'model': UnifiedResponse[ApiError]},
	},
)
async def observe(
	body: MemoryObserveRequest,
) -> UnifiedResponse[dict]:
	"""Crea una nueva observación en la memoria fiscal de *cuit*.

	El ``content`` debe ser Markdown estructurado (máximo 10 KB).
	El ``type`` clasifica la observación (padron, deuda, error, etc.).
	"""
	memory: FiscalMemoryClient = get_memory()

	if not memory.is_available():
		return UnifiedResponse(
			status='error',
			error=ApiError(code='MEMORY_UNAVAILABLE', cause='Engram no está disponible'),
		)

	try:
		await asyncio.to_thread(
			memory.save_observation,
			body.cuit,
			body.title,
			body.type,
			body.content,
		)
		return UnifiedResponse(
			status='success',
			result={'cuit': body.cuit, 'type': body.type, 'title': body.title},
		)
	except Exception as exc:
		return UnifiedResponse(
			status='error',
			error=ApiError(code='MEMORY_OBSERVE_FAILED', cause=str(exc)),
		)
