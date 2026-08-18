"""Tests de contrato SSE del streaming de browser tools (POST /v1/chat/message/stream).

Cubre (tasks.md 6.1):
- Contrato de 5 eventos por tool Phase-1: conversation_start → progress* →
  live_url → agent_step* → complete, con data por tool.
- SSRR parity: sistemaregistral conserva el mismo flujo/eventos que el
  branch hardcodeado previo.
- Engines deterministas (consultaarca / calendariovencimientosarca) NO emiten
  live_url/agent_step (design D1: sin sesión, sin live_url).
- Failure → complete.data.error + reply corto (sin traceback).
"""

from __future__ import annotations

import json
from datetime import datetime, date

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from agente_fiscal.api.routes import chat as chat_router
from agente_fiscal.domain.models import (
	ClientConfig,
	DeudaOutput,
	RegistroIIBBJurisdiccion,
	RegistroOutput,
	RulesOutput,
	Vencimiento,
	VencimientoDeuda,
	FacilidadPlan,
	DeudaDetail,
	IIBBCuotaVencida,
)
from agente_fiscal.domain.intent_router import Intent

CUIT = '20123456789'
# CUIT con formato con guiones para el mensaje (el router lo normaliza).
CUIT_HYPHEN = '20-12345678-9'


# ── Helpers ────────────────────────────────────────────────────────────────


def _build_app() -> FastAPI:
	app = FastAPI()

	@app.exception_handler(HTTPException)
	async def _http_exc_handler(_request, exc):
		return json.JSONResponse({'detail': exc.detail}, status_code=exc.status_code)

	app.include_router(chat_router.router)
	return app


def _parse_sse(text: str) -> list[tuple[str, dict]]:
	"""Parsea el cuerpo SSE en [(event, data_dict), ...]."""
	frames: list[tuple[str, dict]] = []
	for frame in text.split('\n\n'):
		lines = frame.strip().split('\n')
		event = 'message'
		payload_lines: list[str] = []
		for line in lines:
			if line.startswith('event:'):
				event = line.split(':', 1)[1].strip()
			elif line.startswith('data:'):
				payload_lines.append(line.split(':', 1)[1].strip())
		if payload_lines:
			frames.append((event, json.loads('\n'.join(payload_lines))))
	return frames


class _FakeSettings:
	class _Credentials:
		composio_api_key = 'test-key'
		clave_fiscal = 'test-clave'

	credentials = _Credentials()
	browser_enabled = True
	browser_provider = 'composio'


class FakeBrowser:
	"""Mock de ComposioBrowser.run_single: emite callbacks y devuelve output."""

	def __init__(self, output: DeudaOutput, failure: Exception | None = None):
		self.output = output
		self.failure = failure

	def __call__(self, **kwargs):
		return self

	def run_single(
		self,
		cliente: ClientConfig,
		tasks=None,
		echo_func=None,
		on_live_url=None,
		on_step=None,
		on_task_metrics=None,
	) -> DeudaOutput:
		if self.failure is not None:
			raise self.failure
		if echo_func:
			echo_func('  🔍 Ejecutando tareas de browser ...')
		if on_live_url:
			on_live_url('https://live.example/session/abc')
		if on_step:
			on_step(1, 'Primer paso', 'https://padron.example', 'running')
			on_step(1, '', '', 'finished')
		if on_task_metrics:
			on_task_metrics({'duration_ms': 100, 'cost_cents': 2, 'proxy_bytes': 1024, 'session_id': 's1', 'context_id': 'c1', 'started_at': '2026-08-17T00:00:00+00:00', 'ended_at': '2026-08-17T00:01:00+00:00'})
		return self.output


class FakePadronResult:
	"""Mock de PadronA5Result (arca_ws.consultar_cuit)."""

	def __init__(self, data: dict, output=None):
		self._data = data
		self._output = output

	def to_dict(self) -> dict:
		return dict(self._data)

	def to_output(self):
		return self._output


class FakeEngine:
	"""Mock de RulesEngine.calcular (determinista)."""

	def __init__(self, output: RulesOutput):
		self._output = output

	def calcular(self, padron, mes, anio, provincias=None) -> RulesOutput:
		return self._output


