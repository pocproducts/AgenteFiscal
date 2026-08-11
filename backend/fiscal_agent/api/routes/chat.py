"""POST /v1/chat/message — natural-language fiscal query endpoint.

Recibe un mensaje en lenguaje natural, detecta el CUIT + intención,
despacha al handler correspondiente (sincrónico, en thread pool),
y devuelve una respuesta formateada en español.

Streaming
---------
``POST /v1/chat/message/stream`` devuelve un SSE (Server-Sent Events)
con eventos ``progress`` y ``complete``, replicando el output de la CLI
en tiempo real.

Contrato SSE (Issue 5)
----------------------
Eventos emitidos por ``/v1/chat/message/stream``:

    event: conversation_start
    data: {"conversation_id": "uuid"}

    event: progress                          # se repite N veces
    data: {"message": "  Consultando Padrón A5 ..."}

    event: complete
    data: {
      "reply": "**Reporte fiscal...**",
      "data": {"cliente": "...", ...} | null,
      "conversation_id": "uuid",
      "pipeline_steps": ["msg1", "msg2", ...] | null  # desde junio 2026
    }

Eventos emitidos por ``/v1/chat/wizard``:

    event: wizard_state
    data: {
      "state": "processing",
      "reply": "Generando reporte fiscal...",
      "conversation_id": "uuid",
      "cliente": {"nombre": "...", "cuit": "..."} | null
    }

    event: progress                          # se repite N veces
    data: {"message": "  Consultando Padrón A5 ..."}

    event: complete
    data: {
      "reply": "**Reporte fiscal...**",
      "data": {"cliente": "...", ...} | null,
      "conversation_id": "uuid",
      "pdf_url": "/v1/chat/reports/file.pdf" | null,
      "pipeline_steps": ["msg1", "msg2", ...] | null  # desde junio 2026
    }

Notas:
- ``progress`` events son mensajes de texto plano del pipeline (mismos que la CLI).
- ``complete`` event incluye ``pipeline_steps`` (array de strings) desde junio 2026 para persistencia.
- El frontend reconstruye objetos ``{message, status}`` desde las strings raw.
- ``event: complete`` es siempre el último evento. El stream se cierra después.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from fiscal_agent.api.store import RedisStore
from fiscal_agent.domain.intent_router import Intent, detect
from fiscal_agent.domain.response_builder import format_reporte_response, format_taxpayer_response

router = APIRouter()

# ── Request / Response models ───────────────────────────────────────────────


class WizardTasks(BaseModel):
	"""Tasks seleccionadas por el usuario en el wizard."""

	model_config = ConfigDict(extra='forbid')

	deuda: bool = Field(default=True, description='Extraer deuda real')
	facilidades: bool = Field(default=True, description='Extraer planes de pago')
	registro: bool = Field(default=True, description='Extraer registro tributario')
	iibb: bool = Field(default=False, description='Extraer jurisdicciones IIBB detalladas')


class WizardRequest(BaseModel):
	"""Solicitud al wizard interactivo multi-turno."""

	model_config = ConfigDict(extra='forbid')

	cuit: str | None = Field(default=None, description='CUIT del contribuyente (11 dígitos)')
	tasks: WizardTasks | None = Field(default=None, description='Tareas seleccionadas (null → solo descubrir cliente)')
	send_email: bool = Field(default=False, description='Enviar reporte por email al cliente')
	conversation_id: str | None = Field(default=None, description='Identificador de conversación (se genera si se omite)')


class WizardResponse(BaseModel):
	"""Respuesta del wizard (estados no-streaming)."""

	conversation_id: str = Field(description='Identificador de conversación')
	state: str = Field(description='Estado actual: awaiting_cuit | awaiting_tasks | error')
	reply: str = Field(description='Respuesta en español para el usuario')
	cliente: dict | None = Field(default=None, description='Datos del cliente descubierto (solo en awaiting_tasks)')


class ChatRequest(BaseModel):
	"""Natural-language chat message from the user."""

	model_config = ConfigDict(extra='forbid')

	message: str = Field(description='Natural language query from the user')
	conversation_id: str | None = Field(
		default=None,
		description='Opaque conversation identifier (generated if omitted)',
	)
	history: list[dict] | None = Field(
		default=None,
		description='Previous messages: [{"role": "user"|"assistant", "content": str}]',
	)


class ChatResponse(BaseModel):
	"""Structured chat response with natural-language reply and metadata."""

	model_config = ConfigDict(extra='forbid')

	conversation_id: str = Field(description='Conversation identifier')
	reply: str = Field(description='Human-readable response in Spanish')
	actions_taken: list[str] = Field(
		default_factory=list,
		description='Internal actions performed (e.g. ["consultar_cuit"])',
	)
	data: dict[str, Any] | None = Field(
		default=None,
		description='Structured results from backend queries',
	)


# ── Sync handlers (run in thread pool to avoid blocking the event loop) ──────


def _handle_taxpayer(cuit: str) -> dict[str, Any] | None:
	"""Consult taxpayer data via ARCA WS API (sync)."""
	from fiscal_agent.api.deps import REPRESENTANTE_CUIT, get_ta
	from fiscal_agent.adapters.arca_ws import consultar_cuit

	token, sign = get_ta()
	if not token or not sign:
		return None

	try:
		result = consultar_cuit(cuit, token, sign, REPRESENTANTE_CUIT)
		output = result.to_output()
		if output.errorConstancia:
			return {'error': '; '.join(output.errorConstancia.error)}
		output_dict = result.to_dict()
		return {
			'nombre': output_dict.get('nombre') or (output.datosGenerales.razonSocial if output.datosGenerales else ''),
			'tipo': output_dict.get('tipo', ''),
			'tipo_persona': output_dict.get('tipo_persona', ''),
		}
	except Exception as exc:
		return {'error': str(exc)}


def _handle_reporte(cuit: str) -> dict[str, Any] | None:
	"""Generate a complete fiscal report (sync — delegates to ``_procesar_cliente_pipeline``).

	Mirrors the CLI ``report`` flow but returns structured data instead of
	printing to console.  Runs the same ``_procesar_cliente_pipeline()``
	shared by the CLI so behaviour is identical.
	"""
	from datetime import datetime

	from fiscal_agent.api.deps import REPRESENTANTE_CUIT, get_engine, get_memory, get_pdf_gen, get_ta
	from fiscal_agent.cli import _procesar_cliente_pipeline
	from fiscal_agent.config import get_settings
	from fiscal_agent.domain.models import ClientConfig
	from fiscal_agent.pipeline.service import PipelineService, _completar_cliente_desde_padron

	token, sign = get_ta()
	if not token or not sign:
		return None

	cliente = ClientConfig(cuit=cuit)
	try:
		cliente = _completar_cliente_desde_padron(cliente, token, sign, REPRESENTANTE_CUIT)
	except Exception:
		pass

	now = datetime.utcnow()
	mes, anio = now.month, now.year

	engine = get_engine()
	pdf_gen = get_pdf_gen()
	memory = get_memory()

	creds = get_settings().credentials
	browser = None
	with_browser = bool(creds.composio_api_key and creds.clave_fiscal)

	if with_browser:
		from fiscal_agent.adapters.browser import ComposioBrowser

		browser = ComposioBrowser(
			composio_api_key=creds.composio_api_key,
			estudio_cuit=REPRESENTANTE_CUIT,
			estudio_clave=creds.clave_fiscal,
		)

	try:
		resultado = _procesar_cliente_pipeline(
			cliente=cliente,
			token=token,
			sign=sign,
			engine=engine,
			pdf_gen=pdf_gen,
			mes=mes,
			anio=anio,
			browser=browser,
			with_deuda=with_browser,
			with_facilidades=with_browser,
			with_registro=with_browser,
			send_email=False,
			config=None,
			memory_client=memory,
			echo_func=echo_func,
		)
		return resultado
	except Exception as exc:
		return {'error': str(exc)}


# ── Streaming handler (accepts echo_func for progress) ───────────────────


def _handle_reporte_with_echo(
	cuit: str,
	echo_func: Callable[[str], None],
) -> dict[str, Any] | None:
	"""Same as ``_handle_reporte`` but passes ``echo_func`` to the pipeline.

	The ``echo_func`` is called at each pipeline step with the same messages
	that the CLI prints via ``typer.echo``.  Used by the SSE endpoint to
	stream progress in real time.
	"""
	from datetime import datetime

	from fiscal_agent.api.deps import REPRESENTANTE_CUIT, get_engine, get_memory, get_pdf_gen, get_ta
	from fiscal_agent.cli import _procesar_cliente_pipeline
	from fiscal_agent.config import get_settings
	from fiscal_agent.domain.models import ClientConfig
	from fiscal_agent.pipeline.service import PipelineService, _completar_cliente_desde_padron

	token, sign = get_ta()
	if not token or not sign:
		return None

	cliente = ClientConfig(cuit=cuit)
	try:
		cliente = _completar_cliente_desde_padron(cliente, token, sign, REPRESENTANTE_CUIT)
	except Exception:
		pass

	now = datetime.utcnow()
	mes, anio = now.month, now.year

	engine = get_engine()
	pdf_gen = get_pdf_gen()
	memory = get_memory()

	creds = get_settings().credentials
	browser = None
	with_browser = bool(creds.composio_api_key and creds.clave_fiscal)

	if with_browser:
		from fiscal_agent.adapters.browser import ComposioBrowser

		browser = ComposioBrowser(
			composio_api_key=creds.composio_api_key,
			estudio_cuit=REPRESENTANTE_CUIT,
			estudio_clave=creds.clave_fiscal,
		)

	try:
		resultado = _procesar_cliente_pipeline(
			cliente=cliente,
			token=token,
			sign=sign,
			engine=engine,
			pdf_gen=pdf_gen,
			mes=mes,
			anio=anio,
			browser=browser,
			with_deuda=with_browser,
			with_facilidades=with_browser,
			with_registro=with_browser,
			send_email=False,
			config=None,
			memory_client=memory,
			echo_func=echo_func,
		)
		return resultado
	except Exception as exc:
		return {'error': str(exc)}


# ── Wizard: pipeline handler (dynamic flags) ────────────────────────────


def _handle_wizard_pipeline(
	cuit: str,
	tasks: WizardTasks,
	echo_func: Callable[[str], None],
	send_email: bool = False,
) -> dict[str, Any] | None:
	"""Run pipeline with dynamic task flags from the wizard request.

	Same as ``_handle_reporte_with_echo`` but uses the ``tasks`` parameter
	to set ``with_deuda``, ``with_facilidades``, ``with_registro``,
	``with_iibb`` dynamically instead of hardcoding them to ``with_browser``.
	"""
	from datetime import datetime

	from fiscal_agent.api.deps import REPRESENTANTE_CUIT, get_engine, get_memory, get_pdf_gen, get_ta
	from fiscal_agent.cli import _procesar_cliente_pipeline
	from fiscal_agent.config import get_settings
	from fiscal_agent.domain.models import ClientConfig
	from fiscal_agent.pipeline.service import _completar_cliente_desde_padron

	token, sign = get_ta()
	if not token or not sign:
		return None

	cliente = ClientConfig(cuit=cuit)
	try:
		cliente = _completar_cliente_desde_padron(cliente, token, sign, REPRESENTANTE_CUIT)
	except Exception:
		pass

	now = datetime.utcnow()
	mes, anio = now.month, now.year

	engine = get_engine()
	pdf_gen = get_pdf_gen()
	memory = get_memory()

	creds = get_settings().credentials
	uses_browser = tasks.deuda or tasks.facilidades or tasks.registro or tasks.iibb
	browser = None

	if uses_browser:
		if not (creds.composio_api_key and creds.clave_fiscal):
			echo_func('  ⚠️  Credenciales de browser no configuradas — algunas tareas no estarán disponibles')
		else:
			from fiscal_agent.adapters.browser import ComposioBrowser

			browser = ComposioBrowser(
				composio_api_key=creds.composio_api_key,
				estudio_cuit=REPRESENTANTE_CUIT,
				estudio_clave=creds.clave_fiscal,
			)

	try:
		resultado = _procesar_cliente_pipeline(
			cliente=cliente,
			token=token,
			sign=sign,
			engine=engine,
			pdf_gen=pdf_gen,
			mes=mes,
			anio=anio,
			browser=browser,
			with_deuda=tasks.deuda,
			with_facilidades=tasks.facilidades,
			with_registro=tasks.registro,
			with_iibb=tasks.iibb,
			send_email=send_email,
			config=None,
			memory_client=memory,
			echo_func=echo_func,
		)
		return resultado
	except Exception as exc:
		return {'error': str(exc)}


# ── Wizard endpoint ─────────────────────────────────────────────────────


def _descubrir_cliente_desde_padron(cuit: str) -> dict | None:
	"""Discover client info from padrón A5. Returns dict or None."""
	from fiscal_agent.api.deps import REPRESENTANTE_CUIT, get_ta
	from fiscal_agent.domain.models import ClientConfig
	from fiscal_agent.pipeline.service import _completar_cliente_desde_padron

	token, sign = get_ta()
	if not token or not sign:
		return None

	try:
		cliente = ClientConfig(cuit=cuit)
		cliente = _completar_cliente_desde_padron(cliente, token, sign, REPRESENTANTE_CUIT)
		return {'nombre': cliente.nombre or cuit, 'cuit': cliente.cuit, 'tipo': cliente.tipo.value if cliente.tipo else None}
	except Exception:
		return None


@router.post(
	'/v1/chat/wizard',
	summary='Wizard interactivo multi-turno (CUIT → tareas → pipeline)',
)
async def chat_wizard(
	request: WizardRequest,
	fastapi_request: Request,
):
	"""Endpoint multi-turno del wizard de onboarding.

	Comportamiento según el estado:

	1. **Sin CUIT** → retorna ``awaiting_cuit`` (pide CUIT)
	2. **Solo CUIT** (sin tasks) → descubre cliente desde Padrón A5,
	   retorna ``awaiting_tasks`` con datos del cliente
	3. **CUIT + tasks** → ejecuta pipeline con flags dinámicos,
	   streamea progreso via SSE (event: progress → event: complete)

	Estados no-streaming (1 y 2) retornan JSON.
	Estado processing (3) retorna ``text/event-stream``.
	"""
	import json

	from fiscal_agent.api.deps import REPRESENTANTE_CUIT, get_ta

	cuit = request.cuit
	tasks = request.tasks
	conversation_id = request.conversation_id or str(uuid.uuid4())

	# ── Helper: validar CUIT ───────────────────────────────────────────
	def _cuit_valido(raw: str) -> bool:
		import re

		return bool(re.fullmatch(r'\d{11}', raw.strip()))

	# ── Helper: buscar cliente en YAML ─────────────────────────────────
	def _buscar_en_yaml(cuit_raw: str) -> dict | None:
		from pathlib import Path
		import yaml
		from fiscal_agent.domain.models import AppConfig

		config_path = Path('clients.yaml')
		if not config_path.exists():
			return None
		try:
			raw = yaml.safe_load(config_path.read_text())
			config = AppConfig(**raw)
			cuit_limpio = cuit_raw.replace('-', '')
			for c in config.clientes:
				if c.cuit.replace('-', '') == cuit_limpio:
					return {'nombre': c.nombre or c.cuit, 'cuit': c.cuit, 'tipo': c.tipo.value if c.tipo else None}
		except Exception:
			pass
		return None

	# ── Case 1: No CUIT → awaiting_cuit ───────────────────────────────
	if not cuit:
		return WizardResponse(
			conversation_id=conversation_id,
			state='awaiting_cuit',
			reply='Ingresá el CUIT del contribuyente para comenzar.',
		)

	# ── Validate CUIT format ───────────────────────────────────────────
	if not _cuit_valido(cuit):
		return WizardResponse(
			conversation_id=conversation_id,
			state='awaiting_cuit',
			reply='El CUIT debe tener exactamente 11 dígitos. Verificá el número e intentá de nuevo.',
		)

	# ── Find or discover client ────────────────────────────────────────
	cliente_info = _buscar_en_yaml(cuit)
	if cliente_info is None:
		cliente_info = _descubrir_cliente_desde_padron(cuit)

	if cliente_info is None:
		# Not found anywhere → error
		from fiscal_agent.adapters.arca_ws import get_ta, get_ta_error

		token, sign = get_ta()
		if not token or not sign:
			return WizardResponse(
				conversation_id=conversation_id,
				state='error',
				reply=get_ta_error(),
			)
		return WizardResponse(
			conversation_id=conversation_id,
			state='error',
			reply=f'No se encontró el CUIT {cuit} en el Padrón A5. Verificá el número e intentá de nuevo.',
		)

	# ── Case 2: CUIT sin tasks → awaiting_tasks ───────────────────────
	if tasks is None:
		return WizardResponse(
			conversation_id=conversation_id,
			state='awaiting_tasks',
			reply=(f'Cliente encontrado: **{cliente_info.get("nombre", cuit)}**. Seleccioná las tareas a ejecutar.'),
			cliente=cliente_info,
		)

	# ── Case 3: CUIT + tasks → processing (SSE) ───────────────────────
	queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
	_loop = asyncio.get_running_loop()
	_progress_messages: list[str] = []

	def _progress(msg: str) -> None:
		_progress_messages.append(msg)
		_loop.call_soon_threadsafe(queue.put_nowait, ('progress', msg))

	async def _run():
		try:
			# Send wizard_state event first
			await queue.put(
				(
					'wizard_state',
					{
						'state': 'processing',
						'reply': 'Generando reporte fiscal...',
						'conversation_id': conversation_id,
						'cliente': cliente_info,
					},
				)
			)
			data = await asyncio.to_thread(_handle_wizard_pipeline, cuit, tasks, _progress, request.send_email)
			from fiscal_agent.domain.response_builder import format_reporte_response

			if data is None:
				from fiscal_agent.adapters.arca_ws import get_ta_error

				reply = format_reporte_response(data, cuit, arca_error=get_ta_error())
			else:
				reply = format_reporte_response(data, cuit)
			pdf_url = None
			if data and data.get('pdf_path'):
				# Extract filename for download URL
				# and ensure pdf_path is a string (not PosixPath) for JSON serialization
				import os

				data['pdf_path'] = str(data['pdf_path'])
				filename = os.path.basename(data['pdf_path'])
				pdf_url = f'/v1/chat/reports/{filename}'
			complete_payload: dict[str, Any] = {
				'reply': reply,
				'data': data,
				'pdf_url': pdf_url,
				'conversation_id': conversation_id,
			}
			if _progress_messages:
				complete_payload['pipeline_steps'] = list(_progress_messages)
			await queue.put(('complete', complete_payload))
		except Exception as exc:
			await queue.put(
				(
					'complete',
					{
						'reply': f'Ocurrió un error al generar el reporte: {exc}',
						'data': None,
						'conversation_id': conversation_id,
					},
				)
			)

	async def _generate():
		task = asyncio.create_task(_run())
		while True:
			event_type, payload = await queue.get()
			if event_type == 'wizard_state':
				yield f'event: wizard_state\ndata: {json.dumps(payload)}\n\n'
			elif event_type == 'progress':
				yield f'event: progress\ndata: {json.dumps({"message": payload})}\n\n'
			elif event_type == 'complete':
				yield f'event: complete\ndata: {json.dumps(payload)}\n\n'
				break
		await task

	return StreamingResponse(
		_generate(),
		media_type='text/event-stream',
		headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no'},
	)


# ── SSE endpoint ─────────────────────────────────────────────────────────


@router.post(
	'/v1/chat/message/stream',
	summary='Enviar mensaje y recibir progreso vía SSE',
)
async def chat_message_stream(
	request: ChatRequest,
	fastapi_request: Request,
):
	"""Igual que ``/v1/chat/message`` pero devuelve SSE con progreso.

	Cada paso del pipeline se envía como un evento ``progress``.
	Al finalizar se envía ``complete`` con la respuesta final.

	Formato SSE::

	        event: conversation_start
	        data: {'conversation_id': '...'}

	        event: progress
	        data: {'message': '  Consultando Padrón A5 ...'}

	        event: complete
	        data: {'reply': '...', 'pdf_url': '...'}
	"""
	message = request.message
	conversation_id = request.conversation_id or str(uuid.uuid4())
	tenant_id = getattr(fastapi_request.state, 'tenant_id', None)
	store: RedisStore | None = getattr(fastapi_request.app.state, 'store', None)

	# Prep history as multi-turn context
	context = message
	if request.history:
		history_text = '\n'.join(m['content'] for m in request.history if m.get('content'))
		context = f'{history_text}\n{message}'

	# 1. Detect intent + extract CUIT (with history context)
	intent, cuit, _params = detect(context)

	# 2-3. Early returns for invalid/no-intent (same as regular endpoint)
	if not cuit and intent != Intent.UNKNOWN:
		reply = 'Por favor, proporcioná un CUIT válido para realizar la consulta.'
		if tenant_id and store is not None:
			await store.append_messages(
				tenant_id,
				conversation_id,
				[
					{'role': 'user', 'content': message},
					{'role': 'assistant', 'content': reply},
				],
			)
		return StreamingResponse(
			_iter_sse_early(conversation_id, reply),
			media_type='text/event-stream',
			headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
		)

	if intent == Intent.UNKNOWN:
		reply = (
			'Podés consultar datos de un contribuyente '
			'(ej: **consulta CUIT 30716395541**) o generar un reporte '
			'completo (ej: **reporte CUIT 30716395541**).'
		)
		if tenant_id and store is not None:
			await store.append_messages(
				tenant_id,
				conversation_id,
				[
					{'role': 'user', 'content': message},
					{'role': 'assistant', 'content': reply},
				],
			)
		return StreamingResponse(
			_iter_sse_early(conversation_id, reply),
			media_type='text/event-stream',
			headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
		)

	if intent != Intent.REPORTE_COMPLETO:
		reply = 'Intento no soportado.'
		if tenant_id and store is not None:
			await store.append_messages(
				tenant_id,
				conversation_id,
				[
					{'role': 'user', 'content': message},
					{'role': 'assistant', 'content': reply},
				],
			)
		return StreamingResponse(
			_iter_sse_early(conversation_id, reply),
			media_type='text/event-stream',
			headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
		)

	# 4. Streaming flow for REPORTE_COMPLETO
	queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
	# Accumulate progress messages so they can be persisted + sent in complete event
	_progress_messages: list[str] = []

	# Capture the event loop BEFORE entering the thread pool,
	# because _progress() is called from inside asyncio.to_thread
	# where get_running_loop() would raise RuntimeError.
	_loop = asyncio.get_running_loop()

	def _progress(msg: str) -> None:
		_progress_messages.append(msg)
		_loop.call_soon_threadsafe(queue.put_nowait, ('progress', msg))

	async def _run():
		try:
			data = await asyncio.to_thread(_handle_reporte_with_echo, cuit, _progress)
			reply = format_reporte_response(data, cuit)
			if tenant_id and store is not None:
				assistant_entry: dict[str, Any] = {'role': 'assistant', 'content': reply}
				if _progress_messages:
					assistant_entry['pipeline_steps'] = list(_progress_messages)
				await store.append_messages(
					tenant_id,
					conversation_id,
					[
						{'role': 'user', 'content': message},
						assistant_entry,
					],
				)
			# Ensure data is JSON-serializable (e.g. PosixPath → str)
			safe_data: dict[str, Any] | None = None
			if data:
				safe_data = {}
				for k, v in data.items():
					safe_data[k] = str(v) if not isinstance(v, (str, int, float, bool, list, dict, type(None))) else v
			complete_payload: dict[str, Any] = {'reply': reply, 'data': safe_data, 'conversation_id': conversation_id}
			if _progress_messages:
				complete_payload['pipeline_steps'] = list(_progress_messages)
			await queue.put(('complete', complete_payload))
		except Exception as exc:
			reply = f'Ocurrió un error: {exc}'
			if tenant_id and store is not None:
				await store.append_messages(
					tenant_id,
					conversation_id,
					[
						{'role': 'user', 'content': message},
						{'role': 'assistant', 'content': reply},
					],
				)
			await queue.put(('complete', {'reply': reply, 'data': None, 'conversation_id': conversation_id}))

	async def _generate():
		# First, yield conversation_start
		yield f'event: conversation_start\ndata: {json.dumps({"conversation_id": conversation_id})}\n\n'
		task = asyncio.create_task(_run())
		while True:
			event_type, payload = await queue.get()
			if event_type == 'progress':
				yield f'event: progress\ndata: {json.dumps({"message": payload})}\n\n'
			elif event_type == 'complete':
				yield f'event: complete\ndata: {json.dumps(payload)}\n\n'
				break
		await task

	return StreamingResponse(
		_generate(),
		media_type='text/event-stream',
		headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no'},
	)


def _iter_sse_early(conversation_id: str, reply: str):
	"""Yield conversation_start then complete SSE events for early returns."""
	yield f'event: conversation_start\ndata: {json.dumps({"conversation_id": conversation_id})}\n\n'
	yield f'event: complete\ndata: {json.dumps({"reply": reply, "conversation_id": conversation_id})}\n\n'


# ── Intent → action name map ──────────────────────────────────────────────

_ACTION_NAMES: dict[Intent, str] = {
	Intent.TAXPAYER_QUERY: 'consultar_cuit',
	Intent.REPORTE_COMPLETO: 'generar_reporte',
}


# ── Endpoint ────────────────────────────────────────────────────────────────


@router.post(
	'/v1/chat/message',
	response_model=ChatResponse,
	summary='Enviar mensaje de chat al asistente fiscal',
)
async def chat_message(
	request: ChatRequest,
	fastapi_request: Request,
) -> ChatResponse:
	"""Procesa un mensaje en lenguaje natural y devuelve una respuesta.

	Detecta la intención y el CUIT mediante expresiones regulares,
	despacha al handler interno correspondiente (ejecutado en un thread
	pool para no bloquear el event loop), y formatea la respuesta en
	español natural.
	"""
	message = request.message
	conversation_id = request.conversation_id or str(uuid.uuid4())
	tenant_id = getattr(fastapi_request.state, 'tenant_id', None)
	store: RedisStore | None = getattr(fastapi_request.app.state, 'store', None)

	# Prep history as multi-turn context
	context = message
	if request.history:
		history_text = '\n'.join(m['content'] for m in request.history if m.get('content'))
		context = f'{history_text}\n{message}'

	# 1. Detect intent + extract CUIT (with history context)
	intent, cuit, _params = detect(context)

	# 2. No CUIT found
	if not cuit and intent != Intent.UNKNOWN:
		reply = 'Por favor, proporcioná un CUIT válido para realizar la consulta.'
		if tenant_id and store is not None:
			await store.append_messages(
				tenant_id,
				conversation_id,
				[
					{'role': 'user', 'content': message},
					{'role': 'assistant', 'content': reply},
				],
			)
		return ChatResponse(
			conversation_id=conversation_id,
			reply=reply,
			actions_taken=[],
		)

	# 3. Unknown intent — show help
	if intent == Intent.UNKNOWN:
		reply = (
			'Podés consultar datos de un contribuyente '
			'(ej: **consulta CUIT 30716395541**) o generar un reporte '
			'completo (ej: **reporte CUIT 30716395541**).'
		)
		if tenant_id and store is not None:
			await store.append_messages(
				tenant_id,
				conversation_id,
				[
					{'role': 'user', 'content': message},
					{'role': 'assistant', 'content': reply},
				],
			)
		return ChatResponse(
			conversation_id=conversation_id,
			reply=reply,
			actions_taken=[],
		)

	# 4. Dispatch to sync handler in thread pool
	action = _ACTION_NAMES.get(intent, 'unknown')

	try:
		if intent == Intent.TAXPAYER_QUERY:
			data = await asyncio.to_thread(_handle_taxpayer, cuit)
			reply = format_taxpayer_response(data, cuit)
		elif intent == Intent.REPORTE_COMPLETO:
			data = await asyncio.to_thread(_handle_reporte, cuit)
			reply = format_reporte_response(data, cuit)
		else:
			data = None
			reply = 'Intento no soportado.'
	except Exception as exc:
		reply = f'Ocurrió un error al procesar la consulta: {exc}'
		if tenant_id and store is not None:
			await store.append_messages(
				tenant_id,
				conversation_id,
				[
					{'role': 'user', 'content': message},
					{'role': 'assistant', 'content': reply},
				],
			)
		return ChatResponse(
			conversation_id=conversation_id,
			reply=reply,
			actions_taken=[action],
		)

	if tenant_id and store is not None:
		await store.append_messages(
			tenant_id,
			conversation_id,
			[
				{'role': 'user', 'content': message},
				{'role': 'assistant', 'content': reply},
			],
		)
	return ChatResponse(
		conversation_id=conversation_id,
		reply=reply,
		actions_taken=[action],
		data=data if data else None,
	)


# ── PDF download ──────────────────────────────────────────────────────────


REPORTS_DIR = Path('/app/output')


@router.get(
	'/v1/chat/reports/{filename:path}',
	summary='Descargar PDF generado por el chat',
)
async def download_report(
	filename: str,
) -> FileResponse:
	"""Serve a generated PDF report for download.

	The file must exist inside the ``/app/output`` directory (Docker volume
	or ``storage/`` local path).
	"""
	# Try Docker path first, fall back to local storage
	full_path = (REPORTS_DIR / filename).resolve()
	if not str(full_path).startswith(str(REPORTS_DIR.resolve())):
		raise HTTPException(status_code=404, detail='Archivo no encontrado')
	if full_path.exists() and full_path.is_file():
		return FileResponse(full_path, media_type='application/pdf', filename=full_path.name)

	# Fallback: local storage/
	local_path = (Path('storage') / filename).resolve()
	if local_path.exists() and local_path.is_file():
		return FileResponse(local_path, media_type='application/pdf', filename=local_path.name)

	raise HTTPException(status_code=404, detail='Archivo no encontrado')
