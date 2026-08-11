"""Integration tests for POST /v1/chat/message — fiscal_agent/api/routes/chat.py.

Uses FastAPI TestClient with monkeypatched handlers to verify
spec scenarios without real ARCA or browser dependencies.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fiscal_agent.chat.intent_router import Intent


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def app() -> FastAPI:
	"""Build a minimal FastAPI app with only the chat router."""
	app = FastAPI()
	from fiscal_agent.api.routes.chat import router

	app.include_router(router)
	return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
	"""Return a TestClient for the chat-only app."""
	return TestClient(app)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _mock_handler(intent: Intent, data: dict):
	"""Return a patch for the _dispatch function that returns mock data."""
	return patch('fiscal_agent.api.routes.chat._dispatch', return_value=data)


# ── Spec scenarios ──────────────────────────────────────────────────────────


def test_consulta_cuit(client: TestClient) -> None:
	"""Consulta CUIT returns taxpayer data."""
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
	with _mock_handler(Intent.TAXPAYER_QUERY, data):
		resp = client.post(
			'/v1/chat/message',
			json={'message': 'consulta CUIT 20324837796'},
		)

	assert resp.status_code == 200
	body = resp.json()
	assert 'consultar_cuit' in body['actions_taken']
	assert body['data'] == data
	assert 'Juan Perez' in body['reply']


def test_consulta_deuda(client: TestClient) -> None:
	"""Consulta deuda returns debt summary."""
	data = {
		'deuda_actual': 125000.50,
		'saldos': [{'concepto': 'IVA', 'importe': 45000.00}],
	}
	with _mock_handler(Intent.DEUDA_QUERY, data):
		resp = client.post(
			'/v1/chat/message',
			json={'message': 'deuda de 20324837796'},
		)

	assert resp.status_code == 200
	body = resp.json()
	assert 'consultar_deuda' in body['actions_taken']
	assert body['data'] == data


def test_consulta_calendario(client: TestClient) -> None:
	"""Consulta calendario returns calendar data."""
	data = {
		'periodo': '202606',
		'vencimientos': [{'concepto': 'IVA', 'fecha': '2026-06-18', 'importe': 15000.00}],
	}
	with _mock_handler(Intent.CALENDARIO_QUERY, data):
		resp = client.post(
			'/v1/chat/message',
			json={'message': 'calendario 202406 20324837796'},
		)

	assert resp.status_code == 200
	body = resp.json()
	assert 'consultar_calendario' in body['actions_taken']
	assert body['data'] == data


def test_consulta_facilidades(client: TestClient) -> None:
	"""Consulta facilidades returns payment plans."""
	data = {
		'facilidades': [
			{
				'plan': 'Plan Permanente',
				'nro_plan': '12345',
				'estado': 'activo',
				'cantidad_cuotas': 6,
				'cuotas_pagas': 3,
				'saldo': 35000.00,
			},
		],
	}
	with _mock_handler(Intent.FACILIDADES_QUERY, data):
		resp = client.post(
			'/v1/chat/message',
			json={'message': 'facilidades de pago 20324837796'},
		)

	assert resp.status_code == 200
	body = resp.json()
	assert 'consultar_facilidades' in body['actions_taken']


def test_consulta_registro(client: TestClient) -> None:
	"""Consulta registro returns tax registration data."""
	data = {
		'impuestos': [{'impuesto': 'IVA', 'estado': 'activo'}],
	}
	with _mock_handler(Intent.REGISTRO_QUERY, data):
		resp = client.post(
			'/v1/chat/message',
			json={'message': 'registro tributario 20324837796'},
		)

	assert resp.status_code == 200
	body = resp.json()
	assert 'consultar_registro' in body['actions_taken']


def test_reporte_completo(client: TestClient) -> None:
	"""Reporte completo triggers report generation."""
	data = {'calendario': {'periodo': '202606', 'vencimientos': []}, 'ws_api': True}
	with _mock_handler(Intent.REPORTE_COMPLETO, data):
		resp = client.post(
			'/v1/chat/message',
			json={'message': 'reporte completo 20324837796'},
		)

	assert resp.status_code == 200
	body = resp.json()
	assert 'generar_reporte' in body['actions_taken']


def test_sin_cuit(client: TestClient) -> None:
	"""Mensaje sin CUIT pide proporcionar CUIT."""
	resp = client.post(
		'/v1/chat/message',
		json={'message': 'deuda'},
	)

	assert resp.status_code == 200
	body = resp.json()
	assert 'CUIT' in body['reply']
	assert body['actions_taken'] == []


def test_mensaje_irreconocible(client: TestClient) -> None:
	"""Mensaje irreconocible lista tipos soportados."""
	resp = client.post(
		'/v1/chat/message',
		json={'message': 'hola'},
	)

	assert resp.status_code == 200
	body = resp.json()
	assert 'CUITs' in body['reply'] or 'Podés' in body['reply']
	assert body['actions_taken'] == []


def test_error_backend(client: TestClient) -> None:
	"""Error interno del backend muestra error en español."""
	with patch('fiscal_agent.api.routes.chat._dispatch', side_effect=ValueError('Error interno')):
		resp = client.post(
			'/v1/chat/message',
			json={'message': 'consulta CUIT 20324837796'},
		)

		assert resp.status_code == 200
		body = resp.json()
		assert 'error' in body['reply'].lower() or 'Error' in body['reply']
		assert 'consultar_cuit' in body['actions_taken']


def test_conversation_id_generated(client: TestClient) -> None:
	"""Omitted conversation_id generates a new one."""
	resp = client.post(
		'/v1/chat/message',
		json={'message': 'hola'},
	)

	assert resp.status_code == 200
	body = resp.json()
	assert body['conversation_id']
	assert len(body['conversation_id']) > 0


def test_conversation_id_echoed(client: TestClient) -> None:
	"""Provided conversation_id is echoed back."""
	resp = client.post(
		'/v1/chat/message',
		json={'message': 'hola', 'conversation_id': 'test-conv-123'},
	)

	assert resp.status_code == 200
	body = resp.json()
	assert body['conversation_id'] == 'test-conv-123'


def test_with_history(client: TestClient) -> None:
	"""Providing history does not break the endpoint."""
	resp = client.post(
		'/v1/chat/message',
		json={
			'message': 'consulta CUIT 20324837796',
			'history': [
				{'role': 'user', 'content': 'hola'},
				{'role': 'assistant', 'content': 'Hola! En qué puedo ayudarte?'},
			],
		},
	)

	assert resp.status_code == 200
