"""Tests for chat intent router — fiscal_agent/chat/intent_router.py.

Verifies CUIT extraction, intent detection, and parameter parsing
for all supported query types and edge cases.
"""

from __future__ import annotations

import pytest

from fiscal_agent.chat.intent_router import Intent, detect


# ── CUIT extraction ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
	('text', 'expected_cuit'),
	[
		('consulta CUIT 20324837796', '20324837796'),
		('deuda de 20324837796', '20324837796'),
		('calendario 202406 20324837796', '20324837796'),
		('reporte completo 20324837796', '20324837796'),
		('consulta datos del contribuyente 20-32483779-6', '20324837796'),
		('facilidades de pago 27-12345678-9', '27123456789'),
		# Invalid CUIT (wrong start digits)
		('consulta 19324837796', ''),
		# No CUIT at all
		('hola', ''),
		('qué podes hacer', ''),
	],
)
def test_cuit_extraction(text: str, expected_cuit: str) -> None:
	"""Verify CUIT extraction from various message formats."""
	intent, cuit, params = detect(text)
	assert cuit == expected_cuit, f'Expected CUIT "{expected_cuit}", got "{cuit}"'


# ── Intent detection ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
	('text', 'expected_intent'),
	[
		# TAXPAYER
		('consulta CUIT 20324837796', Intent.TAXPAYER_QUERY),
		('datos del contribuyente 20324837796', Intent.TAXPAYER_QUERY),
		('padron de 20324837796', Intent.TAXPAYER_QUERY),
		# DEUDA
		('deuda de 20324837796', Intent.DEUDA_QUERY),
		('saldo del CUIT 20324837796', Intent.DEUDA_QUERY),
		('cuanto adeuda 20324837796', Intent.DEUDA_QUERY),
		# FACILIDADES
		('facilidades de pago 20324837796', Intent.FACILIDADES_QUERY),
		('plan de pagos 20324837796', Intent.FACILIDADES_QUERY),
		('cuotas 20324837796', Intent.FACILIDADES_QUERY),
		# CALENDARIO
		('calendario 202406 20324837796', Intent.CALENDARIO_QUERY),
		('vencimientos de 20324837796', Intent.CALENDARIO_QUERY),
		('vto junio 2026 20324837796', Intent.CALENDARIO_QUERY),
		# REGISTRO
		('registro tributario 20324837796', Intent.REGISTRO_QUERY),
		('impuestos de 20324837796', Intent.REGISTRO_QUERY),
		('actividades economicas 20324837796', Intent.REGISTRO_QUERY),
		# REPORTE
		('reporte completo 20324837796', Intent.REPORTE_COMPLETO),
		('resumen 20324837796', Intent.REPORTE_COMPLETO),
		('pipeline 20324837796', Intent.REPORTE_COMPLETO),
		# UNKNOWN
		('hola', Intent.UNKNOWN),
		('como estas', Intent.UNKNOWN),
		('', Intent.UNKNOWN),
	],
)
def test_intent_detection(text: str, expected_intent: Intent) -> None:
	"""Verify correct intent is returned for each keyword pattern."""
	intent, cuit, params = detect(text)
	assert intent == expected_intent, f'Expected {expected_intent}, got {intent} for text: "{text}"'


# ── Parameter parsing ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
	('text', 'expected_params'),
	[
		('calendario 202406 20324837796', {'periodo': '202406'}),
		('calendario junio 2026 20324837796', {'periodo': '202606'}),
		('vencimientos 20324837796', {}),
		('consulta CUIT 20324837796', {}),
	],
)
def test_param_parsing(text: str, expected_params: dict) -> None:
	"""Verify extra parameters like ``periodo`` are correctly parsed."""
	intent, cuit, params = detect(text)
	assert params == expected_params, f'Expected params {expected_params}, got {params}'


# ── Edge cases ──────────────────────────────────────────────────────────────


def test_empty_text() -> None:
	"""Empty text returns UNKNOWN with no CUIT."""
	intent, cuit, params = detect('')
	assert intent == Intent.UNKNOWN
	assert cuit == ''
	assert params == {}


def test_whitespace_text() -> None:
	"""Whitespace-only text returns UNKNOWN."""
	intent, cuit, params = detect('   ')
	assert intent == Intent.UNKNOWN


def test_cuit_with_hyphens() -> None:
	"""CUIT with hyphen separators is correctly normalized."""
	intent, cuit, params = detect('consulta 20-32483779-6')
	assert cuit == '20324837796'
	assert intent == Intent.TAXPAYER_QUERY


def test_cuit_at_end_of_text() -> None:
	"""CUIT at the end of a sentence is still extracted."""
	intent, cuit, params = detect('necesito la deuda de 20324837796')
	assert cuit == '20324837796'
	assert intent == Intent.DEUDA_QUERY


def test_multiple_cuits_first_is_used() -> None:
	"""When multiple CUITs are present, the first one is used."""
	intent, cuit, params = detect('20324837796 y tambien 27123456789')
	assert cuit == '20324837796'


def test_keyword_without_cuit_detects_intent() -> None:
	"""Keywords without CUIT should still detect intent (endpoint handles 'no CUIT' reply)."""
	intent, cuit, params = detect('deuda')
	assert cuit == ''
	# The router detects intent by keyword even without CUIT.
	# The endpoint (chat.py) is responsible for returning the "provide a CUIT" message.
	assert intent == Intent.DEUDA_QUERY
