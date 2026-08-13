"""Task system — unified protocol for all operations (browser, API, SOAP)."""

from agente_fiscal.adapters.tasks.base import ApiTask, BaseTask, TaskResult
from agente_fiscal.adapters.tasks.padron import PadronApiTask

__all__ = [
	'ApiTask',
	'BaseTask',
	'PadronApiTask',
	'TaskResult',
]
