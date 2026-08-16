"""Tests del intent router para las browser tools.

Cubre la prioridad del design: tools ANTES de REPORTE_COMPLETO/TAXPAYER_QUERY,
la colisión "deuda y vencimientos" vs "vencimientos" resuelta por orden de
chequeo, y el fallback de "consulta" genérica → TAXPAYER_QUERY.
"""

from __future__ import annotations

import pytest

from agente_fiscal.domain.intent_router import Intent, detect

CUIT = '20-12345678-9'


@pytest.mark.parametrize(
	('message', 'expected'),
	[
		(f'sistemaregistral CUIT {CUIT}', Intent.SISTEMA_REGISTRAL),
		(f'sistema registral CUIT {CUIT}', Intent.SISTEMA_REGISTRAL),
		(f'deudavencimientos CUIT {CUIT}', Intent.DEUDA_VENCIMIENTOS),
		(f'deuda y vencimientos CUIT {CUIT}', Intent.DEUDA_VENCIMIENTOS),
		(f'misfacilidades CUIT {CUIT}', Intent.MIS_FACILIDADES),
		(f'mis facilidades CUIT {CUIT}', Intent.MIS_FACILIDADES),
		(f'plan de pago CUIT {CUIT}', Intent.MIS_FACILIDADES),
		(f'rentascordoba CUIT {CUIT}', Intent.RENTAS_CORDOBA),
		(f'rentas cordoba CUIT {CUIT}', Intent.RENTAS_CORDOBA),
		(f'iibb CUIT {CUIT}', Intent.RENTAS_CORDOBA),
		(f'consultaarca CUIT {CUIT}', Intent.CONSULTA_ARCA),
		(f'calendariovencimientosarca CUIT {CUIT}', Intent.CALENDARIO_VENCIMIENTOS_ARCA),
		(f'calendario CUIT {CUIT}', Intent.CALENDARIO_VENCIMIENTOS_ARCA),
	],
)
def test_tool_commands_route_to_their_intent(message, expected):
	intent, cuit, _params = detect(message)
	assert intent == expected
	assert cuit == CUIT.replace('-', '')


def test_deuda_y_vencimientos_wins_over_calendario():
	# Colisión: "deuda y vencimientos" contiene keyword de deuda Y de
	# calendario ("vencimientos"). Deuda se chequea antes → DEUDA_VENCIMIENTOS.
	intent, _cuit, _params = detect(f'deuda y vencimientos CUIT {CUIT}')
	assert intent == Intent.DEUDA_VENCIMIENTOS


def test_vencimientos_alone_routes_to_calendario():
	# Sin keyword deuda → "vencimientos" lleva a CALENDARIO_VENCIMIENTOS_ARCA.
	intent, _cuit, _params = detect(f'vencimientos CUIT {CUIT}')
	assert intent == Intent.CALENDARIO_VENCIMIENTOS_ARCA


def test_tool_keyword_beats_reporte_completo():
	# Mensaje mixto "reporte + tool" → la tool gana (spec scenario). El
	# agregador REPORTE_COMPLETO solo matchea sin keyword de tool.
	intent, _cuit, _params = detect(f'reporte completo deudavencimientos CUIT {CUIT}')
	assert intent == Intent.DEUDA_VENCIMIENTOS


def test_plain_consulta_stays_taxpayer_query():
	# "consulta" genérico NO es keyword de consultaarca (solo
	# 'consultaarca'/'obligaciones') → cae a TAXPAYER_QUERY, como siempre.
	intent, _cuit, _params = detect(f'consulta CUIT {CUIT}')
	assert intent == Intent.TAXPAYER_QUERY


def test_mixed_deuda_plan_routes_to_deuda():
	# "plan de pago de deuda": la keyword "deuda" gana porque el chequeo de
	# deuda precede al de facilidades (prioridad del design).
	intent, _cuit, _params = detect(f'plan de pago de deuda CUIT {CUIT}')
	assert intent == Intent.DEUDA_VENCIMIENTOS


def test_engine_tools_require_cuit():
	# Sin CUIT no hay tool intent: cae al flujo "proporcioná un CUIT".
	intent, cuit, _params = detect('vencimientos')
	assert cuit is None
	assert intent == Intent.UNKNOWN