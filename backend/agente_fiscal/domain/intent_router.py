"""Detect fiscal query intent and extract CUIT from natural language messages.

Usage::

    >>> from agente_fiscal.chat.intent_router import detect, Intent
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
	SISTEMA_REGISTRAL = 3
	DEUDA_VENCIMIENTOS = 4
	MIS_FACILIDADES = 5
	RENTAS_CORDOBA = 6
	CONSULTA_ARCA = 7
	CALENDARIO_VENCIMIENTOS_ARCA = 8


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

	# ── Browser tools (Phase-1 + Phase-2) — prioridad sobre REPORTE_COMPLETO ──
	# Orden de chequeo (design D. Intent Router): sistemaregistral →
	# deudavencimientos → calendariovencimientosarca → misfacilidades →
	# rentascordoba → consultaarca. Deuda se chequea antes que calendario
	# para que "deuda y vencimientos" gane; "vencimientos" solo → calendario.
	# REPORTE_COMPLETO queda como agregador: solo matchea si ninguna keyword
	# de tool pegó (mensaje mixto "reporte + tool" → tool, spec scenario).
	if cuit and any(kw in msg for kw in ['sistemaregistral', 'sistema registral', 'registro registral']):
		return Intent.SISTEMA_REGISTRAL, cuit, {}
	if cuit and any(kw in msg for kw in ['deudavencimientos', 'deuda y vencimientos', 'deuda']):
		return Intent.DEUDA_VENCIMIENTOS, cuit, {}
	if cuit and any(kw in msg for kw in ['calendariovencimientosarca', 'calendario', 'vencimientos']):
		return Intent.CALENDARIO_VENCIMIENTOS_ARCA, cuit, {}
	if cuit and any(kw in msg for kw in ['misfacilidades', 'mis facilidades', 'plan de pago', 'plan de pagos']):
		return Intent.MIS_FACILIDADES, cuit, {}
	if cuit and any(kw in msg for kw in ['rentascordoba', 'rentas cordoba', 'iibb', 'ingresos brutos']):
		return Intent.RENTAS_CORDOBA, cuit, {}
	if cuit and any(kw in msg for kw in ['consultaarca', 'obligaciones']):
		return Intent.CONSULTA_ARCA, cuit, {}

	# ── Reporte completo (pipeline completo: padrón + calendario + browser + PDF) ─
	if cuit and any(kw in msg for kw in ['reporte', 'informe', 'completo', 'todo', 'resumen', 'full', 'pipeline']):
		return Intent.REPORTE_COMPLETO, cuit, {}

	# ── Consulta de datos del contribuyente ─────────────────────────────────────
	if cuit and any(kw in msg for kw in ['consulta', 'cuit', 'padron', 'datos', 'quien', 'quién']):
		return Intent.TAXPAYER_QUERY, cuit, {}

	return Intent.UNKNOWN, cuit, {}
