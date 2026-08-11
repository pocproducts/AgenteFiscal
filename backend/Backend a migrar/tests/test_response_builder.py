"""Tests for chat response builder — fiscal_agent/chat/response_builder.py.

Verifies that each formatter produces correct Spanish text for
various data shapes: complete data, partial data, and errors.
"""

from __future__ import annotations

import pytest

from fiscal_agent.chat.intent_router import Intent
from fiscal_agent.chat.response_builder import (
	build_response,
	format_calendario,
	format_deuda,
	format_facilidades,
	format_registro,
	format_reporte,
	format_response,
	format_taxpayer,
)


# ── format_taxpayer ─────────────────────────────────────────────────────────


def test_taxpayer_full_data() -> None:
	"""Full taxpayer data produces a complete profile."""
	data = {
		'datosGenerales': {
			'nombre': 'Juan Perez',
			'idPersona': '20324837796',
			'tipoPersona': 'FISICA',
			'tipoClave': 'Clave Fiscal',
			'estadoClave': 'activa',
		},
		'domicilioFiscal': {
			'direccion': 'Av. Ejemplo 123',
			'descripcionProvincia': 'CABA',
		},
	}
	result = format_taxpayer(data, '20324837796')
	assert 'Juan Perez' in result
	assert '20324837796' in result
	assert 'CABA' in result


def test_taxpayer_razon_social() -> None:
	"""Company taxpayer uses razonSocial instead of nombre."""
	data = {
		'datosGenerales': {
			'razonSocial': 'Empresa SA',
			'idPersona': '30234567890',
			'tipoPersona': 'JURIDICA',
			'tipoClave': 'Clave Fiscal',
			'estadoClave': 'activa',
		},
		'domicilioFiscal': {
			'direccion': 'Calle Falsa 456',
			'descripcionProvincia': 'Buenos Aires',
		},
	}
	result = format_taxpayer(data, '30234567890')
	assert 'Empresa SA' in result


def test_taxpayer_with_error_constancia() -> None:
	"""Error constancia shows the error message."""
	data = {
		'datosGenerales': None,
		'errorConstancia': {
			'error': ['CUIT INACTIVO', 'CLAVE NO EXISTE'],
		},
	}
	result = format_taxpayer(data, '20324837796')
	assert 'CUIT INACTIVO' in result
	assert 'CLAVE NO EXISTE' in result


def test_taxpayer_no_data() -> None:
	"""None data shows 'no se encontraron datos'."""
	result = format_taxpayer(None, '20324837796')
	assert 'No se encontraron datos' in result


# ── format_deuda ────────────────────────────────────────────────────────────


def test_deuda_with_amount() -> None:
	"""Debt with actual amount shows formatted total."""
	data = {
		'deuda_actual': 125000.50,
		'saldos': [],
		'facilidades': [],
	}
	result = format_deuda(data, '20324837796')
	assert '125' in result
	assert '20324837796' in result


def test_deuda_with_items() -> None:
	"""Debt with line items shows each one."""
	data = {
		'deuda_actual': 45000.00,
		'saldos': [
			{'concepto': 'IVA', 'importe': 45000.00, 'vencimiento': None, 'estado': 'impago'},
		],
		'facilidades': [],
	}
	result = format_deuda(data, '20324837796')
	assert 'IVA' in result
	assert '45,000' in result


def test_deuda_error() -> None:
	"""Error in deuda response shows the error."""
	data = {'error': 'Servicio no disponible'}
	result = format_deuda(data, '20324837796')
	assert 'Servicio no disponible' in result


def test_deuda_no_data() -> None:
	"""None data shows 'no se encontró información'."""
	result = format_deuda(None, '20324837796')
	assert 'No se encontró información' in result


# ── format_facilidades ──────────────────────────────────────────────────────


def test_facilidades_active_plan() -> None:
	"""Active payment plan shows plan details."""
	data = {
		'facilidades': [
			{
				'plan': 'Plan Permanente',
				'nro_plan': '12345',
				'estado': 'activo',
				'cantidad_cuotas': 6,
				'cuotas_pagas': 3,
				'saldo': 35000.00,
				'proximo_vencimiento': {
					'nro_cuota': 4,
					'fecha': '2026-07-15',
					'total': 12500.00,
				},
			},
		],
	}
	result = format_facilidades(data, '20324837796')
	assert 'Plan Permanente' in result
	assert '12345' in result
	assert '3/6' in result


