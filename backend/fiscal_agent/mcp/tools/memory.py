"""MCP tools: consultar y registrar memoria fiscal.

Tools:
  - ``get_memory_history(cuit, obs_type?, limit)``: leer observaciones de un CUIT
  - ``save_memory_observation(cuit, title, type, content)``: crear observación
"""

from __future__ import annotations

from mcp.server.fastmcp import Context

from fiscal_agent.mcp.server import mcp
from fiscal_agent.domain.models import ApiError, UnifiedResponse


@mcp.tool()
async def get_memory_history(
	cuit: str,
	obs_type: str | None = None,
	limit: int = 10,
	ctx: Context = None,
) -> str:
	"""Consultar el historial de memoria fiscal de un contribuyente.

	Retorna las observaciones registradas para el CUIT, opcionalmente
	filtradas por tipo (padron, deuda, facilidades, registro, error, etc.).

	Args:
		cuit: CUIT del contribuyente.
		obs_type: Filtrar por tipo de observación (opcional).
		limit: Cantidad máxima de observaciones a retornar (default: 10).

	Returns:
		UnifiedResponse JSON string con las observaciones.
	"""
	memory = ctx.request_context.lifespan_context.get('memory')
	if memory is None:
		return UnifiedResponse(
			status='error',
			error=ApiError(code='MEMORY_UNAVAILABLE', cause='FiscalMemoryClient no disponible en el contexto'),
		).model_dump_json()

	try:
		if obs_type:
			observations = memory.get_extraction_history(cuit, obs_type, limit)
		else:
			observations = memory.get_pipeline_history(cuit, limit)

		return UnifiedResponse(
			status='success',
			result=observations,
		).model_dump_json()
	except Exception as exc:
		return UnifiedResponse(
			status='error',
			error=ApiError(code='MEMORY_QUERY_FAILED', cause=str(exc)),
		).model_dump_json()


@mcp.tool()
async def save_memory_observation(
	cuit: str,
	title: str,
	type: str = 'generic',  # noqa: A002
	content: str = '',
	ctx: Context = None,
) -> str:
	"""Guardar una observación en la memoria fiscal de un contribuyente.

	Crea una nueva entrada en Engram para el CUIT con el título, tipo y
	contenido especificados. El contenido debe ser Markdown estructurado.

	Args:
		cuit: CUIT del contribuyente.
		title: Título descriptivo de la observación.
		type: Tipo de observación (padron, deuda, facilidades, error, etc.).
		content: Contenido Markdown (máximo 10 KB).

	Returns:
		UnifiedResponse JSON string confirmando la creación.
	"""
	memory = ctx.request_context.lifespan_context.get('memory')
	if memory is None:
		return UnifiedResponse(
			status='error',
			error=ApiError(code='MEMORY_UNAVAILABLE', cause='FiscalMemoryClient no disponible en el contexto'),
		).model_dump_json()

	try:
		# Validate content length (same limit as MemoryObserveRequest)
		if len(content) > 10_240:
			return UnifiedResponse(
				status='error',
				error=ApiError(code='CONTENT_TOO_LARGE', cause=f'Content excede 10 KB ({len(content)} bytes)'),
			).model_dump_json()

		memory.save_observation(cuit, title, type, content)

		return UnifiedResponse(
			status='success',
			result={'cuit': cuit, 'type': type, 'title': title},
		).model_dump_json()
	except Exception as exc:
		return UnifiedResponse(
			status='error',
			error=ApiError(code='MEMORY_SAVE_FAILED', cause=str(exc)),
		).model_dump_json()
