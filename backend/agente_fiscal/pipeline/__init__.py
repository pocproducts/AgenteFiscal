"""Pipeline service — extracted from CLI for shared use across CLI, API, and MCP."""

from agente_fiscal.pipeline.models import PipelineResult
from agente_fiscal.pipeline.service import PipelineService, _completar_cliente_desde_padron

__all__ = [
	'PipelineService',
	'PipelineResult',
	'_completar_cliente_desde_padron',
]
