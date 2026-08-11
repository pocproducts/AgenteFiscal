"""Task system — unified protocol for all operations (browser, API, SOAP)."""

from fiscal_agent.tasks.base import ApiTask, BaseTask, TaskResult
from fiscal_agent.tasks.padron import PadronApiTask

__all__ = [
	'ApiTask',
	'BaseTask',
	'PadronApiTask',
	'TaskResult',
]
