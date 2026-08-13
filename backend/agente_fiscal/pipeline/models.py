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
