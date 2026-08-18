"""Tests de BrowserbaseBrowser (segundo provider real, OFFLINE).

Sin llamadas reales a la API: se monkeypatchea la clase ``Browserbase`` del
módulo con un cliente falso que simula el flujo del SDK (agents create → runs
create → poll retrieve → completed/failed + sessions.debug). Cubre:

  - run_single exitoso: DeudaOutput sin error, live_url == inspect_url,
    on_live_url recibió la URL y parse_output recibió el JSON serializado;
    consolidación con la misma forma que Composio (deudas tipadas).
  - fallo del run (failed + cause) → DeudaOutput.error sin excepción.
  - fallback a list_messages cuando el result del run está vacío.
  - registro del provider: BROWSER_PROVIDER=browserbase resuelve
    BrowserbaseBrowser con key y None sin key (a través de build_browser_provider).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from agente_fiscal.adapters.browser.browserbase import BrowserbaseBrowser
from agente_fiscal.adapters.browser.provider import ALLOWED_PROVIDERS, build_browser_provider
from agente_fiscal.adapters.browser.task import VencimientosDeudasTask
from agente_fiscal.domain.models import ClientConfig, DeudaOutput
from agente_fiscal.ports.browser import BrowserPort
from agente_fiscal.ports.browser_sessions import BrowserSession

INSPECT_URL = 'https://www.browserbase.com/sessions/sess-1?mode=debug'

RESULT_DICT = {
	'deudas': [
		{
			'impuesto': 'IVA',
			'concepto': 'IVA Mensual',
			'periodo': 202608,
			'vencimiento': '2026-08-18',
			'saldo': 100.5,
		},
	],
	'vencimientos': [],
}


def _settings(browserbase_api_key: str = 'sk-test', *, project_id: str = 'proj-1', browser_enabled: bool = True) -> SimpleNamespace:
	return SimpleNamespace(
		browser_enabled=browser_enabled,
		browser_provider='browserbase',
		credentials=SimpleNamespace(
			composio_api_key='',
			clave_fiscal='',
			browserbase_api_key=browserbase_api_key,
			browserbase_project_id=project_id,
		),
	)


class FakeBrowserbase:
	"""Simula el flujo del SDK: create → retrieve (RUNNING → terminal) + debug.

	Los callbacks (retrieve/status/etc.) se vuelcan en secuencias editables
	para poder testear el success y el failure path por separado.
	"""

	def __init__(self) -> None:
		self.agent_id = 'agent-test-1'
		self.run_id = 'run-test-1'
		self.session_id = 'sess-1'
		self.status_seq = ['RUNNING', 'COMPLETED']
		self.results_seq: list = [None, RESULT_DICT]
		self.causes_seq: list = [None, None]
		self.debug_url = INSPECT_URL
		self.messages: list = []
		self.created_agents: list[str] = []
		self.created_kwargs: dict = {}
		# Métricas de sesión falsificadas (sessions.retrieve) + contextos creados.
		self.retrieved_sessions: list[str] = []
		self.contexts_created: list[dict] = []
		self.session_started = datetime(2026, 8, 17, 12, 0, 0, tzinfo=timezone.utc)
		self.session_ended = self.session_started + timedelta(seconds=90)
		self.session_proxy_bytes = 4096

	def agents_create(self, *, name, result_schema=None, system_prompt=None):
		self.created_agents.append(name)
		return SimpleNamespace(agent_id=self.agent_id)

	def runs_create(self, *, task, agent_id=None, result_schema=None, variables=None, browser_settings=None):
		self.created_kwargs = {
			'task': task,
			'agent_id': agent_id,
			'result_schema': result_schema,
		}
		if browser_settings is not None:
			self.created_kwargs['browser_settings'] = browser_settings
		return SimpleNamespace(
			run_id=self.run_id,
			status='RUNNING',  # "running" en la creación
			session_id=self.session_id,
			result=None,
			cause=None,
		)

	def runs_retrieve(self, run_id):
		status = self.status_seq.pop(0)
		result = self.results_seq.pop(0)
		cause = self.causes_seq.pop(0)
		return SimpleNamespace(
			run_id=run_id,
			status=status,
			result=result,
			cause=cause,
			session_id=self.session_id,
		)

	def sessions_debug(self, session_id):
		return SimpleNamespace(inspect_url=self.debug_url, debugger_url=self.debug_url)

	def sessions_retrieve(self, session_id):
		self.retrieved_sessions.append(session_id)
		return SimpleNamespace(
			id=session_id,
			started_at=self.session_started,
			ended_at=self.session_ended,
			proxy_bytes=self.session_proxy_bytes,
			status='COMPLETED',
		)

	def contexts_create(self, *, name, project_id):
		self.contexts_created.append({'name': name, 'project_id': project_id})
		return SimpleNamespace(id=f'ctx-{len(self.contexts_created)}')

	def list_messages(self, run_id):
		return SimpleNamespace(data=self.messages)


class _FakeRuns:
	def __init__(self, fake: FakeBrowserbase) -> None:
		self._fake = fake

	def create(self, **kwargs):
		return self._fake.runs_create(**kwargs)

	def retrieve(self, run_id):
		return self._fake.runs_retrieve(run_id)

	def list_messages(self, run_id, **kwargs):
		return self._fake.list_messages(run_id)


class _FakeAgents:
	def __init__(self, fake: FakeBrowserbase) -> None:
		self._fake = fake
		self.runs = _FakeRuns(fake)

	def create(self, **kwargs):
		return self._fake.agents_create(**kwargs)


class _FakeSessions:
	def __init__(self, fake: FakeBrowserbase) -> None:
		self._fake = fake

	def debug(self, session_id):
		return self._fake.sessions_debug(session_id)

	def retrieve(self, session_id):
		return self._fake.sessions_retrieve(session_id)


class _FakeContexts:
	def __init__(self, fake: FakeBrowserbase) -> None:
		self._fake = fake

	def create(self, *, name=None, project_id=None):
		return self._fake.contexts_create(name=name, project_id=project_id)


class _FakeClient:
	def __init__(self, fake: FakeBrowserbase) -> None:
		self.agents = _FakeAgents(fake)
		self.sessions = _FakeSessions(fake)
		self.contexts = _FakeContexts(fake)


class _SpyTask(VencimientosDeudasTask):
	"""VencimientosDeudasTask que registra el raw que recibió parse_output."""

	def __init__(self, cuit: str, clave: str, cliente_cuit: str) -> None:
		super().__init__(cuit=cuit, clave=clave, cliente_cuit=cliente_cuit)
		self.seen_raw: str | None = None

	def parse_output(self, raw: str) -> dict:
		self.seen_raw = raw
		return super().parse_output(raw)


# ── run_single exitoso ─────────────────────────────────────────────────────


def test_run_single_success_maps_live_url_parse_output(monkeypatch) -> None:
	fake = FakeBrowserbase()
	monkeypatch.setattr('agente_fiscal.adapters.browser.browserbase.Browserbase', lambda **kw: _FakeClient(fake))
	monkeypatch.setattr('agente_fiscal.adapters.browser.browserbase.time.sleep', lambda *a, **k: None)

	browser = BrowserbaseBrowser(api_key='sk-test', project_id='proj-1')
	cliente = ClientConfig(cuit='20301234561')
	seen_urls: list[str] = []
	task = _SpyTask(cuit='20324837796', clave='secreto', cliente_cuit=cliente.cuit)

	out = browser.run_single(cliente, tasks=[task], on_live_url=seen_urls.append)

	assert isinstance(out, DeudaOutput)
	assert out.error is None
	assert out.live_url == INSPECT_URL
	assert seen_urls == [INSPECT_URL]
	# parse_output recibió el result serializado a STRING (json.dumps)
	assert task.seen_raw == json.dumps(RESULT_DICT, ensure_ascii=False)
	# consolidación con la misma forma que Composio: deuda tipada en el modelo
	assert len(out.deudas) == 1
	assert out.deudas[0].impuesto == 'IVA'
	assert out.deudas[0].saldo == 100.5
	# el agent compartido se crea de forma lazy y se pasa a runs.create
	assert fake.created_agents == ['agente-fiscal-arca']
	assert fake.created_kwargs['agent_id'] == 'agent-test-1'
	# el template renderizado lleva los placeholders interpolados + start_url
	assert '20324837796' in fake.created_kwargs['task']
	assert 'auth.afip.gob.ar' in fake.created_kwargs['task']
	assert fake.created_kwargs['result_schema'] is not None


# ── Fallback a list_messages cuando el result está vacío ───────────────────


def test_run_single_falls_back_to_list_messages(monkeypatch) -> None:
	fake = FakeBrowserbase()
	fake.results_seq = [None, None]  # result vacío en el COMPLETED
	raw_assistant = '{"deudas": [], "vencimientos": []}'
	fake.messages = [
		SimpleNamespace(
			message=SimpleNamespace(role='tool', content='tool output'),
		),
		SimpleNamespace(
			message=SimpleNamespace(role='assistant', content=raw_assistant),
		),
	]
	monkeypatch.setattr('agente_fiscal.adapters.browser.browserbase.Browserbase', lambda **kw: _FakeClient(fake))
	monkeypatch.setattr('agente_fiscal.adapters.browser.browserbase.time.sleep', lambda *a, **k: None)

	browser = BrowserbaseBrowser(api_key='sk-test')
	task = _SpyTask(cuit='20324837796', clave='secreto', cliente_cuit='20301234561')

	out = browser.run_single(ClientConfig(cuit='20301234561'), tasks=[task])

	assert out.error is None
	assert task.seen_raw == raw_assistant
	assert task.seen_raw is not None


# ── Fallo del run (failed + cause) → DeudaOutput.error, sin excepción ──────


def test_run_failure_returns_error_without_raising(monkeypatch) -> None:
	fake = FakeBrowserbase()
	fake.status_seq = ['FAILED']
	fake.results_seq = [None]
	fake.causes_seq = [SimpleNamespace(code='RUNNER_HEARTBEAT_LOST', message='agent crash')]
	monkeypatch.setattr('agente_fiscal.adapters.browser.browserbase.Browserbase', lambda **kw: _FakeClient(fake))
	monkeypatch.setattr('agente_fiscal.adapters.browser.browserbase.time.sleep', lambda *a, **k: None)

	browser = BrowserbaseBrowser(api_key='sk-test')
	task = _SpyTask(cuit='20324837796', clave='secreto', cliente_cuit='20301234561')

	out = browser.run_single(ClientConfig(cuit='20301234561'), tasks=[task])

	assert out.error is not None
	assert 'RUNNER_HEARTBEAT_LOST' in out.error
	assert out.error


# ── Registro del provider (a través de build_browser_provider) ─────────────


def test_provider_resolves_browserbase_with_key() -> None:
	provider = build_browser_provider(_settings())
	assert isinstance(provider, BrowserbaseBrowser)
	assert isinstance(provider, BrowserPort)


def test_provider_returns_none_without_browserbase_key() -> None:
	assert build_browser_provider(_settings(browserbase_api_key='')) is None


def test_provider_disabled_returns_none() -> None:
	assert build_browser_provider(_settings(browser_enabled=False)) is None


def test_browserbase_in_allowed_providers() -> None:
	assert 'browserbase' in ALLOWED_PROVIDERS


# ── Reuso de sesión persistida (Browserbase context) ─────────────────────────


def _binding(context_id: str = 'ctx-cookies') -> BrowserSession:
	return BrowserSession(
		id='11111111-1111-7111-8111-111111111111',
		tenant_id='22222222-2222-7222-8222-222222222222',
		provider='browserbase',
		context_id=context_id,
		status='in_use',
	)


def test_with_binding_passes_browser_settings_context(monkeypatch) -> None:
	"""Con binding reutilizable, runs.create recibe browser_settings.context."""
	fake = FakeBrowserbase()
	monkeypatch.setattr('agente_fiscal.adapters.browser.browserbase.Browserbase', lambda **kw: _FakeClient(fake))
	monkeypatch.setattr('agente_fiscal.adapters.browser.browserbase.time.sleep', lambda *a, **k: None)

	browser = BrowserbaseBrowser(api_key='sk-test', project_id='proj-1', binding=_binding())
	task = _SpyTask(cuit='20324837796', clave='secreto', cliente_cuit='20301234561')

	out = browser.run_single(ClientConfig(cuit='20301234561'), tasks=[task])

	assert out.error is None
	assert fake.created_kwargs['browser_settings'] == {
		'context': {'id': 'ctx-cookies', 'persist': True},
	}
	# Binding reutilizable → NO se crea contexto nuevo.
	assert fake.contexts_created == []


def test_without_binding_runs_create_has_no_browser_settings(monkeypatch) -> None:
	"""Sin binding ni store: runs.create NO pasa browser_settings (efímero)."""
	fake = FakeBrowserbase()
	monkeypatch.setattr('agente_fiscal.adapters.browser.browserbase.Browserbase', lambda **kw: _FakeClient(fake))
	monkeypatch.setattr('agente_fiscal.adapters.browser.browserbase.time.sleep', lambda *a, **k: None)

	browser = BrowserbaseBrowser(api_key='sk-test')
	task = _SpyTask(cuit='20324837796', clave='secreto', cliente_cuit='20301234561')

	out = browser.run_single(ClientConfig(cuit='20301234561'), tasks=[task])

	assert out.error is None
	assert 'browser_settings' not in fake.created_kwargs
	assert fake.contexts_created == []


def test_with_store_and_no_binding_creates_context_and_metrics(monkeypatch) -> None:
	"""Efímero con store: crea contexto nuevo en Browserbase y lo entrega en metrics."""
	fake = FakeBrowserbase()
	monkeypatch.setattr('agente_fiscal.adapters.browser.browserbase.Browserbase', lambda **kw: _FakeClient(fake))
	monkeypatch.setattr('agente_fiscal.adapters.browser.browserbase.time.sleep', lambda *a, **k: None)

	received: dict = {}
	browser = BrowserbaseBrowser(api_key='sk-test', project_id='proj-1', session_store=object())
	task = _SpyTask(cuit='20324837796', clave='secreto', cliente_cuit='20301234561')

	out = browser.run_single(
		ClientConfig(cuit='20301234561'),
		tasks=[task],
		on_task_metrics=received.update,
	)

	assert out.error is None
	assert len(fake.contexts_created) == 1
	ctx_id = fake.contexts_created[0]['name']
	assert ctx_id.startswith('af-')
	assert fake.created_kwargs['browser_settings']['context']['id'] == 'ctx-1'
	# El contexto nuevo se devuelve en las métricas para persistirlo después.
	assert received['context_id'] == 'ctx-1'


def test_on_task_metrics_reports_real_duration_and_proxy_bytes(monkeypatch) -> None:
	"""Run COMPLETED → on_task_metrics con métricas reales de sessions.retrieve."""
	fake = FakeBrowserbase()
	monkeypatch.setattr('agente_fiscal.adapters.browser.browserbase.Browserbase', lambda **kw: _FakeClient(fake))
	monkeypatch.setattr('agente_fiscal.adapters.browser.browserbase.time.sleep', lambda *a, **k: None)

	received: dict = {}
	browser = BrowserbaseBrowser(api_key='sk-test', project_id='proj-1')
	task = _SpyTask(cuit='20324837796', clave='secreto', cliente_cuit='20301234561')

	out = browser.run_single(
		ClientConfig(cuit='20301234561'),
		tasks=[task],
		on_task_metrics=received.update,
	)

	assert out.error is None
	assert fake.retrieved_sessions == ['sess-1']
	assert received['session_id'] == 'sess-1'
	# duración real = ended - started (90s) → 90000ms; proxy bytes reales.
	assert received['duration_ms'] == 90000
	assert received['proxy_bytes'] == 4096
	assert received['status'] == 'COMPLETED'
	assert received['cost_cents'] == 0