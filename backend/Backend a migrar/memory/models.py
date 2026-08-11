"""Pydantic models for the memory subsystem — observations, queries, and TenantContext.

All models use Pydantic v2 with strict validation. Designed for best-effort
semantics: ``TenantContext`` fields default to ``None``/``[]`` so partial
data is always representable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MemoryObservation(BaseModel):
	"""A single fiscal memory observation persisted in Engram for a CUIT.

	Each observation represents one pipeline event (padron lookup, extraction,
	error, PDF sent, etc.) stored in the CUIT's Engram session.
	"""

	id: int | None = None
	cuit: str
	title: str
	type: str
	content: str
	created_at: datetime | None = None


class MemoryQueryRequest(BaseModel):
	"""Request to query memory observations for a CUIT.

	Args:
		cuit: CUIT del contribuyente.
		obs_type: Optional filter by observation type (padron, deuda, etc.).
		limit: Max observations to return (default 10).
	"""

	cuit: str
	obs_type: str | None = None
	limit: int = Field(default=10, ge=1, le=100)


class MemoryObserveRequest(BaseModel):
	"""Request to persist a new observation in Engram.

	Args:
		cuit: CUIT del contribuyente (11 dígitos).
		title: Título descriptivo de la observación.
		type: Tipo de observación (padron, deuda, facilidades, error, etc.).
		content: Contenido Markdown estructurado (máximo 10 KB).
	"""

	cuit: str = Field(min_length=11, max_length=11)
	title: str = Field(min_length=1)
	type: str = Field(default='generic')
	content: str = Field(max_length=10_240)  # 10 KB max


class MemoryQueryResponse(BaseModel):
	"""Response envelope for memory queries.

	Args:
		observations: List of matching observations as raw dicts.
		total: Total number of observations returned.
		cuit: CUIT consultado.
	"""

	observations: list[dict] = Field(default_factory=list)
	total: int = 0
	cuit: str = ''


class TenantContext(BaseModel):
	"""Contexto fiscal completo de un CUIT — best-effort, puede tener campos ``None``.

	Cada campo representa una fuente de datos fiscal. ``build_context()``
	puebla cada fuente secuencialmente, tolerando fallos parciales. Si una
	fuente falla, su campo queda en ``None``/``[]`` y el error se registra
	en ``ultimo_error``.
	"""

	padron: Any | None = None  # PadronA5Output o dict
	deuda: list[dict] = Field(default_factory=list)
	facilidades: list[dict] = Field(default_factory=list)
	registro: Any | None = None  # RegistroOutput o dict
	calendario: Any | None = None  # RulesOutput o dict
	rentas_matching: Any | None = None  # RentasCordobaMatching o dict
	memoria_historica: list[dict] = Field(default_factory=list)
	ultimo_error: dict | None = None
	resumen_ejecutivo: str = ''


__all__ = [
	'MemoryObservation',
	'MemoryObserveRequest',
	'MemoryQueryRequest',
	'MemoryQueryResponse',
	'TenantContext',
]