def _registro_output() -> DeudaOutput:
	"""DeudaOutput para sistemaregistral (registro tributario + live_url)."""
	return DeudaOutput(
		cuit=CUIT,
		extraido_el=datetime.utcnow(),
		live_url='https://live.example/session/abc',
		registro=RegistroOutput(
			jurisdiccion='CÓRDOBA',
			domicilios=[],
			actividades=[],
			impuestos=[],
			iibb_jurisdicciones=[
				RegistroIIBBJurisdiccion(provincia='CÓRDOBA', inscripcion='901-123456-1', estado='ACTIVO'),
			],
		),
	)


def _output_for(tool_key: str) -> DeudaOutput:
	"""DeudaOutput por tool (como lo devuelve ComposioBrowser.run_single real)."""
	if tool_key == 'sistemaregistral':
		return _registro_output()
	if tool_key == 'deudavencimientos':
		return DeudaOutput(
			cuit=CUIT,
			extraido_el=datetime.utcnow(),
			deuda_actual=12345.6,
			vencimientos=[VencimientoDeuda(impuesto='IVA', concepto='IVA Mensual', periodo=202608, fecha_vencimiento=date(2026, 8, 18))],
			deudas=[DeudaDetail(impuesto='Ganancias', concepto='Anticipo', saldo=500.25, vencimiento=date(2026, 8, 22))],
		)
	if tool_key == 'misfacilidades':
		return DeudaOutput(
			cuit=CUIT,
			extraido_el=datetime.utcnow(),
			facilidades=[FacilidadPlan(plan='Plan 1', nro_plan='12345', estado='ACTIVO', cantidad_cuotas=6, cuotas_pagas=2)],
		)
	if tool_key == 'rentascordoba':
		return DeudaOutput(
			cuit=CUIT,
			extraido_el=datetime.utcnow(),
			registro=RegistroOutput(
				iibb_jurisdicciones=[RegistroIIBBJurisdiccion(provincia='CÓRDOBA', inscripcion='901-123456-1', estado='ACTIVO')],
				iibb_cuotas_vencidas=[IIBBCuotaVencida(periodo='2026/3', impuesto='Ingresos Brutos Local', saldo=1500.5, estado='EN MORA')],
			),
		)
	raise AssertionError(f'tool no soportada en el mock: {tool_key}')


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def browser_env(monkeypatch):
	"""Ambiente de browser tools: creds + token + integración habilitada."""
	from agente_fiscal.adapters import browser as browser_mod

	monkeypatch.setattr('agente_fiscal.config.get_settings', lambda: _FakeSettings())
	monkeypatch.setattr('agente_fiscal.features.integration_enabled', lambda _name: True)
	monkeypatch.setattr('agente_fiscal.api.deps.get_ta', lambda *a, **k: ('token', 'sign'))
	monkeypatch.setattr('agente_fiscal.api.deps.REPRESENTANTE_CUIT', '20999999999')
	return browser_mod


@pytest.fixture
def engine_env(monkeypatch):
	"""Ambiente de engines: token + padrón + motor."""
	monkeypatch.setattr('agente_fiscal.api.deps.get_ta', lambda *a, **k: ('token', 'sign'))
	monkeypatch.setattr('agente_fiscal.api.deps.REPRESENTANTE_CUIT', '20999999999')
	return monkeypatch


# ── Contrato 5 eventos por tool Phase-1 ────────────────────────────────────


