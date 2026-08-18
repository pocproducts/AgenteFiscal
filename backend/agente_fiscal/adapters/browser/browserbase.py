"""BrowserbaseBrowser — browser automation via the Browserbase Agents API.

Segundo provider real de ``BrowserPort``. En lugar de la API REST del Browser
Tool de Composio, maneja la API de Agents de Browserbase (tarea en lenguaje
natural → browser remoto → resultado estructurado), preservando la semántica
observable de ComposioBrowser: templates NL por task, URL en vivo de la sesión,
lista de ``TaskResult`` y un ``DeudaOutput`` con la MISMA forma (la
consolidación se reutiliza de ComposioBrowser para que ambos providers no
dupliquen el mapeo a modelos de dominio y no diverjan).

Pipeline por BrowserTask:
    1. Renderizar el template NL (sustitución de ``{placeholder}``, igual que
       Composio).
    2. Crear el agent compartido de forma lazy (``agents.create``) UNA vez por
       instancia del provider.
    3. ``agents.runs.create(task=<NL renderizado>, agent_id=<agent>,
       result_schema=<JSON schema compartido>)``.
    4. Pollear ``agents.runs.retrieve(run_id)`` cada ~5s hasta terminal o
       timeout.
    5. URL en vivo vía ``sessions.debug(session_id)`` apenas existe la sesión.
    6. Alimentar el resultado serializado a ``task.parse_output`` y consolidar
       en un ``DeudaOutput``.

El agent se crea con un system prompt que ordena seguir el template EXACTO y
devolver únicamente el JSON que los parsers esperan (el mismo shape que
Composio produce). Nunca levanta excepciones hacia afuera: todo error se
devuelve dentro de ``DeudaOutput.error``.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Optional

from browserbase import Browserbase

from agente_fiscal.adapters.browser.composio import ComposioBrowser
from agente_fiscal.adapters.browser.task import (
	BrowserTask,
	TaskResult,
	VencimientosDeudasTask,
	_parse_arca_error,
)
from agente_fiscal.domain.models import ClientConfig, DeudaOutput
from agente_fiscal.ports.browser_sessions import BrowserSession

logger = logging.getLogger(__name__)

BROWSERBASE_POLL_INTERVAL = 5  # seconds entre polls de retrieve
BROWSERBASE_DEFAULT_TIMEOUT = 600  # seconds por task (default)

#: Estados terminales del SDK (PENDING → RUNNING → COMPLETED/FAILED/STOPPED/TIMED_OUT).
_TERMINAL = frozenset({'COMPLETED', 'FAILED', 'STOPPED', 'TIMED_OUT', 'CANCELED'})
#: Estados "en curso" (incluye el alias ``queued`` usado en documentación).
_RUNNING = frozenset({'PENDING', 'QUEUED', 'RUNNING'})

#: System prompt del agent compartido: seguir el template exacto y emitir solo JSON.
SYSTEM_PROMPT = (
	'Eres un agente de navegación web. Ejecuta las instrucciones de la tarea '
	'exactamente como están escritas: navega, autentica cuando corresponda y '
	'extrae los datos requeridos. Cuando la tarea indique el formato del '
	'resultado, devuelve ÚNICAMENTE el objeto JSON pedido, sin texto adicional, '
	'sin markdown y sin explicaciones.'
)

#: JSON Schema compartido por agent y runs. La unión de todos los shapes que
#: producen los parsers de ``adapters/browser/task.py`` (deudas/vencimientos,
#: planes, registro, IIBB) con todas las propiedades opcionales: el agent
#: devuelve el subconjunto que corresponda a la task y el parser lo valida.
RESULT_SCHEMA: dict[str, Any] = {
	'type': 'object',
	'properties': {
		'deudas': {'type': 'array', 'items': {'type': 'object'}},
		'vencimientos': {'type': 'array', 'items': {'type': 'object'}},
		'planes': {'type': 'array', 'items': {'type': 'object'}},
		'saldos': {'type': 'array', 'items': {'type': 'object'}},
		'domicilios': {'type': 'array', 'items': {'type': 'object'}},
		'actividades': {'type': 'array', 'items': {'type': 'object'}},
		'impuestos': {'type': 'array', 'items': {'type': 'object'}},
		'puntos_de_venta': {'type': 'array', 'items': {'type': 'object'}},
		'iibb_jurisdicciones': {'type': 'array', 'items': {'type': 'object'}},
		'cuotas_vencidas': {'type': 'array', 'items': {'type': 'object'}},
		'deuda_actual': {'type': ['number', 'null']},
		'jurisdiccion': {'type': ['string', 'null']},
		'plan_pagos': {'type': 'object'},
	},
	'additionalProperties': True,
}


class BrowserbaseError(Exception):
	"""Error de la API de Browserbase o de la ejecución de un run."""


class BrowserbaseBrowser:
	"""Browser automation via la API de Agents de Browserbase (NL instructions).

	Cada cliente/task se resuelve en un run remoto (el browser corre en el
	cloud de Browserbase). El agent compartido se crea de forma lazy y se
	reutiliza entre runs de la misma instancia del provider.

	Args:
	    api_key: API key de Browserbase (https://www.browserbase.com/dashboard).
	    project_id: ID de proyecto opcional. Se conserva para futuro scope de
	        proyecto; el cliente SDK actual no lo acepta en el constructor.
	    headed: Flag de paridad de API (en Browserbase la sesión es siempre
	        visible vía live URL).
	    default_timeout: Timeout en segundos por task cuando la task no define
	        el propio (default 600).
	"""

	def __init__(
		self,
		api_key: str,
		project_id: Optional[str] = None,
		*,
		headed: bool = False,
		default_timeout: int = BROWSERBASE_DEFAULT_TIMEOUT,
		session_store: Optional[object] = None,
		binding: Optional[BrowserSession] = None,
	) -> None:
		self._api_key = api_key
		self._project_id = project_id
		self._headed = headed
		self._default_timeout = default_timeout or BROWSERBASE_DEFAULT_TIMEOUT
		# Creado de forma lazy para no tocar red ni construir transport en el factory.
		self._client: Optional[Browserbase] = None
		self._agent_id: Optional[str] = None
		self._live_url = ''
		# Consolidación reutilizada de ComposioBrowser (misma forma de DeudaOutput).
		self._consolidator: Optional[ComposioBrowser] = None
		# Reuso de sesión persistida: el store NO se toca en el flujo síncrono —
		# el wiring async recibe on_task_metrics y hace el persist con await.
		self._session_store = session_store
		self._session_binding = binding
		# Marca de tiempo del run actual (fallback de duration_ms sin sesión).
		self._run_started: Optional[float] = None

	# ── Internals ──────────────────────────────────────────────────────────

	def _get_client(self) -> Browserbase:
		"""Cliente SDK lazy (una sola instancia por provider)."""
		if self._client is None:
			if self._project_id:
				logger.debug(
					'Browserbase project_id=%s (reservado; el cliente SDK no acepta scope por proyecto)',
					self._project_id,
				)
			self._client = Browserbase(api_key=self._api_key)
		return self._client

	def _ensure_agent(self) -> str:
		"""Crea (una sola vez) el agent compartido y devuelve su id."""
		if self._agent_id:
			return self._agent_id
		resp = self._get_client().agents.create(
			name='agente-fiscal-arca',
			result_schema=RESULT_SCHEMA,
			system_prompt=SYSTEM_PROMPT,
		)
		agent_id = getattr(resp, 'agent_id', '')
		if not agent_id:
			raise BrowserbaseError('Browserbase agents.create no devolvió agent_id')
		self._agent_id = agent_id
		logger.info('Agent Browserbase creado: %s', agent_id)
		return agent_id

	@staticmethod
	def _render(task: BrowserTask) -> str:
		"""Renderiza el template NL igual que Composio: replace de placeholders.

		Browserbase no expone ``secrets``/``startUrl`` en runs.create; el
		template ya embebe las credenciales (``{cuit}``/``{clave}``), así que la
		URL inicial se anexa al texto de la task (mismo efecto que el
		``startUrl`` de Composio).
		"""
		instruction = task.template
		if task.template_params:
			for key, value in task.template_params.items():
				instruction = instruction.replace(f'{{{key}}}', str(value))
		if task.needs_auth and task.start_url:
			instruction = f'{instruction}\n\nIniciá la navegación en esta URL: {task.start_url}'
		return instruction

	def _live_url_for(self, session_id: Optional[str]) -> str:
		"""Mapea la URL en vivo de la sesión (inspect/debug URL de Browserbase)."""
		if not session_id:
			return ''
		try:
			urls = self._get_client().sessions.debug(session_id)
		except Exception as e:
			logger.debug('No se pudo obtener URL de sesión %s: %s', session_id, e)
			return ''
		return (
			getattr(urls, 'inspect_url', None)
			or getattr(urls, 'debugger_url', None)
			or getattr(urls, 'debugger_fullscreen_url', None)
			or ''
		)

	def _context_slug(self) -> str:
		"""Nombre corto y sanitizado del contexto en Browserbase (sin PII ni CUIT).

		Si hay binding se deriva del tenant/profile (ids UUID en slug, NO son
		datos sensibles); sin binding se usa un sufijo aleatorio. Nunca expone
		credenciales ni CUIT reales al provider.
		"""
		b = self._session_binding
		if b is not None and getattr(b, 'tenant_id', ''):
			tid = str(b.tenant_id)[:8]
			pid = str(getattr(b, 'profile_id', '') or '')[:8] or 'guest'
			return f'af-{tid}-{pid}'
		return f'af-{uuid.uuid4().hex[:8]}'

	def _ensure_context(self) -> str:
		"""Crea un contexto persistido nuevo en Browserbase (best effort).

		Se usa cuando hay store pero NO hay binding reutilizable: el run corre
		efímero e igual se persiste el contexto nuevo para el próximo run. Un
		error de red NO rompe el run — se loguea y se devuelve ''.
		"""
		if self._session_store is None:
			return ''
		try:
			resp = self._get_client().contexts.create(
				name=self._context_slug(),
				project_id=self._project_id,
			)
			ctx_id = getattr(resp, 'id', '')
			if ctx_id:
				logger.info('Contexto Browserbase persistido creado: %s', ctx_id)
				return ctx_id
		except Exception as e:
			logger.debug('No se pudo crear contexto Browserbase: %s', e)
		return ''

	def _collect_metrics(
		self,
		task_name: str,
		session_id: Optional[str],
		context_id: Optional[str],
		status: str,
	) -> dict[str, Any]:
		"""Métricas reales del run: una sola llamada a sessions.retrieve (best effort).

		``started_at``/``ended_at`` vienen de la sesión; si faltan, ``duration_ms``
		se aproxima con ``time.monotonic`` del run. ``cost_cents`` se deja en 0:
		el SDK de Browserbase no expone costo USD por sesión.
		"""
		started_at: Optional[datetime] = None
		ended_at: Optional[datetime] = None
		proxy_bytes: Optional[int] = None
		if session_id:
			try:
				sess = self._get_client().sessions.retrieve(session_id)
				started_at = getattr(sess, 'started_at', None)
				ended_at = getattr(sess, 'ended_at', None)
				proxy_bytes = getattr(sess, 'proxy_bytes', None)
			except Exception as e:
				logger.debug('No se pudieron obtener métricas de la sesión %s: %s', session_id, e)
		duration_ms: Optional[int] = None
		if started_at is not None and ended_at is not None:
			try:
				duration_ms = int((ended_at - started_at).total_seconds() * 1000)
			except (TypeError, ValueError):
				duration_ms = None
		if duration_ms is None and self._run_started is not None:
			duration_ms = int((time.monotonic() - self._run_started) * 1000)
		return {
			'task_name': task_name,
			'session_id': session_id or '',
			'context_id': context_id or '',
			'proxy_bytes': proxy_bytes,
			'duration_ms': duration_ms,
			'cost_cents': 0,
			'started_at': started_at.isoformat() if started_at else None,
			'ended_at': ended_at.isoformat() if ended_at else None,
			'status': status,
		}

	def _last_assistant_text(self, run_id: str) -> str:
		"""Fallback: último texto del assistant desde list_messages (result vacío)."""
		try:
			resp = self._get_client().agents.runs.list_messages(run_id)
		except Exception as e:
			logger.debug('list_messages fallback falló para %s: %s', run_id, e)
			return ''
		for item in reversed(getattr(resp, 'data', None) or []):
			msg = getattr(item, 'message', None)
			if msg is None or getattr(msg, 'role', None) != 'assistant':
				continue
			content = getattr(msg, 'content', None)
			if isinstance(content, str):
				return content
			if isinstance(content, list):
				texts = [part.text for part in content if getattr(part, 'text', None)]
				if texts:
					return texts[-1]
		return ''

	def _extract_result(self, run, run_id: str) -> str:
		"""Serializa el result del run a STRING para task.parse_output.

		Si ``result`` es dict (con result_schema) se serializa a JSON; si es
		str se usa directo; si está vacío se intenta list_messages.
		"""
		result = getattr(run, 'result', None)
		if isinstance(result, str):
			return result
		if isinstance(result, dict):
			try:
				return json.dumps(result, ensure_ascii=False)
			except (TypeError, ValueError) as e:
				logger.warning('No se pudo serializar result de run %s: %s', run_id, e)
				return str(result)
		if result is None:
			return self._last_assistant_text(run_id)
		return str(result)

	def _failure_message(self, run, run_id: str, status: str) -> str:
		"""Mensaje de error en el tono de Composio (status + cause)."""
		cause = getattr(run, 'cause', None)
		if cause:
			code = getattr(cause, 'code', '') or ''
			message = getattr(cause, 'message', '') or ''
			detail = f'{code}: {message}' if code else message
			if detail:
				return f'Browserbase: run {run_id} terminó con status={status} — {detail}'
		return f'Browserbase: run {run_id} terminó con status={status}'

	def _execute_task(
		self,
		task: BrowserTask,
		instruction: str,
		cuit: str,
		echo_func: Optional[Callable[[str], None]] = None,
		on_live_url: Optional[Callable[[str], None]] = None,
		on_step: Optional[Callable[[int, str, str, str], None]] = None,
		on_task_metrics: Optional[Callable[[dict], None]] = None,
	) -> TaskResult:
		"""Ejecuta UNA task: create → live URL → poll → parse → TaskResult.

		Con binding de sesión persistida, el run se crea con
		``browser_settings={'context': {'id', 'persist': True}}`` para que las
		cookies del login ARCA sobrevivan entre tools. Sin binding usable y con
		store, se crea un contexto nuevo en Browserbase (best effort) y se
		persiste su id vía ``on_task_metrics`` al terminar el run.

		Raises:
		    TimeoutError: si el run no termina dentro de task.timeout.
		    BrowserbaseError: si el run termina en failed/stopped/timed_out/canceled.
		"""
		client = self._get_client()
		agent_id = self._ensure_agent()
		timeout = task.timeout or self._default_timeout

		# ── Reuso de sesión persistida (Browserbase context) ───────────────
		run_kwargs: dict[str, Any] = {
			'task': instruction,
			'agent_id': agent_id,
			'result_schema': RESULT_SCHEMA,
		}
		context_id: Optional[str] = None
		binding = self._session_binding
		if binding is not None and getattr(binding, 'context_id', ''):
			# Hay contexto persistido: el run arranca ya logueado (cookies ARCA).
			context_id = binding.context_id
			run_kwargs['browser_settings'] = {
				'context': {'id': context_id, 'persist': True},
			}
		elif self._session_store is not None:
			# Efímero + store: crear contexto nuevo para el próximo reuso.
			context_id = self._ensure_context()
			if context_id:
				run_kwargs['browser_settings'] = {
					'context': {'id': context_id, 'persist': True},
				}

		self._run_started = time.monotonic()
		run = client.agents.runs.create(**run_kwargs)
		run_id = getattr(run, 'run_id', '')
		if not run_id:
			raise BrowserbaseError('Browserbase runs.create no devolvió run_id')

		# ── Live URL — siempre que la sesión exista ────────────────────────
		session_id = getattr(run, 'session_id', None)
		live_url = self._live_url_for(session_id)
		if live_url:
			self._live_url = live_url
			logger.info('  ⛓ Live: %s', live_url)
			if echo_func:
				echo_func(f'  ⛓ Live: {live_url}')
			if on_live_url:
				on_live_url(live_url)

		# ── Poll hasta terminal o timeout ─────────────────────────────────
		status = (getattr(run, 'status', '') or '').upper()
		if status not in _TERMINAL:
			seen_running = status in _RUNNING
			start = time.monotonic()
			while time.monotonic() - start < timeout:
				run = client.agents.runs.retrieve(run_id)
				status = (getattr(run, 'status', '') or '').upper()
				if status in _TERMINAL:
					break
				if status in _RUNNING and not seen_running:
					seen_running = True
					if on_step:
						on_step(1, f'{task.name} en ejecución', live_url, 'running')
					if echo_func:
						echo_func(f'  🚀 {task.name}: run {run_id} en ejecución ...')
				time.sleep(BROWSERBASE_POLL_INTERVAL)
			else:
				raise TimeoutError(f'Run {run_id} timed out after {timeout}s')

		if status in ('FAILED', 'STOPPED', 'TIMED_OUT', 'CANCELED'):
			raise BrowserbaseError(self._failure_message(run, run_id, status))

		# ── COMPLETED → extraer y parsear ────────────────────────────────
		raw = self._extract_result(run, run_id)
		if on_step:
			on_step(1, '', '', 'finished')
		logger.info('Output crudo de %s (primeros 500): %s', task.name, raw[:500])

		# ── Métricas reales del run (una sola retrieve + callback) ────────
		if on_task_metrics:
			session_id = session_id or getattr(run, 'session_id', None)
			metrics = self._collect_metrics(task.name, session_id, context_id, status)
			logger.info(
				'Run %s COMPLETED | session=%s | proxy_bytes=%s | duration_ms=%s',
				run_id,
				metrics['session_id'],
				metrics['proxy_bytes'],
				metrics['duration_ms'],
			)
			on_task_metrics(metrics)

		parsed_data = task.parse_output(raw)
		arca_error = _parse_arca_error(raw)
		return TaskResult(
			task_name=task.name,
			success=arca_error is None,
			raw_output=raw,
			parsed_data=parsed_data,
			arca_error=arca_error,
			task_id=run_id,
		)

	def _consolidate(self, cliente: Optional[ClientConfig], results: list[TaskResult]) -> DeudaOutput:
		"""Consolida TaskResults en DeudaOutput con la MISMA forma que Composio.

		Reutiliza ComposioBrowser._consolidate (mapeo a modelos de dominio)
		para que ambos providers produzcan un DeudaOutput con shape idéntico
		sin duplicar la conversión. El consolidator no toca la red: es puro
		mapping de datos.
		"""
		if self._consolidator is None:
			self._consolidator = ComposioBrowser(
				composio_api_key='',
				estudio_cuit='',
				estudio_clave='',
			)
		self._consolidator._live_url = self._live_url
		return self._consolidator._consolidate(cliente, results)

	def _run_single(
		self,
		cliente: Optional[ClientConfig],
		tasks: Optional[list[BrowserTask]] = None,
		echo_func: Optional[Callable[[str], None]] = None,
		on_live_url: Optional[Callable[[str], None]] = None,
		on_step: Optional[Callable[[int, str, str, str], None]] = None,
		on_task_metrics: Optional[Callable[[dict], None]] = None,
	) -> DeudaOutput:
		"""Procesa un cliente con N tasks de Browserbase secuencialmente.

		Si tasks es None, usa [VencimientosDeudasTask()] con las credenciales
		del cliente (Browserbase no tiene credenciales propias de estudio).
		Nunca propaga excepción: todo error se devuelve en DeudaOutput.error
		(consolidando datos parciales de tasks exitosas previas, igual que
		Composio).
		"""
		cuit = cliente.cuit if cliente else ''
		if tasks is None:
			clave = cliente.clave_fiscal or '' if cliente else ''
			tasks = [VencimientosDeudasTask(cuit=cuit, clave=clave, cliente_cuit=cuit)]

		results: list[TaskResult] = []

		try:
			for i, task in enumerate(tasks, 1):
				if echo_func:
					echo_func(f'  ─── [{i}/{len(tasks)}] {task.name} ───')
				logger.info('─── [Task %d/%d] %s ───', i, len(tasks), task.name)

				instruction = self._render(task)
				if echo_func:
					echo_func(f'  ▶ {task.name}: {cuit} ...')

				result = self._execute_task(
					task,
					instruction,
					cuit,
					echo_func=echo_func,
					on_live_url=on_live_url,
					on_step=on_step,
					on_task_metrics=on_task_metrics,
				)
				results.append(result)

				if result.arca_error or not result.success:
					msg = f'✘ Task {task.name} falló para {cuit}: {result.arca_error or result.error}'
					logger.error(msg)
					if echo_func:
						echo_func(f'  ❌ {msg}')
					break

				data_desc = (
					', '.join(f'{k}={len(v)}' for k, v in result.parsed_data.items() if isinstance(v, list))
					if result.parsed_data
					else '✓'
				)
				logger.info('✓ Task %s completada | %s', task.name, data_desc or 'OK')
				if echo_func:
					echo_func(f'  ✓ {task.name} completada | {data_desc or "OK"}')

			total_ok = sum(1 for r in results if r.success)
			logger.info('─── Resumen: %d/%d tasks exitosas ───', total_ok, len(results))
			if echo_func:
				echo_func(f'  Browserbase: {total_ok}/{len(tasks)} tasks completadas')
			return self._consolidate(cliente, results)

		except TimeoutError:
			task_name = tasks[len(results)].name if len(results) < len(tasks) else 'desconocida'
			timeout = tasks[len(results)].timeout if len(results) < len(tasks) else self._default_timeout
			logger.error('✘ Timeout — %s excedió el límite (%ss)', task_name, timeout)
			if results:
				output = self._consolidate(cliente, results)
				output.error = f'Timeout — {task_name} excedió el límite de espera'
				return output
			return DeudaOutput(
				cuit=cuit,
				extraido_el=datetime.now(),
				error=f'Timeout — {task_name} excedió el límite de espera',
			)
		except BrowserbaseError as e:
			logger.error('Error Browserbase para %s: %s', cuit, e)
			if results:
				output = self._consolidate(cliente, results)
				output.error = str(e)
				return output
			return DeudaOutput(cuit=cuit, extraido_el=datetime.now(), error=str(e))
		except Exception as e:
			logger.error('Error inesperado para %s: %s', cuit, e)
			if results:
				output = self._consolidate(cliente, results)
				output.error = f'Error inesperado: {e}'
				return output
			return DeudaOutput(cuit=cuit, extraido_el=datetime.now(), error=f'Error inesperado: {e}')

	# ── Public API (BrowserPort) ───────────────────────────────────────────

	def run_single(
		self,
		cliente: Optional[ClientConfig] = None,
		tasks: Optional[list[BrowserTask]] = None,
		echo_func: Optional[Callable[[str], None]] = None,
		on_live_url: Optional[Callable[[str], None]] = None,
		on_step: Optional[Callable[[int, str, str, str], None]] = None,
		on_task_metrics: Optional[Callable[[dict], None]] = None,
	) -> DeudaOutput:
		"""Wrapper síncrono. Nunca propaga excepción."""
		try:
			return self._run_single(
				cliente,
				tasks=tasks,
				echo_func=echo_func,
				on_live_url=on_live_url,
				on_step=on_step,
				on_task_metrics=on_task_metrics,
			)
		except Exception as e:
			cuit = cliente.cuit if cliente else ''
			logger.error('run_single error for %s: %s', cuit, e)
			return DeudaOutput(cuit=cuit, extraido_el=datetime.now(), error=str(e))

	async def run_all(self, clientes: list[ClientConfig]) -> list[DeudaOutput]:
		"""Procesa cada cliente en orden (1:1 con la entrada).

		Secuencial a propósito para v1: determinista y sin multiplicar sesiones
		cloud. Composio paraleliza con asyncio.gather; acá la secuencia es
		aceptable y más predecible hasta que se requiera concurrencia.
		"""
		return [self.run_single(cliente) for cliente in clientes]

	async def close(self) -> None:
		"""Cleanup: cierra el transport HTTP local del SDK si fue creado.

		Los runs y el agent viven del lado de Browserbase (server-side), así
		que no se borra el agent; alcanza con liberar el cliente local.
		"""
		client = self._client
		if client is not None:
			close = getattr(client, 'close', None)
			if close is not None:
				try:
					close()
				except Exception as e:
					logger.debug('Error cerrando Browserbase client: %s', e)
		logger.info('BrowserbaseBrowser closed')
