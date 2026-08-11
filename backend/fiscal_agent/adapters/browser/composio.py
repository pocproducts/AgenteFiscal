"""ComposioBrowser — browser automation via Composio Browser Tool.

Reemplaza ArcaBrowser (Playwright + YAML). Usa la API REST de Composio
directamente (no el SDK Python) para crear sesiones de navegador cloud,
ejecutar instrucciones en lenguaje natural, y extraer datos de ARCA.

Tools de Composio utilizados:
    - BROWSER_TOOL_CREATE_TASK      → Crear tarea de navegación con instrucciones NL
    - BROWSER_TOOL_WATCH_TASK       → Esperar completitud con timeout
    - BROWSER_TOOL_GET_SESSION      → Obtener URL en vivo (modo headed)
    - BROWSER_TOOL_STOP_TASK        → Detener tarea en timeout/error/finally

Endpoint base: POST https://backend.composio.dev/api/v3.1/tools/execute/{tool_slug}
Autenticación: header ``x-api-key``
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
from datetime import datetime
from typing import Any, Callable, Optional

import requests

from fiscal_agent.adapters.browser.workflows import TEMPLATE_FULL
from fiscal_agent.domain.models import (
	ClientConfig,
	DeudaDetail,
	DeudaItem,
	DeudaOutput,
	FacilidadDatosPlan,
	FacilidadPlan,
	FacilidadPlanCuota,
	FacilidadProximoVencimiento,
	IIBBCuotaVencida,
	RegistroActividad,
	RegistroDomicilio,
	RegistroImpuesto,
	RegistroOutput,
	RegistroIIBBJurisdiccion,
	RegistroPuntoVenta,
	Tenant,
	VencimientoDeuda,
)

from fiscal_agent.adapters.browser.task import (
	BrowserTask,
	FacilidadesTask,
	VencimientosDeudasTask,
	TaskResult,
	_parse_arca_error,
	_parse_extract_output,
)

logger = logging.getLogger(__name__)

COMPOSIO_BASE_URL = 'https://backend.composio.dev/api/v3.1/tools/execute'
COMPOSIO_POLL_INTERVAL = 2  # seconds between WatchTask polls
COMPOSIO_DEFAULT_TIMEOUT = 300  # seconds per task (5 min max)


class ComposioError(Exception):
	"""Error from Composio API or task execution."""


class ComposioBrowser:
	"""Browser automation via Composio Browser Tool (NL instructions).

	Each client gets its own Composio session, running in parallel
	via ``asyncio.gather``. STOP_TASK runs in ``finally`` per session
	to avoid cloud costs from dangling tasks.

	Args:
	    composio_api_key: API key from https://dashboard.composio.dev/settings
	    estudio_cuit: CUIT del estudio contable (para login en ARCA)
	    estudio_clave: Clave fiscal del estudio
	    headed: Si True, obtiene y loggea la URL en vivo de la sesión Composio
	    tenant: Tenant opcional. Si se provee, usa sus credenciales (cuit, clave_fiscal)
	        en lugar de las globales del estudio.
	"""

	def __init__(
		self,
		composio_api_key: str,
		estudio_cuit: str,
		estudio_clave: str,
		headed: bool = False,
		tenant: Tenant | None = None,
	) -> None:
		self._api_key = composio_api_key
		self._estudio_cuit = estudio_cuit
		self._estudio_clave = estudio_clave
		self._headed = headed
		self._tenant = tenant
		self._http_headers = {
			'x-api-key': self._api_key,
			'Content-Type': 'application/json',
		}

	@property
	def _login_cuit(self) -> str:
		"""CUIT for ARCA login — tenant's if available, otherwise global."""
		return self._tenant.cuit if self._tenant else self._estudio_cuit

	@property
	def _login_clave(self) -> str:
		"""Clave fiscal for ARCA login — tenant's if available, otherwise global."""
		return self._tenant.clave_fiscal if self._tenant else self._estudio_clave

	# ── Internal HTTP helpers ───────────────────────────────────────────────

	def _execute_tool(self, slug: str, params: dict, request_timeout: int = 30) -> dict[str, Any]:
		"""Execute a Composio tool via REST API.

		POST ``{COMPOSIO_BASE_URL}/{slug}`` con headers ``x-api-key``.
		Los parámetros se envuelven automáticamente en ``arguments``
		(API v3.1 espera ``{"arguments": {...}}``, no parámetros sueltos).

		Args:
		    slug: Tool slug (e.g. ``'BROWSER_TOOL_CREATE_TASK'``).
		    params: Input parameters for the tool (sin wrapper arguments).
		    request_timeout: Timeout en segundos para el HTTP request.
		        Usar 180+ para WATCH_TASK (long-polling).

		Returns:
		    Parsed response data dict (``body.data`` deserializado).

		Raises:
		    ComposioError: If the API returns an error or the tool execution fails.
		"""
		url = f'{COMPOSIO_BASE_URL}/{slug}'
		logger.debug('Composio API POST %s', slug)

		# API v3.1 espera user_id (para aislar perfiles de browser) + arguments
		payload = {'arguments': params, 'user_id': self._login_cuit}

		try:
			resp = requests.post(url, headers=self._http_headers, json=payload, timeout=request_timeout)
		except requests.RequestException as e:
			raise ComposioError(f'Composio request failed ({slug}): {e}') from e

		# Log response status y texto crudo para debug de API
		logger.debug(
			'🔍 Composio %s: HTTP %s, req_body=%s, resp_body=%s', slug, resp.status_code, str(payload)[:200], resp.text[:500]
		)

		try:
			resp.raise_for_status()
		except requests.RequestException as e:
			raise ComposioError(f'Composio API error ({slug}): HTTP {resp.status_code} — {resp.text[:300]}') from e

		try:
			body = resp.json()
		except json.JSONDecodeError as e:
			raise ComposioError(
				f'Composio {slug} response no es JSON válido. HTTP {resp.status_code}, body={resp.text[:500]}'
			) from e

		if not isinstance(body, dict):
			raise ComposioError(
				f'Composio {slug} response body no es un objeto. Tipo={type(body).__name__}, body={str(body)[:300]}'
			)

		if not body.get('successful', False):
			err_msg = body.get('error', f'Tool {slug} returned unsuccessful')
			raise ComposioError(f'Composio {slug} unsuccessful: {err_msg}')

		raw_data = body.get('data', '{}')

		# Log estructura de la respuesta para debug
		body_keys = list(body.keys())
		data_type = type(raw_data).__name__
		logger.debug(
			'Composio %s body: keys=%s, data_type=%s, data_preview=%s',
			slug,
			body_keys,
			data_type,
			str(raw_data)[:300],
		)

		if isinstance(raw_data, str):
			if not raw_data.strip():
				return {}
			try:
				parsed = json.loads(raw_data)
				# json.loads puede devolver string/number si raw_data es
				# un JSON literal de tipo primitivo (ej: '\n    "deuda_actual"'
				# se parsea como el string 'deuda_actual'). El resto del código
				# espera un dict, así que si no lo es, lo envolvemos en _raw.
				if isinstance(parsed, dict):
					return parsed
				logger.warning(
					'Composio data parsed as non-dict (%s): %s',
					type(parsed).__name__,
					str(parsed)[:200],
				)
				return {'_raw': str(parsed)[:1000]}
			except json.JSONDecodeError as e:
				logger.warning(
					'Composio data JSONDecodeError (%s). data[:500]=%s',
					e,
					raw_data[:500],
				)
			# Si no es JSON, devolver como dict con _raw para debug
			return {'_raw': raw_data[:1000]}
		return raw_data if isinstance(raw_data, dict) else {}

	# ── Tool wrappers ───────────────────────────────────────────────────────

	async def _create_task(
		self,
		instruction: str,
		secrets: Optional[dict] = None,
		start_url: Optional[str] = None,
		session_id: Optional[str] = None,
	) -> dict[str, Any]:
		"""BROWSER_TOOL_CREATE_TASK — Crear tarea de navegación con instrucciones NL.

		Args:
		    instruction: Instrucciones en lenguaje natural para el AI agent.
		    secrets: Dict ``{dominio: 'user:pass'}`` para autologin en sitios.
		    start_url: URL inicial donde empezar la navegación.
		    session_id: ID de sesión existente para continuar (misma sesión =
		        cookies preservadas entre tasks).

		Returns:
		    Dict con ``taskId``, ``sessionId`` (``browser_session_id``), etc.
		"""
		params: dict[str, Any] = {'task': instruction}
		if secrets:
			params['secrets'] = secrets
		if start_url:
			params['startUrl'] = start_url
		if session_id:
			params['sessionId'] = session_id

		return await asyncio.to_thread(
			self._execute_tool,
			'BROWSER_TOOL_CREATE_TASK',
			params,
		)
		# Log completo cuando falta taskId (debug de API)
		if not result.get('taskId') and not result.get('id'):
			logger.warning(
				'CreateTask response sin taskId. Keys=%s, preview=%s',
				list(result.keys()),
				str(result)[:300],
			)
		return result

	async def _watch_task(
		self,
		task_id: str,
		timeout: int = COMPOSIO_DEFAULT_TIMEOUT,
		echo_func: Optional[Callable[[str], None]] = None,
	) -> dict[str, Any]:
		"""BROWSER_TOOL_WATCH_TASK — Pollear tarea hasta completitud o timeout.

		Args:
		    task_id: ID de la tarea a monitorear.
		    timeout: Tiempo máximo en segundos antes de lanzar TimeoutError.
		    echo_func: Callback opcional para emitir progreso en tiempo real.

		Returns:
		    Dict con resultado de la tarea (``status``, ``output``, etc.).

		Raises:
		    asyncio.TimeoutError: Si la tarea no completa dentro del timeout.
		    ComposioError: Si la tarea termina en ``failed`` o ``stopped``.
		"""
		last_step = 0
		start = time.monotonic()

		while time.monotonic() - start < timeout:
			result = await asyncio.to_thread(
				self._execute_tool,
				'BROWSER_TOOL_WATCH_TASK',
				{'taskId': task_id, 'lastStepSeen': last_step},
				timeout,  # request_timeout = long-poll, same as overall task timeout
			)

			# Si el result no tiene status, algo raro pasó (probable parse error)
			if 'status' not in result:
				raw_data = result.get('_raw', str(result)[:500])
				logger.error('WatchTask result sin status. Raw: %s', raw_data)
				raise ComposioError(
					f'WatchTask sin status en respuesta. Datos crudos: {raw_data}',
				)

			status = result.get('status', 'started')
			current_step_val = result.get('current_step')
			if current_step_val is not None and current_step_val != last_step:
				goal = result.get('current_goal', '') or ''
				url = result.get('current_url', '') or ''
				if goal:
					logger.info('  🎯 Step %s: %s', current_step_val, goal[:300])
					if echo_func:
						echo_func(f'  🔍 Step {current_step_val}: {goal[:200]}')
					if url:
						logger.info('     ↳ %s', url[:200])
				else:
					logger.info('  ⏳ Step %s', current_step_val)
			last_step = result.get('current_step', last_step)

			if status == 'finished':
				logger.info(
					'Task %s finished (is_success=%s)',
					task_id,
					result.get('is_success'),
				)
				return result

			if status in ('failed', 'stopped'):
				output = result.get('output', result.get('data', ''))
				raise ComposioError(
					f'Task {task_id} ended with status={status}: {str(output)[:500]}',
				)

			await asyncio.sleep(COMPOSIO_POLL_INTERVAL)

		raise asyncio.TimeoutError(f'Task {task_id} timed out after {timeout}s')

	async def _stop_task(self, task_id: str) -> None:
		"""BROWSER_TOOL_STOP_TASK — Detener tarea y liberar sesión cloud.

		Siempre ejecutar en ``finally`` para evitar costos cloud por tareas
		colgadas.
		"""
		try:
			await asyncio.to_thread(
				self._execute_tool,
				'BROWSER_TOOL_STOP_TASK',
				{'taskId': task_id},
			)
			logger.info('Task %s stopped', task_id)
		except Exception as e:
			logger.warning('Error stopping task %s: %s', task_id, e)

	async def _get_session(self, session_id: str) -> dict[str, Any]:
		"""BROWSER_TOOL_GET_SESSION — Obtener URL en vivo de la sesión.

		Args:
		    session_id: ID de sesión (del campo ``sessionId`` en CreateTask response).

		Returns:
		    Dict con ``liveUrl`` para ver el browser en tiempo real.
		"""
		return await asyncio.to_thread(
			self._execute_tool,
			'BROWSER_TOOL_GET_SESSION',
			{'sessionId': session_id},
		)

	# ── Single client pipeline ──────────────────────────────────────────────

	async def _run_single(
		self,
		cliente: ClientConfig,
		tasks: Optional[list[BrowserTask]] = None,
		echo_func: Optional[Callable[[str], None]] = None,
	) -> DeudaOutput:
		"""Procesa un cliente con N tasks Composio en sesión compartida.

		Si tasks es None, usa [VencimientosDeudasTask()] por defecto (backward compatible).
		Todas las tasks comparten el mismo session_id de Composio.
		STOP_TASK se ejecuta UNA VEZ al final del finally.

		Args:
		    cliente: Configuración del cliente (``cuit``, ``nombre``, etc.).
		    tasks: Lista de BrowserTask a ejecutar secuencialmente.
		        Si None, usa VencimientosDeudasTask (comportamiento actual).
		    echo_func: Callback opcional para emitir progreso en tiempo real
		        (used by the SSE streaming endpoint).

		Returns:
		    ``DeudaOutput`` con resultado o error.
		"""
		if tasks is None:
			tasks = [
				VencimientosDeudasTask(
					cuit=self._login_cuit,
					clave=self._login_clave,
					cliente_cuit=cliente.cuit,
				)
			]

		session_id: Optional[str] = None
		last_task_id: Optional[str] = None
		results: list[TaskResult] = []

		try:
			for i, task in enumerate(tasks, 1):
				if echo_func:
					echo_func(f'  ─── [{i}/{len(tasks)}] {task.name} ───')
				logger.info('')
				logger.info('─── [Task %d/%d] %s ───', i, len(tasks), task.name)
				logger.info('')

				# ── Preparar parámetros ──────────────────────────────────
				# Reemplazar placeholders uno a uno con replace()
				# para no romper templates que tienen JSON con { y }
				instruction = task.template
				if task.template_params:
					for key, value in task.template_params.items():
						instruction = instruction.replace(f'{{{key}}}', str(value))
				secrets = task.secrets if task.needs_auth else None
				start_url = task.start_url if task.needs_auth else None
				reuse_session = session_id if not task.needs_auth else None

				logger.info('▶ Ejecutando %s para %s ...', task.name, cliente.cuit)
				if echo_func:
					echo_func(f'  ▶ {task.name}: {cliente.cuit} ...')

				# ── Determinar política de reintento ──────────────────────
				max_retries = 3 if (task.name == 'facilidades' or task.timeout > 300) else 1
				retry_delay = 30
				task_failed = False

				for attempt in range(max_retries):
					try:
						if attempt > 0:
							if echo_func:
								echo_func(f'  🔄 Reintento {attempt + 1}/{max_retries} tras error transitorio...')
							logger.warning('Reintentando %s (intento %d/%d)', task.name, attempt + 1, max_retries)
							await asyncio.sleep(retry_delay)

						# ── CREATE_TASK ───────────────────────────────────────────
						create_result = await self._create_task(
							instruction=instruction,
							secrets=secrets,
							start_url=start_url,
							session_id=reuse_session,
						)
						task_id = create_result.get('taskId') or create_result.get('id') or create_result.get('watch_task_id')
						last_task_id = task_id

						# Session ID de ESTA task (cada task puede tener su propia sesión)
						current_session_id = create_result.get('sessionId') or create_result.get('browser_session_id') or ''

						# Almacenar solo para reuso entre tasks (cuando needs_auth=False)
						if session_id is None:
							session_id = current_session_id

						if not task_id:
							raise ComposioError(f'No taskId en CreateTask para {task.name}')

						logger.info('Task %s creada: taskId=%s, sessionId=%s', task.name, task_id, current_session_id or 'N/A')

						# ── Live URL — siempre visible cuando se lanza la task ───
						if current_session_id and task.needs_auth:
							try:
								session_info = await self._get_session(current_session_id)
								live_url = session_info.get('liveUrl', '')
								if live_url:
									logger.info('  🔗 Live: %s', live_url)
									if echo_func:
										echo_func(f'  🔗 Live: {live_url}')
							except Exception as e:
								logger.debug('No se pudo obtener URL de sesión para %s: %s', task.name, e)

						# ── WATCH_TASK con timeout individual ───────────────────
						task_start = time.monotonic()
						output = await self._watch_task(task_id, timeout=task.timeout, echo_func=echo_func)
						task_duration = time.monotonic() - task_start
						raw = str(output.get('output', output.get('data', '')))
						total_steps = output.get('current_step', 0)

						logger.info('Output crudo de %s (primeros 500): %s', task.name, raw[:500])

						# ── Parsear y detectar ARCA error ────────────────────────
						parsed_data = task.parse_output(raw)
						arca_error = _parse_arca_error(raw)

						result = TaskResult(
							task_name=task.name,
							success=arca_error is None,
							raw_output=raw,
							parsed_data=parsed_data,
							arca_error=arca_error,
							task_id=task_id,
						)

						if not parsed_data and raw and not arca_error:
							logger.warning('Task %s: output no parseable', task.name)

						results.append(result)

						if arca_error or not result.success:
							task_failed = True
							msg = f'✘ Task {task.name} falló para {cliente.cuit}: {arca_error or result.error}'
							logger.error(msg)
							if echo_func:
								echo_func(f'  ❌ {msg}')
							break
						else:
							data_desc = (
								', '.join(f'{k}={len(v)}' for k, v in parsed_data.items() if isinstance(v, list))
								if parsed_data
								else '✓'
							)
							task_msg = f'  ✓ {task.name} completada — ⏱️ {task_duration:.1f}s | 👣 {total_steps} steps'
							logger.info(
								'✓ Task %s completada — ⏱️ %.1fs | 👣 %s steps | Plan: Estudio Contable | 💰 $0 (%s)',
								task.name,
								task_duration,
								total_steps,
								data_desc or 'OK',
							)
							if echo_func:
								echo_func(task_msg)

						break  # exit retry loop on success

					except (ComposioError, asyncio.TimeoutError) as e:
						error_str = str(e).lower()
						is_transient = any(
							p in error_str
							for p in [
								'502',
								'bad gateway',
								'err_tunnel',
								'unreachable',
								'503',
								'service unavailable',
								'gateway timeout',
							]
						)
						if is_transient and attempt < max_retries - 1:
							logger.warning(
								'Error transitorio en %s: %s. Reintentando...',
								task.name,
								e,
							)
							continue
						raise

				if task_failed:
					break

			# ── Post-loop: resumen y return ─────────────────────────────────
			logger.info('')
			total_ok = sum(1 for r in results if r.success)
			summary_msg = f'  Composio: {total_ok}/{len(tasks)} tasks completadas'
			logger.info('─── Resumen: %d/%d tasks exitosas ───', total_ok, len(results))
			if echo_func:
				echo_func(summary_msg)
			return self._consolidate(cliente, results)

		except asyncio.TimeoutError:
			task_name = tasks[len(results)].name if len(results) < len(tasks) else 'desconocida'
			logger.error(
				'✘ Timeout — %s excedió el límite (%ds)',
				task_name,
				tasks[len(results)].timeout if len(results) < len(tasks) else '?',
			)
			# Consolidar datos parciales de tasks exitosas antes del timeout
			if results:
				output = self._consolidate(cliente, results)
				output.error = f'Timeout — {task_name} excedió el límite de espera'
				return output
			return DeudaOutput(
				cuit=cliente.cuit,
				extraido_el=datetime.now(),
				error=f'Timeout — {task_name} excedió el límite de espera',
			)
		except ComposioError as e:
			logger.error('Error Composio para %s: %s', cliente.cuit, e)
			if results:
				output = self._consolidate(cliente, results)
				output.error = str(e)
				return output
			return DeudaOutput(
				cuit=cliente.cuit,
				extraido_el=datetime.now(),
				error=str(e),
			)
		except Exception as e:
			logger.error('Error inesperado para %s: %s\n%s', cliente.cuit, e, traceback.format_exc())
			if results:
				output = self._consolidate(cliente, results)
				output.error = f'Error inesperado: {e}'
				return output
			return DeudaOutput(
				cuit=cliente.cuit,
				extraido_el=datetime.now(),
				error=f'Error inesperado: {e}',
			)
		finally:
			if last_task_id:
				await self._stop_task(last_task_id)

	@staticmethod
	def _parse_facilidad(item: dict) -> FacilidadPlan:
		"""Convierte un dict crudo de plan de pago en FacilidadPlan."""

		def _parse_date(val: Any) -> Optional[date]:
			if isinstance(val, str) and len(val) >= 10:
				try:
					return datetime.strptime(val[:10], '%Y-%m-%d').date()
				except ValueError:
					pass
			return None

		# próximo vencimiento
		prox_raw = item.get('proximo_vencimiento')
		proximo_vencimiento = None
		if prox_raw and isinstance(prox_raw, dict):
			proximo_vencimiento = FacilidadProximoVencimiento(
				nro_cuota=int(prox_raw.get('nro_cuota', 0)),
				fecha=_parse_date(prox_raw.get('fecha')) or date.today(),
				total=float(prox_raw['total']) if prox_raw.get('total') is not None else 0.0,
			)

		# cuotas
		cuotas = []
		for c in item.get('cuotas', []):
			cuotas.append(
				FacilidadPlanCuota(
					numero=int(c.get('numero', 0)),
					capital=float(c['capital']) if c.get('capital') is not None else 0.0,
					interes_financiero=float(c['interes_financiero']) if c.get('interes_financiero') is not None else 0.0,
					interes_resarcitorio=float(c['interes_resarcitorio']) if c.get('interes_resarcitorio') is not None else 0.0,
					total=float(c['total']) if c.get('total') is not None else 0.0,
					vencimiento=_parse_date(c.get('vencimiento')),
					fecha_pago=_parse_date(c.get('fecha_pago')),
					estado=str(c.get('estado', '')),
				)
			)

		# datos del plan
		dp_raw = item.get('datos_plan')
		datos_plan = None
		if dp_raw and isinstance(dp_raw, dict):
			datos_plan = FacilidadDatosPlan(
				fecha_consolidacion=_parse_date(dp_raw.get('fecha_consolidacion')),
				cbu=str(dp_raw.get('cbu', '')),
				titular_cbu=str(dp_raw.get('titular_cbu', '')),
			)

		return FacilidadPlan(
			plan=str(item.get('plan', '')),
			nro_plan=str(item.get('nro_plan', '')),
			estado=str(item.get('estado', '')),
			fecha_presentacion=_parse_date(item.get('fecha_presentacion')),
			cantidad_cuotas=int(item.get('cantidad_cuotas', 0)),
			cuotas_pagas=int(item.get('cuotas_pagas', 0)),
			cuotas_impagas=int(item.get('cuotas_impagas', 0)),
			saldo=float(item['saldo']) if item.get('saldo') is not None else 0.0,
			concepto=str(item.get('concepto', '')),
			proximo_vencimiento=proximo_vencimiento,
			cuotas=cuotas,
			datos_plan=datos_plan,
			observacion=str(item.get('observacion', '')),
		)

	@staticmethod
	def _parse_iibb(data: dict) -> list[RegistroIIBBJurisdiccion]:
		"""Convierte un dict crudo de IIBB jurisdicciones en lista de RegistroIIBBJurisdiccion."""
		iibb_list: list[RegistroIIBBJurisdiccion] = []
		for ij in data.get('iibb_jurisdicciones', []):
			iibb_list.append(
				RegistroIIBBJurisdiccion(
					provincia=str(ij.get('provincia', '')),
					inscripcion=str(ij.get('inscripcion', '')),
					estado=str(ij.get('estado', '')),
					fecha_alta=(
						datetime.strptime(ij['fecha_alta'], '%Y-%m-%d').date()
						if ij.get('fecha_alta') and isinstance(ij.get('fecha_alta'), str)
						else None
					),
					fecha_baja=(
						datetime.strptime(ij['fecha_baja'], '%Y-%m-%d').date()
						if ij.get('fecha_baja') and isinstance(ij.get('fecha_baja'), str)
						else None
					),
				)
			)
		return iibb_list

	@staticmethod
	def _parse_cuota_vencida(item: dict) -> IIBBCuotaVencida:
		"""Convierte un dict crudo de cuota vencida IIBB en IIBBCuotaVencida."""

		def _parse_date(val: Any) -> Optional[date]:
			if isinstance(val, str) and len(val) >= 10:
				try:
					return datetime.strptime(val[:10], '%Y-%m-%d').date()
				except ValueError:
					pass
			return None

		return IIBBCuotaVencida(
			periodo=str(item.get('periodo', '')),
			impuesto=str(item.get('impuesto', '')),
			vencimiento=_parse_date(item.get('vencimiento')),
			saldo=float(item['saldo']) if item.get('saldo') is not None else None,
			recargo=float(item['recargo']) if item.get('recargo') is not None else None,
			estado=str(item.get('estado', '')),
			apto_plan=bool(item.get('apto_plan', False)),
		)

	@staticmethod
	def _parse_registro(data: dict) -> RegistroOutput:
		"""Convierte un dict crudo de registro tributario en RegistroOutput."""

		domicilios = []
		for d in data.get('domicilios', []):
			domicilios.append(
				RegistroDomicilio(
					tipo=str(d.get('tipo', '')),
					provincia=str(d.get('provincia', '')),
					localidad=str(d.get('localidad', '')),
					direccion=str(d.get('direccion', '')),
					codigo_postal=str(d.get('codigo_postal', '')),
				)
			)

		actividades = []
		for a in data.get('actividades', []):
			actividades.append(
				RegistroActividad(
					actividad=str(a.get('actividad', '')),
					codigo=str(a.get('codigo', '')),
					estado=str(a.get('estado', '')),
				)
			)

		impuestos = []
		for imp in data.get('impuestos', []):
			impuestos.append(
				RegistroImpuesto(
					impuesto=str(imp.get('impuesto', '')),
					categoria=str(imp.get('categoria', '')) if imp.get('categoria') else None,
					estado=str(imp.get('estado', '')),
				)
			)

		puntos_de_venta = []
		for pv in data.get('puntos_de_venta', []):
			puntos_de_venta.append(
				RegistroPuntoVenta(
					punto=str(pv.get('punto', '')),
					tipo=str(pv.get('tipo', '')),
					estado=str(pv.get('estado', '')),
				)
			)

		iibb_jurisdicciones = []
		for ij in data.get('iibb_jurisdicciones', []):
			iibb_jurisdicciones.append(
				RegistroIIBBJurisdiccion(
					provincia=str(ij.get('provincia', '')),
					inscripcion=str(ij.get('inscripcion', '')),
					estado=str(ij.get('estado', '')),
					fecha_alta=(
						datetime.strptime(ij['fecha_alta'], '%Y-%m-%d').date()
						if ij.get('fecha_alta') and isinstance(ij.get('fecha_alta'), str)
						else None
					),
					fecha_baja=(
						datetime.strptime(ij['fecha_baja'], '%Y-%m-%d').date()
						if ij.get('fecha_baja') and isinstance(ij.get('fecha_baja'), str)
						else None
					),
				)
			)

		return RegistroOutput(
			domicilios=domicilios,
			jurisdiccion=str(data.get('jurisdiccion')) if data.get('jurisdiccion') else None,
			actividades=actividades,
			impuestos=impuestos,
			puntos_de_venta=puntos_de_venta,
			iibb_jurisdicciones=iibb_jurisdicciones,
		)

	def _consolidate(self, cliente: ClientConfig, results: list[TaskResult]) -> DeudaOutput:
		"""Consolida lista de TaskResults en un solo DeudaOutput.

		Vencimientos y deudas se buscan en TODAS las tasks exitosas (primera
		que contenga esos datos). Facilidades y registro también se iteran
		todas. Saldos legacy, deuda_actual y plan_pagos se toman de la
		última task exitosa con parsed_data.

		Si todas fallaron, retorna DeudaOutput con error.
		"""
		if not results:
			return DeudaOutput(
				cuit=cliente.cuit,
				extraido_el=datetime.now(),
				error='No se ejecutaron tasks',
			)

		# Buscar la última task exitosa con parsed_data
		last_ok = None
		for r in reversed(results):
			if r.success and r.parsed_data:
				last_ok = r
				break

		if last_ok is None:
			last_result = results[-1]
			return DeudaOutput(
				cuit=cliente.cuit,
				extraido_el=datetime.now(),
				error=last_result.arca_error or last_result.error or 'Error desconocido',
			)

		data = last_ok.parsed_data

		# ── Vencimientos y Deudas: buscar en TODAS las tasks (no solo last_ok)
		#    porque si corren VencimientosDeudasTask + FacilidadesTask + RegistroTask,
		#    la última task exitosa es RegistroTask que no tiene vencimientos/deudas.
		vencimientos_raw: list[dict] = []
		for r in results:
			if r.success and r.parsed_data:
				v = r.parsed_data.get('vencimientos', [])
				if v:
					vencimientos_raw = v
					break

		deudas_raw: list[dict] = []
		for r in results:
			if r.success and r.parsed_data:
				d = r.parsed_data.get('deudas', [])
				if d:
					deudas_raw = d
					break

		# Construir VencimientoDeuda[] desde vencimientos_raw
		vencimientos = []
		for item in vencimientos_raw:
			try:
				fv = item.get('fecha_vencimiento')
				vencimientos.append(
					VencimientoDeuda(
						impuesto=item.get('impuesto', ''),
						concepto=item.get('concepto', ''),
						subconcepto=item.get('subconcepto', ''),
						periodo=int(item.get('periodo', 0)),
						anticuota=int(item['anticuota']) if item.get('anticuota') is not None else 0,
						fecha_vencimiento=(
							datetime.strptime(fv, '%Y-%m-%d').date() if fv and isinstance(fv, str) and len(fv) >= 10 else None
						),
						detalle=item.get('detalle', ''),
					)
				)
			except (ValueError, TypeError) as e:
				logger.warning('Item de vencimiento inválido omitido: %s — %s', item, e)

		# Construir DeudaDetail[] desde deudas_raw (ya resuelto arriba)
		deudas = []
		for item in deudas_raw:
			try:
				fv = item.get('vencimiento')
				deudas.append(
					DeudaDetail(
						impuesto=item.get('impuesto', ''),
						concepto=item.get('concepto', ''),
						subconcepto=item.get('subconcepto', ''),
						periodo=int(item.get('periodo', 0)),
						anticuota=int(item['anticuota']) if item.get('anticuota') is not None else 0,
						vencimiento=(
							datetime.strptime(fv, '%Y-%m-%d').date() if fv and isinstance(fv, str) and len(fv) >= 10 else None
						),
						saldo=float(item['saldo']) if item.get('saldo') is not None else None,
						interes_resarcitorio=float(item['interes_resarcitorio'])
						if item.get('interes_resarcitorio') is not None
						else 0.0,
						interes_punitorio=float(item['interes_punitorio']) if item.get('interes_punitorio') is not None else 0.0,
					)
				)
			except (ValueError, TypeError) as e:
				logger.warning('Item de deuda inválido omitido: %s — %s', item, e)

		# Legacy saldos
		saldos_raw = data.get('saldos', [])
		saldos = []
		for item in saldos_raw:
			try:
				saldos.append(
					DeudaItem(
						concepto=item.get('concepto', ''),
						importe=float(item.get('importe', 0)),
						vencimiento=item.get('vencimiento'),
					)
				)
			except (ValueError, TypeError) as e:
				logger.warning('Item de saldo inválido omitido: %s — %s', item, e)

		deuda_actual = data.get('deuda_actual')
		plan_pagos = data.get('plan_pagos')

		# ── Planes de pago (desde cualquier task exitosa) ────────────────
		facilidades: list[FacilidadPlan] = []
		for r in results:
			if not r.success or not r.parsed_data:
				continue
			planes_raw = r.parsed_data.get('planes', [])
			if not planes_raw:
				continue
			for item in planes_raw:
				try:
					facilidades.append(self._parse_facilidad(item))
				except (ValueError, TypeError) as e:
					logger.warning('Plan inválido omitido: %s — %s', item, e)

		# ── Registro tributario (desde cualquier task exitosa) ───────────
		registro: Optional[RegistroOutput] = None
		for r in results:
			if not r.success or not r.parsed_data:
				continue
			if any(k in r.parsed_data for k in ('domicilios', 'actividades', 'impuestos', 'puntos_de_venta')):
				registro = self._parse_registro(r.parsed_data)
				break

		# ── IIBB jurisdicciones (desde IIBBTask, merge con registro) ──
		for r in results:
			if not r.success or not r.parsed_data:
				continue
			iibb_raw = r.parsed_data.get('iibb_jurisdicciones')
			if iibb_raw:
				iibb_list = self._parse_iibb(r.parsed_data)
				if registro is None:
					registro = RegistroOutput(iibb_jurisdicciones=iibb_list)
				else:
					registro.iibb_jurisdicciones = iibb_list
				break

		# ── IIBB cuotas vencidas ──
		for r in results:
			if not r.success or not r.parsed_data:
				continue
			cuotas_raw = r.parsed_data.get('cuotas_vencidas')
			if cuotas_raw:
				cuotas_list = [self._parse_cuota_vencida(c) for c in cuotas_raw]
				if registro is None:
					registro = RegistroOutput(iibb_cuotas_vencidas=cuotas_list)
				else:
					registro.iibb_cuotas_vencidas = cuotas_list
				break

		return DeudaOutput(
			cuit=cliente.cuit,
			extraido_el=datetime.now(),
			vencimientos=vencimientos,
			deudas=deudas,
			deuda_actual=float(deuda_actual) if deuda_actual is not None else None,
			saldos=saldos,
			plan_pagos=plan_pagos,
			facilidades=facilidades,
			registro=registro,
			error=None,
		)

	# ── Public API ──────────────────────────────────────────────────────────

	async def run_all(self, clientes: list[ClientConfig]) -> list[DeudaOutput]:
		"""Procesa cada cliente en paralelo con sesión Composio independiente.

		Usa ``asyncio.gather`` con ``return_exceptions=True`` para que una
		falla individual no detenga el procesamiento del resto.

		Args:
		    clientes: Lista de ``ClientConfig``.

		Returns:
		    Lista de ``DeudaOutput`` (1:1 con clientes de entrada).
		    Cada elemento tiene ``error=None`` si fue exitoso, o ``error=str``
		    si falló. STOP_TASK se ejecuta en ``finally`` por sesión.
		"""
		if not clientes:
			return []

		logger.info('Processing %d clients in parallel', len(clientes))

		tasks = [self._run_single(c) for c in clientes]
		results = await asyncio.gather(*tasks, return_exceptions=True)

		outputs: list[DeudaOutput] = []
		for i, result in enumerate(results):
			if isinstance(result, Exception):
				logger.error(
					'Unhandled exception for %s: %s',
					clientes[i].cuit,
					result,
				)
				outputs.append(
					DeudaOutput(
						cuit=clientes[i].cuit,
						extraido_el=datetime.now(),
						error=f'Excepción no manejada: {result}',
					)
				)
			else:
				outputs.append(result)

		return outputs

	def run_single(
		self,
		cliente: ClientConfig,
		tasks: Optional[list[BrowserTask]] = None,
		echo_func: Optional[Callable[[str], None]] = None,
	) -> DeudaOutput:
		"""Sync wrapper para _run_single. Crea su propio event loop.

		Args:
		    cliente: Configuración del cliente (``cuit``, ``nombre``, etc.).
		    tasks: Lista de BrowserTask. Si None, usa [VencimientosDeudasTask()].
		    echo_func: Callback opcional para emitir progreso en tiempo real.

		Returns:
		    ``DeudaOutput`` con resultado o error. Nunca propaga excepción.
		"""
		try:
			return asyncio.run(self._run_single(cliente, tasks=tasks, echo_func=echo_func))
		except Exception as e:
			logger.error('run_single error for %s: %s', cliente.cuit, e)
			return DeudaOutput(
				cuit=cliente.cuit,
				extraido_el=datetime.now(),
				error=str(e),
			)

	async def close(self) -> None:
		"""Cleanup — no resources to release since STOP_TASK runs per session."""
		logger.info('ComposioBrowser closed')
