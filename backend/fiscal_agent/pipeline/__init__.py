"""Pipeline service — extracted from CLI for shared use across CLI, API, and MCP."""

from fiscal_agent.pipeline.models import PipelineResult
from fiscal_agent.pipeline.service import PipelineService, _completar_cliente_desde_padron

__all__ = [
	'PipelineService',
	'PipelineResult',
	'_completar_cliente_desde_padron',
]