def test_facilidades_empty() -> None:
	"""No payment plans shows appropriate message."""
	data = {'facilidades': []}
	result = format_facilidades(data, '20324837796')
	assert 'No hay planes de pago activos' in result


def test_facilidades_no_data() -> None:
	"""None data shows 'no se encontraron'."""
	result = format_facilidades(None, '20324837796')
	assert 'No se encontraron planes' in result


# ── format_calendario ───────────────────────────────────────────────────────


def test_calendario_with_items() -> None:
	"""Calendar with vencimientos lists each one."""
	data = {
		'periodo': '202606',
		'vencimientos': [
			{'concepto': 'IVA - DDJJ', 'fecha': '2026-06-18', 'importe': 15000.00},
			{'concepto': 'Ganancias - Anticipo', 'fecha': '2026-06-22', 'importe': 25000.00},
		],
	}
	result = format_calendario(data, '20324837796')
	assert 'IVA' in result
	assert '18/06/2026' in result
	assert '15,000' in result


def test_calendario_error() -> None:
	"""Error in calendar shows the error."""
	data = {'error': 'CUIT inválido', 'periodo': '202606', 'vencimientos': []}
	result = format_calendario(data, '20324837796')
	assert 'CUIT inválido' in result


def test_calendario_empty() -> None:
	"""No vencimientos shows appropriate message."""
	data = {'periodo': '202606', 'vencimientos': []}
	result = format_calendario(data, '20324837796')
	assert 'No hay vencimientos' in result


# ── format_registro ─────────────────────────────────────────────────────────


def test_registro_full() -> None:
	"""Full registro data shows domicilios, actividades, impuestos."""
	data = {
		'domicilios': [
			{'tipo': 'fiscal', 'provincia': 'CABA', 'localidad': 'Capital Federal', 'direccion': 'Av. Ejemplo 123'},
		],
		'actividades': [
			{'actividad': 'Servicios informáticos', 'codigo': '620100', 'estado': 'activo'},
		],
		'impuestos': [
			{'impuesto': 'IVA', 'categoria': 'Responsable Inscripto', 'estado': 'activo'},
		],
	}
	result = format_registro(data, '20324837796')
	assert 'Servicios informáticos' in result
	assert 'IVA' in result
	assert 'CABA' in result


def test_registro_no_data() -> None:
	"""None data shows 'no se encontró registro'."""
	result = format_registro(None, '20324837796')
	assert 'No se encontró registro tributario' in result


# ── format_reporte ──────────────────────────────────────────────────────────


def test_reporte_generated() -> None:
	"""Generated report shows summary."""
	data = {
		'calendario': {'periodo': '202606', 'vencimientos': [{'concepto': 'IVA'}]},
		'ws_api': True,
	}
	result = format_reporte(data, '20324837796')
	assert 'generado' in result or 'Reporte' in result


def test_reporte_error() -> None:
	"""Error in report generation shows the error."""
	data = {'error': 'Pipeline falló'}
	result = format_reporte(data, '20324837796')
	assert 'Pipeline falló' in result


def test_reporte_no_data() -> None:
	"""None data shows 'no se pudo generar'."""
	result = format_reporte(None, '20324837796')
	assert 'No se pudo generar' in result


# ── format_response (top-level dispatch) ────────────────────────────────────


def test_dispatch_unknown() -> None:
	"""UNKNOWN intent lists supported query types."""
	result = format_response(Intent.UNKNOWN, None, '')
	assert 'CUITs' in result
	assert 'deuda' in result
	assert 'calendario' in result


# ── build_response ──────────────────────────────────────────────────────────


def test_build_response_full() -> None:
	"""build_response returns dict with reply, actions_taken, and data."""
	data = {
		'datosGenerales': {'nombre': 'Juan Perez'},
	}
	result = build_response(Intent.TAXPAYER_QUERY, data, '20324837796')
	assert 'reply' in result
	assert 'actions_taken' in result
	assert 'data' in result
	assert 'consultar_cuit' in result['actions_taken']
	assert result['data'] == data


def test_build_response_unknown() -> None:
	"""UNKNOWN intent has no data and empty actions."""
	result = build_response(Intent.UNKNOWN, None, '')
	assert 'reply' in result
	assert result['actions_taken'] == []
	assert 'data' not in result