@pytest.mark.parametrize(
	('tool_key', 'message'),
	[
		('sistemaregistral', f'sistemaregistral CUIT {CUIT_HYPHEN}'),
		('deudavencimientos', f'deudavencimientos CUIT {CUIT_HYPHEN}'),
		('misfacilidades', f'misfacilidades CUIT {CUIT_HYPHEN}'),
		('rentascordoba', f'rentascordoba CUIT {CUIT_HYPHEN}'),
	],
)
async def test_browser_tool_streams_five_events(browser_env, monkeypatch, tool_key, message):
	"""5-event contract por tool Phase-1: conversation_start → progress →
	live_url → agent_step → complete, con data por tool (SSRR parity incluida)."""
	from agente_fiscal.adapters.browser.provider import PROVIDERS

	monkeypatch.setitem(
		PROVIDERS,
		'composio',
		lambda settings=None, headed=False: FakeBrowser(output=_output_for(tool_key)),
	)

	transport = httpx.ASGITransport(app=_build_app())
	async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
		res = await client.post('/v1/chat/message/stream', json={'message': message})

	assert res.status_code == 200
	frames = _parse_sse(res.text)
	events = [e for e, _ in frames]

	# Contrato: primer evento conversation_start, último complete.
	assert events[0] == 'conversation_start'
	assert events[-1] == 'complete'
	# Browser: live_url y agent_step presentes (sesión Composio viva).
	assert 'live_url' in events
	assert 'agent_step' in events
	# Progress: al menos un paso antes del paso del browser.
	assert 'progress' in events and events.index('progress') < events.index('live_url')

	complete = frames[-1][1]
	assert complete['reply']
	assert complete['data'] is not None
	# SSRR parity: sistemaregistral conserva la misma estructura de antes.
	if tool_key == 'sistemaregistral':
		assert complete['data']['registro']['iibb_jurisdicciones'][0]['provincia'] == 'CÓRDOBA'
	if tool_key == 'deudavencimientos':
		assert complete['data']['deuda_actual'] == 12345.6
	if tool_key == 'misfacilidades':
		assert complete['data']['facilidades'][0]['plan'] == 'Plan 1'
	if tool_key == 'rentascordoba':
		assert complete['data']['registro']['iibb_cuotas_vencidas'][0]['estado'] == 'EN MORA'


# ── Engines deterministas: sin live_url ni agent_step ──────────────────────


async def test_consultaarca_streams_without_browser_events(engine_env, monkeypatch):
	from agente_fiscal.adapters.arca_ws import consultar_cuit  # noqa: F401 (target del patch)
	from agente_fiscal.domain.models import DatosGenerales, PadronA5Output

	padron = PadronA5Output(
		datosGenerales=DatosGenerales(idPersona=CUIT, razonSocial='ACME SA', estadoClave='ACTIVO')
	)
	result = FakePadronResult(
		{'denominacion': 'ACME SA', 'tipo': 'responsable_inscripto', 'estado_clave': 'ACTIVO', 'obligaciones': None},
		output=padron,
	)
	monkeypatch.setattr('agente_fiscal.adapters.arca_ws.consultar_cuit', lambda *a, **k: result)

	transport = httpx.ASGITransport(app=_build_app())
	async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
		res = await client.post('/v1/chat/message/stream', json={'message': f'consultaarca CUIT {CUIT_HYPHEN}'})

	assert res.status_code == 200
	frames = _parse_sse(res.text)
	events = [e for e, _ in frames]

	assert events[0] == 'conversation_start'
	assert events[-1] == 'complete'
	# Sin sesión → sin live_url/agent_step (D1), pero progress presente.
	assert 'live_url' not in events
	assert 'agent_step' not in events
	assert 'progress' in events
	complete = frames[-1][1]
	assert complete['data']['denominacion'] == 'ACME SA'


async def test_calendario_streams_engine_output_without_browser(engine_env, monkeypatch):
	from agente_fiscal.adapters.arca_ws import consultar_cuit  # noqa: F401 (target del patch)
	from agente_fiscal.domain.models import DatosGenerales, PadronA5Output

	calendario = RulesOutput(
		cuit=CUIT,
		periodo='2026-08',
		vencimientos=[Vencimiento(concepto='Monotributo - Cuota Mensual', fecha=date(2026, 8, 20))],
		observaciones=['Presentación EE.CC. anual'],
	)
	monkeypatch.setattr(
		'agente_fiscal.adapters.arca_ws.consultar_cuit',
		lambda *a, **k: FakePadronResult(
			{},
			output=PadronA5Output(datosGenerales=DatosGenerales(idPersona=CUIT)),
		),
	)
	monkeypatch.setattr(
		'agente_fiscal.api.deps.get_engine',
		lambda: FakeEngine(calendario),
	)

	transport = httpx.ASGITransport(app=_build_app())
	async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
		res = await client.post('/v1/chat/message/stream', json={'message': f'calendariovencimientosarca CUIT {CUIT_HYPHEN}'})

	assert res.status_code == 200
	frames = _parse_sse(res.text)
	events = [e for e, _ in frames]

	assert events[0] == 'conversation_start'
	assert events[-1] == 'complete'
	assert 'live_url' not in events
	assert 'agent_step' not in events
	complete = frames[-1][1]
	assert complete['data']['periodo'] == '2026-08'
	assert complete['data']['vencimientos'][0]['concepto'] == 'Monotributo - Cuota Mensual'
	assert 'Presentación EE.CC. anual' in complete['reply']


