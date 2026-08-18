"""Tests unitarios de los formatters por tool (domain/response_builder.py).

Cubre: rama error-first (BROWSER_ERROR → motivo corto; códigos de motor
conocidos → motivo amigable sin códigos internos ni 500 crudo) y el render
de secciones por tool sobre dicts planos (la misma forma que reciben los
handlers en runtime).
"""

from __future__ import annotations

import pytest

from agente_fiscal.domain.response_builder import (
	format_calendario_response,
	format_consultaarca_response,
	format_deuda_response,
	format_facilidades_response,
	format_rentas_response,
)

CUIT = '20123456789'


@pytest.mark.parametrize(
	('formatter', 'tool'),
	[
		(format_deuda_response, 'la deuda'),
		(format_rentas_response, 'las rentas'),
		(format_consultaarca_response, 'el padrón ARCA'),
		(format_calendario_response, 'el calendario'),
	],
)
def test_error_browser_error_short_reason(formatter, tool):
	reply = formatter({'error': 'BROWSER_ERROR', 'detail': 'traceback raw'}, CUIT)
	assert 'No pude consultar' in reply and CUIT in reply
	assert '**Motivo:** Error de conexión' in reply
	assert 'traceback' not in reply  # nunca filtra el traceback crudo


def test_error_engine_code_friendly_reason():
	"""Códigos de motor conocidos → motivo amigable sin códigos internos ni 500 crudo."""
	reply = format_consultaarca_response({'error': 'TAXPAYER_QUERY_FAILED', 'detail': '500 Server Error ...'}, CUIT)
	assert 'No pude consultar' in reply and CUIT in reply
	assert 'ARCA no respondió la consulta al padrón' in reply
	assert 'TAXPAYER_QUERY_FAILED' not in reply
	assert '500 Server Error' not in reply


def test_error_not_found_friendly_reason():
	reply = format_consultaarca_response({'error': 'TAXPAYER_NOT_FOUND', 'detail': 'No existe persona con ese Id'}, CUIT)
	assert 'no figura en el padrón de ARCA' in reply
	assert 'TAXPAYER_NOT_FOUND' not in reply


def test_error_none_data_short_reply():
	reply = format_deuda_response(None, CUIT)
	assert 'No pude consultar' in reply and CUIT in reply


def test_deuda_sections():
	data = {
		'deuda_actual': 12345.6,
		'vencimientos': [
			{'impuesto': 'IVA', 'concepto': 'IVA Mensual', 'periodo': 202608, 'fecha_vencimiento': '2026-08-18'},
		],
		'deudas': [{'impuesto': 'Ganancias', 'concepto': 'Anticipo', 'saldo': 500.25, 'vencimiento': '2026-08-22'}],
	}
	reply = format_deuda_response(data, CUIT)
	assert '**Deuda y vencimientos (ARCA)**' in reply and CUIT in reply
	assert '$ 12,345.60' in reply  # deuda_actual formateada con separador de miles
	assert 'IVA Mensual' in reply and '2026-08-18' in reply
	assert 'Ganancias' in reply and '$ 500.25' in reply


def test_deuda_empty_state():
	reply = format_deuda_response({'deuda_actual': None}, CUIT)
	assert 'No se encontraron deudas o vencimientos activos.' in reply


def test_facilidades_sections():
	data = {
		'facilidades': [
			{
				'plan': 'Plan 1',
				'nro_plan': '12345',
				'estado': 'ACTIVO',
				'cantidad_cuotas': 6,
				'cuotas_pagas': 2,
				'saldo': 900.0,
				'proximo_vencimiento': {'fecha': '2026-09-10'},
			}
		]
	}
	reply = format_facilidades_response(data, CUIT)
	assert '**Mis Facilidades (ARCA)**' in reply and CUIT in reply
	assert '**Plan 1** (N° 12345) — ACTIVO' in reply
	assert '6 cuotas, 2 pagas' in reply
	assert 'próximo vencimiento 2026-09-10' in reply


def test_facilidades_empty_state():
	reply = format_facilidades_response({}, CUIT)
	assert 'No se encontraron planes de pago activos.' in reply


def test_rentas_sections():
	data = {
		'registro': {
			'iibb_jurisdicciones': [
				{'provincia': 'CÓRDOBA', 'inscripcion': '901-123456-1', 'estado': 'ACTIVO'},
			],
			'iibb_cuotas_vencidas': [
				{'periodo': '2026/3', 'impuesto': 'Ingresos Brutos Local', 'saldo': 1500.5, 'estado': 'EN MORA'},
			],
		}
	}
	reply = format_rentas_response(data, CUIT)
	assert '**Rentas Córdoba (IIBB)**' in reply and CUIT in reply
	assert 'CÓRDOBA' in reply and '901-123456-1' in reply and 'ACTIVO' in reply
	assert '2026/3' in reply and '$ 1,500.50' in reply and 'EN MORA' in reply


def test_rentas_empty_state():
	reply = format_rentas_response({'registro': None}, CUIT)
	assert 'No se encontró registro IIBB para la provincia de Córdoba.' in reply


def test_consultaarca_obligaciones_mock_shape():
	data = {
		'denominacion': 'EMPRESA DE PRUEBA S.A.',
		'obligaciones': [
			{'impuesto': 'IVA', 'codigo': '030', 'estado': 'Activo'},
		],
	}
	reply = format_consultaarca_response(data, CUIT)
	assert '**Consulta ARCA (Padrón A5)**' in reply and CUIT in reply
	assert 'EMPRESA DE PRUEBA S.A.' in reply
	assert '**Obligaciones:**' in reply and 'IVA' in reply and '030' in reply


def test_consultaarca_padron_shape():
	data = {
		'razon_social': 'ACME SA',
		'tipo': 'responsable_inscripto',
		'estado_clave': 'ACTIVO',
		'domicilio_fiscal': {'direccion': 'Av. Siempre Viva 742', 'localidad': 'Córdoba', 'provincia': 'CÓRDOBA'},
		'impuestos_rg': [{'idImpuesto': '030', 'descripcionImpuesto': 'IVA', 'estadoImpuesto': 'Activo'}],
	}
	reply = format_consultaarca_response(data, CUIT)
	assert 'ACME SA' in reply and 'Responsable Inscripto' in reply and 'ACTIVO' in reply
	assert 'Av. Siempre Viva 742' in reply
	assert '**Obligaciones:**' in reply and 'IVA' in reply


def test_calendario_sections():
	data = {
		'periodo': '2026-08',
		'vencimientos': [
			{'fecha': '2026-08-20', 'concepto': 'Monotributo - Cuota Mensual', 'importe': 45000.0},
		],
		'observaciones': ['Presentación EE.CC. anual'],
		'feriados_presentes': ['2026-08-17'],
	}
	reply = format_calendario_response(data, CUIT)
	assert '**Calendario de vencimientos (ARCA)**' in reply and CUIT in reply and '(2026-08)' in reply
	assert '**2026-08-20** — Monotributo - Cuota Mensual' in reply and '$ 45,000.00' in reply
	assert 'Presentación EE.CC. anual' in reply
	assert '1 feriados' in reply


def test_calendario_empty_state():
	reply = format_calendario_response({'vencimientos': []}, CUIT)
	assert 'No se encontraron vencimientos para el período.' in reply