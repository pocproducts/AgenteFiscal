"""Typed pipeline output model."""

from __future__ import annotations

from pydantic import BaseModel


class PipelineResult(BaseModel):
	"""Typed pipeline output — field names match the existing dict.

	``model_dump()`` produces a dict with EXACTLY the same keys
	as the raw dict previously returned by ``_procesar_cliente_pipeline()``.
	"""

	cliente: str
	cuit: str
	ws_api: bool = False
	calendario: bool = False
	pdf: bool = False
	pdf_path: str | None = None
	email: bool = False
	error: str | None = None
	pdf_preview: str | None = None


class ProposalOutcome(BaseModel):
	"""Result of the proposal phase — pipeline result WITHOUT side effects.

	``PipelineService.run_proposal`` computes everything up to (but excluding)
	the outbound steps (email) and reports which side effects it WOULD run.
	The unattended worker parks the run in ``waiting_approval`` when
	``pending_actions`` is non-empty; offline callers (CLI/MCP/sync API)
	execute them immediately because the operator IS the human.
	"""

	result: PipelineResult
	pending_actions: list[str] = []
