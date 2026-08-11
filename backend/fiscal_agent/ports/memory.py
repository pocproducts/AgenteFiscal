"""Memory ports — abstraction over the fiscal memory/persistence layer."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fiscal_agent.domain.models import PipelineRun


@runtime_checkable
class MemoryWriter(Protocol):
	"""Writes observations/history for a CUIT."""

	def save_padron_result(self, cuit: str, padron_data: dict, status: str) -> None:
		"""Persist the WS ARCA padron lookup result for *cuit*."""
		...

	def save_extraction_result(self, cuit: str, extraction_type: str, data: dict, status: str) -> None:
		"""Persist a browser-extraction result (deuda, facilidades, registro)."""
		...

	def save_pdf_sent(self, cuit: str, pdf_path: str, email_sent_to: str, status: str) -> None:
		"""Record that a PDF was generated and emailed for *cuit*."""
		...

	def save_pipeline_run(self, cuit: str, run: PipelineRun) -> None:
		"""Persist a ``PipelineRun`` observation under *cuit*'s session."""
		...

	def save_pipeline_error(self, cuit: str, stage: str, error_message: str) -> None:
		"""Record a pipeline error for *cuit* at a specific *stage*."""
		...

	def save_observation(self, cuit: str, obs_type: str, content: str, *, title: str = '', status: str = '') -> None:
		"""Lower-level generic observation write."""
		...


@runtime_checkable
class MemoryReader(Protocol):
	"""Reads history/observations for a CUIT."""

	def get_padron_history(self, cuit: str, limit: int = 3) -> list[dict]:
		"""Return recent padron observations for *cuit*."""
		...

	def get_extraction_history(self, cuit: str, extraction_type: str, limit: int = 3) -> list[dict]:
		"""Return recent extraction observations for *cuit*."""
		...

	def get_pipeline_history(self, cuit: str, limit: int = 10) -> list[dict]:
		"""Return recent pipeline run observations for *cuit*."""
		...

	def get_last_error(self, cuit: str, stage: str) -> dict | None:
		"""Return the last error observation for *cuit* at *stage*."""
		...


@runtime_checkable
class MemoryPort(MemoryReader, MemoryWriter, Protocol):
	"""Full read/write contract of the fiscal memory client."""

	def is_available(self) -> bool:
		"""Whether the backing store (Engram/Redis) is reachable."""
		...