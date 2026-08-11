"""Detect fiscal query intent and extract CUIT from natural language messages.

Usage::

    >>> from fiscal_agent.chat.intent_router import detect, Intent
    >>> intent, cuit, params = detect('reporte completo CUIT 30716395541')
    >>> intent
    <Intent.REPORTE_COMPLETO: 2>
    >>> cuit
    '30716395541'
"""

from __future__ import annotations

import re
from enum import Enum


class Intent(Enum):
	"""Supported fiscal query intents for the chat interface."""

	UNKNOWN = 0
	TAXPAYER_QUERY = 1
	REPORTE_COMPLETO = 2


# CUIT: 11 dígitos, opcionalmente con guiones (XX-XXXXXXXX-X)
_CUIT_RE = re.compile(r'\b(\d{2}-?\d{8}-?\d)\b')


def detect(message: str) -> tuple[Intent, str | None, dict]:
	"""Detect intent and extract CUIT from a natural language message.

	Args:
		message: Raw user message (e.g. ``'reporte CUIT 30716395541'``).

	Returns:
		Tuple of ``(intent, cuit_or_none, params_dict)``.
	"""
	match = _CUIT_RE.search(message)
	cuit = match.group(1).replace('-', '') if match else None

	msg = message.lower()

	# ── Reporte completo (pipeline completo: padrón + calendario + browser + PDF) ─
	if cuit and any(kw in msg for kw in ['reporte', 'informe', 'completo', 'todo', 'resumen', 'full', 'pipeline']):
		return Intent.REPORTE_COMPLETO, cuit, {}

	# ── Consulta de datos del contribuyente ─────────────────────────────────────
	if cuit and any(kw in msg for kw in ['consulta', 'cuit', 'padron', 'datos', 'quien', 'quién']):
		return Intent.TAXPAYER_QUERY, cuit, {}

	return Intent.UNKNOWN, cuit, {}