# ── Failure: complete.data.error + reply corto ─────────────────────────────


async def test_browser_failure_emits_error_complete(browser_env, monkeypatch):
	"""Failure del browser → complete.data.error='BROWSER_ERROR' y reply corto."""
	from agente_fiscal.adapters.browser.provider import PROVIDERS

	monkeypatch.setitem(
		PROVIDERS,
		'composio',
		lambda settings=None, headed=False: FakeBrowser(output=None, failure=RuntimeError('Composio 403')),
	)

	transport = httpx.ASGITransport(app=_build_app())
	async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
		res = await client.post('/v1/chat/message/stream', json={'message': f'deudavencimientos CUIT {CUIT_HYPHEN}'})

	assert res.status_code == 200
	frames = _parse_sse(res.text)
	complete = frames[-1][1]
	assert complete['data']['error'] == 'BROWSER_ERROR'
	assert '**Motivo:** Error de conexión' in complete['reply']
	assert 'Composio 403' not in complete['reply']  # nunca filtra el traceback crudo


async def test_engine_failure_emits_engine_error(engine_env, monkeypatch):
	"""Failure del padrón → complete.data.error='TAXPAYER_QUERY_FAILED'."""

	def _padron_boom(*_a, **_k):
		raise RuntimeError('WS caído')

	monkeypatch.setattr(
		'agente_fiscal.adapters.arca_ws.consultar_cuit',
		_padron_boom,
	)

	transport = httpx.ASGITransport(app=_build_app())
	async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
		res = await client.post('/v1/chat/message/stream', json={'message': f'consultaarca CUIT {CUIT_HYPHEN}'})

	assert res.status_code == 200
	frames = _parse_sse(res.text)
	events = [e for e, _ in frames]
	assert 'live_url' not in events
	complete = frames[-1][1]
	assert complete['data']['error'] == 'TAXPAYER_QUERY_FAILED'
	assert 'WS caído' in complete['data']['detail']


async def test_arca_missing_persona_fault_maps_to_not_found(engine_env, monkeypatch):
	"""SOAP Fault 'No existe persona con ese Id' → TAXPAYER_NOT_FOUND con reply
	amigable (sin filtrar el 500 crudo)."""
	from agente_fiscal.adapters.arca_ws import PadronNotFoundError

	def _padron_missing(*_a, **_k):
		raise PadronNotFoundError('No existe persona con ese Id')

	monkeypatch.setattr(
		'agente_fiscal.adapters.arca_ws.consultar_cuit',
		_padron_missing,
	)

	transport = httpx.ASGITransport(app=_build_app())
	async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
		res = await client.post('/v1/chat/message/stream', json={'message': f'consultaarca CUIT {CUIT_HYPHEN}'})

	assert res.status_code == 200
	frames = _parse_sse(res.text)
	complete = frames[-1][1]
	assert complete['data']['error'] == 'TAXPAYER_NOT_FOUND'
	assert 'no figura en el padrón' in complete['reply']
	assert '500 Server Error' not in complete['reply']
	assert 'TAXPAYER_NOT_FOUND' not in complete['reply']


# ── Resolubilidad de formatters desde el dispatch ──────────────────────────


def test_all_tool_spec_formatters_resolve():
	"""Todo formatter_name del registro ToolSpec es resoluble en el dispatch."""
	from agente_fiscal.domain.tool_spec import TOOL_SPECS

	for key, spec in TOOL_SPECS.items():
		formatter = chat_router._resolve_formatter(spec.formatter_name)
		assert callable(formatter)
		reply = formatter({}, CUIT)  # smoke: no explota con dict vacío
		assert isinstance(reply, str) and reply