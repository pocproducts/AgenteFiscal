"""Base task protocol — unified interface for all system operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TaskResult:
	"""Compartido por BrowserTask y ApiTask."""

	task_name: str
	success: bool
	raw_output: str = ''
	parsed_data: dict = field(default_factory=dict)
	error: Optional[str] = None
	arca_error: Optional[str] = None  # solo BrowserTask
	task_id: Optional[str] = None  # solo BrowserTask


class BaseTask(ABC):
	"""Protocolo unificado para toda task del sistema."""

	name: str = ''
	timeout: int = 300

	def execute(self, context: dict) -> TaskResult:
		"""Ejecuta la operación. Llamada bloqueante.

		BrowserTask subclasses son ejecutadas externamente vía
		ComposioBrowser y NO implementan este método. ApiTask
		subclasses DEBEN overridearlo.
		"""
		raise NotImplementedError(
			f'{type(self).__name__} does not implement execute(). BrowserTask subclasses execute via ComposioBrowser.'
		)

	def parse_output(self, raw: Any) -> dict:
		"""Parseo default: identidad."""
		return raw if isinstance(raw, dict) else {'_raw': str(raw)}


class ApiTask(BaseTask):
	"""Task síncrona sin Composio (SOAP/REST directo)."""

	needs_ta: bool = False
	needs_certs: bool = False

	@abstractmethod
	def execute(self, context: dict) -> TaskResult:
		"""Ejecuta la operación síncrona. ApiTask subclasses DEBEN implementarlo."""
		...
