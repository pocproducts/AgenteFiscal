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
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from uuid import UUID

from agente_fiscal.adapters.db_agent_sessions import PostgresAgentSessionsRepository
from agente_fiscal.api.profile_gate import ActiveProfileContext, validate_active_profile
from agente_fiscal.api.store import RedisStore
from agente_fiscal.db.conversation_repo import (
	insert_generated_pdf,
	upsert_conversation,
)
from agente_fiscal.db.models import ReportRun, User
from agente_fiscal.domain.intent_router import Intent, detect
from agente_fiscal.domain.models import ApiError, UnifiedResponse
from agente_fiscal.domain.response_builder import (
	format_calendario_response,
	format_consultaarca_response,
	format_deuda_response,
	format_facilidades_response,
	format_rentas_response,
	format_reporte_response,
	format_taxpayer_response,
)
from agente_fiscal.domain.session_tasks import build_session_tasks
from agente_fiscal.domain.tool_spec import INTENT_TO_KEY, TOOL_SPECS, ToolSpec
from agente_fiscal.ports.agent_sessions import AgentSession

router = APIRouter()

logger = logging.getLogger(__name__)

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
	profile_id: UUID | None = Field(
		default=None,
		description='Opaque conversation identifier (generated if omitted)',
	)


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
	tools: list[str] | None = Field(
		default=None,
		description='Explicit tool-keys to run as ONE consolidated pipeline '
		'(bypasses detect()); any subset of TOOL_SPECS plus '
		'"informefiscal" (all data tools) and "enviarmail" (send report)',
	)
	conversation_id: str | None = Field(
		default=None,
		description='Opaque conversation identifier (generated if omitted)',
	)
	history: list[dict] | None = Field(
		default=None,
		description='Previous messages: [{"role": "user"|"assistant", "content": str}]',
	)
	profile_id: UUID | None = Field(
		default=None,
		description='Active tenant profile required to generate a report (REPORTE_COMPLETO intent)',
	)
	message_id: str | None = Field(
		default=None,
		description='Opaque message identifier assigned by the frontend; '
		'persisted on the agent_sessions row (AST-4), defaults to None for API/CLI callers',
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


# ── Report-run persistence (active-profile invariant) ──────────────────────


async def _resolve_active_profile(
	fastapi_request: Request,
	profile_id: UUID | None,
) -> ActiveProfileContext | None:
	"""Validate the active-profile invariant for a chat report request.

	Returns ``None`` (no report generation needed) and otherwise the resolved
	tenant/profile/user context, raising 401/400/404/409 via the shared gate.
	"""
	factory = getattr(fastapi_request.app.state, 'session_factory', None)
	if factory is None:
		raise HTTPException(
			status_code=500,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(
					code='REPORT_PERSIST_UNAVAILABLE',
					cause='El store de persistencia (session_factory) no está disponible',
					remediation='Revisa la configuración del servidor',
				),
			).model_dump(),
		)
	async with factory() as session:
		return await validate_active_profile(
			fastapi_request,
			profile_id,
			session,
			missing_code=400,
			not_found_code=404,
			inactive_code=409,
		)


async def _persist_chat_report_run(
	fastapi_request: Request,
	*,
	ctx: ActiveProfileContext,
	cuit: str,
	data: dict[str, Any] | None,
	progress_msgs: list[str],
	mes: int,
	anio: int,
) -> str | None:
	"""Persist a ``report_runs`` row for a chat-driven report (done/failed).

	Synchronous pipeline results land here after execution: status ``done`` on
	success, ``failed`` with an ``error`` JSONB dict when the pipeline reported
	an error or crashed. Returns the ``report_run_id`` (``None`` if the store is
	unavailable) — the SSE/non-stream payload surfaces it for the history UI.
	"""
	factory = getattr(fastapi_request.app.state, 'session_factory', None)
	if factory is None:
		return None

	if data is None or data.get('error'):
		status = 'failed'
		error = {'code': 'PIPELINE_FAILED', 'cause': str((data or {}).get('error') or 'Reporte fallido')}
	else:
		status = 'done'
		error = None

	steps: dict[str, Any] = {'source': 'chat'}
	if progress_msgs:
		steps['progress'] = list(progress_msgs)

	run = ReportRun(
		tenant_id=ctx.tenant_id,
		profile_id=ctx.profile_id,
		user_id=ctx.user_id,
		cuit=cuit,
		status=status,
		steps=steps,
		error=error,
		period_month=mes,
		period_year=anio,
	)

	async with factory() as session:
		session.add(run)
		try:
			await session.commit()
		except Exception:
			await session.rollback()
			return None
	return str(run.id)


# ── Chat conversation persistence (Postgres, best-effort) ────────────────


async def _persist_conversation(
	fastapi_request: Request,
	conversation_id: str,
	messages: list[dict[str, Any]],
	*,
	title: str | None = None,
	profile_id: UUID | None = None,
	status: str = 'running',
) -> None:
	"""Persiste la conversación en Postgres sin romper el streaming SSE.

	La DB nunca debe romper la respuesta: si la session factory falta, el
	tenant no se resuelve o el commit falla, se loguea un warning y se sigue.
	El ``user_id`` ORM se resuelve desde ``clerk_user_id`` (None para API keys).
	"""
	factory = getattr(fastapi_request.app.state, 'session_factory', None)
	tenant_id = getattr(fastapi_request.state, 'tenant_id', None)
	if factory is None or not tenant_id:
		return
	try:
		tenant_uuid = UUID(str(tenant_id))
	except (TypeError, ValueError):
		return
	clerk_user_id = getattr(fastapi_request.state, 'clerk_user_id', None)
	try:
		async with factory() as session:
			user_id: UUID | None = None
			if clerk_user_id:
				user_id = await session.scalar(
					select(User.id).where(User.clerk_user_id == clerk_user_id).limit(1)
				)
			result = await upsert_conversation(
				session,
				tenant_id=tenant_uuid,
				user_id=user_id,
				profile_id=profile_id,
				conversation_id=conversation_id,
				title=title,
				messages=messages,
				status=status,
			)
		if result is None:
			# CD-2: la conversación fue borrada (tombstone, ADR-5) — el upsert
			# NO la resucita. El flujo lo trata como missing-conversation.
			logger.info(
				'Conversación %s borrada durante el stream — se saltea la persistencia del turno',
				conversation_id,
			)
			return False
		return True
	except Exception as exc:
		logger.warning('No se pudo persistir la conversación %s en Postgres: %s', conversation_id, exc)
		return False


async def _persist_agent_session_start(
	fastapi_request: Request,
	*,
	tool: str,
	message_id: str | None,
	conversation_id: str,
	tenant_id: uuid.UUID | None,
	profile_id: UUID | None,
	session_id: str | None = None,
) -> str | None:
	"""Inserta la fila ``agent_sessions`` en estado ``running`` (best-effort, AST-2/3).

	Se llama en el dispatch, ANTES de que la tool ejecute: el row queda en la DB
	en el momento exacto en que la UI muestra "Iniciando un chat…". El id
	generado (uuid4) se usa luego en :func:`_persist_agent_session` para
	COMPLETAR la misma fila (nunca se duplica). Mirrors ``_persist_agent_session``:
	sin factory o sin tenant se saltea; los fallos de DB se loguean y el stream
	SSE nunca se rompe (ADR-3).
	"""
	factory = getattr(fastapi_request.app.state, 'session_factory', None)
	if factory is None or not tenant_id:
		return None
	try:
		clerk_user_id = getattr(fastapi_request.state, 'clerk_user_id', None)
		user_id: UUID | None = None
		if clerk_user_id:
			async with factory() as session:
				user_id = await session.scalar(
					select(User.id).where(User.clerk_user_id == clerk_user_id).limit(1)
				)
		repo = PostgresAgentSessionsRepository(factory)
		sid = str(uuid.uuid4())
		await repo.record(
			AgentSession(
				id=sid,
				tool=tool,
				message_id=message_id,
				conversation_id=conversation_id,
				profile_id=str(profile_id) if profile_id else None,
				tenant_id=str(tenant_id),
				user_id=str(user_id) if user_id else None,
				session_id=session_id,
				status='running',
				tasks=[],
				cost_cents=0,
				started_at=datetime.now(timezone.utc),
				completed_at=None,
			)
		)
		return sid
	except Exception as exc:
		logger.warning(
			'No se pudo registrar el inicio de la sesión de agente %s: %s', tool, exc
		)
		return None


async def _persist_conversation_start(
	fastapi_request: Request,
	conversation_id: str,
	message: str,
	profile_id: UUID | None,
) -> None:
	"""Persiste la conversación en estado ``running`` al dispatch (AST-2/3, ADR-3).

	Se llama ANTES de que la tool corra: la fila queda en Postgres en el
	instante en que la UI dice "Iniciando un chat…" para que el sidebar la
	muestre al toque. El upsert post-run (status 'done') completa la MISMA
	fila (idempotente por role/content — nunca duplica el mensaje de usuario).
	Best-effort: sin factory/tenant o fallo de DB se loguea y el stream nunca
	se rompe.
	"""
	await _persist_conversation(
		fastapi_request,
		conversation_id,
		[{'role': 'user', 'content': message}],
		profile_id=profile_id,
		status='running',
	)


async def _persist_agent_session(
	fastapi_request: Request,
	*,
	tool: str,
	agent_session_id: str | None = None,
	message_id: str | None,
	conversation_id: str,
	tenant_id: uuid.UUID | None,
	profile_id: UUID | None,
	status: str,
	tasks: list[dict[str, Any]],
	cost_cents: int = 0,
	session_id: str | None = None,
	started_at: datetime | None = None,
	completed_at: datetime | None = None,
) -> None:
	"""Persiste UNA fila de telemetría ``agent_sessions`` (best-effort, AST-2/3).

	Mirrors ``_persist_conversation``: sin factory o sin tenant se saltea; los
	fallos de DB se loguean y el stream SSE nunca se rompe (ADR-3). El row se
	crea en el dispatch con status ``running`` (``_persist_agent_session_start``,
	'Comenzó') y esta helper lo COMPLETA post-run vía ``repo.complete`` —
	actualiza la MISMA fila (id), nunca toca tool/ids/started_at. Sin
	``agent_session_id`` (fila nunca pre-iniciada) inserta una fila completa
	post-run con ``record``, preservando el comportamiento previo.
	"""
	factory = getattr(fastapi_request.app.state, 'session_factory', None)
	if factory is None or not tenant_id:
		return
	try:
		repo = PostgresAgentSessionsRepository(factory)
		if agent_session_id:
			await repo.complete(
				agent_session_id,
				status=status,
				tasks=tasks,
				completed_at=completed_at,
				cost_cents=cost_cents,
			)
			return
		clerk_user_id = getattr(fastapi_request.state, 'clerk_user_id', None)
		user_id: UUID | None = None
		if clerk_user_id:
			async with factory() as session:
				user_id = await session.scalar(
					select(User.id).where(User.clerk_user_id == clerk_user_id).limit(1)
				)
		await repo.record(
			AgentSession(
				id=str(uuid.uuid4()),
				tool=tool,
				message_id=message_id,
				conversation_id=conversation_id,
				profile_id=str(profile_id) if profile_id else None,
				tenant_id=str(tenant_id),
				user_id=str(user_id) if user_id else None,
				session_id=session_id,
				status=status,
				tasks=tasks,
				cost_cents=cost_cents,
				started_at=started_at,
				completed_at=completed_at,
			)
		)
	except Exception as exc:
		logger.warning('No se pudo persistir la sesión de agente %s: %s', tool, exc)


async def _persist_chat_pdf(
	fastapi_request: Request,
	report_run_id: str,
	pdf_path: str | Path,
) -> None:
	"""Persiste los bytes del PDF generado en ``generated_pdfs`` (best-effort)."""
	factory = getattr(fastapi_request.app.state, 'session_factory', None)
	if factory is None or not report_run_id or not pdf_path:
		return
	try:
		path = Path(pdf_path)
		if not path.is_file():
			logger.warning('PDF %s no existe en disco — saltando persistencia', pdf_path)
			return
		data = path.read_bytes()
		async with factory() as session:
			await insert_generated_pdf(
				session,
				report_run_id=UUID(str(report_run_id)),
				storage_key=f'storage/calendarios/{path.name}',
				filename=path.name,
				data=data,
			)
	except Exception as exc:
		logger.warning('No se pudo persistir el PDF %s en generated_pdfs: %s', pdf_path, exc)


# ── Sync handlers (run in thread pool to avoid blocking the event loop) ──────


def _handle_taxpayer(cuit: str) -> dict[str, Any] | None:
	"""Consult taxpayer data via ARCA WS API (sync).

	Devuelve el dict completo del padrón (``PadronA5Result.to_dict()``) para
	que la UI pueda mostrar la información íntegra del contribuyente, incluido
	el detalle de ``errorConstancia`` cuando la persona no existe o está dada de baja.
	"""
	from agente_fiscal.api.deps import REPRESENTANTE_CUIT, get_ta
	from agente_fiscal.adapters.arca_ws import consultar_cuit

	token, sign = get_ta()
	if not token or not sign:
		return None

	try:
		result = consultar_cuit(cuit, token, sign, REPRESENTANTE_CUIT)
		return result.to_dict()
	except Exception as exc:
		return {'error': str(exc)}


def _handle_reporte(cuit: str) -> dict[str, Any] | None:
	"""Generate a complete fiscal report (sync — delegates to ``_procesar_cliente_pipeline``).

	Mirrors the CLI ``report`` flow but returns structured data instead of
	printing to console.  Runs the same ``_procesar_cliente_pipeline()``
	shared by the CLI so behaviour is identical.
	"""
	from datetime import datetime

	from agente_fiscal.api.deps import REPRESENTANTE_CUIT, get_engine, get_memory, get_pdf_gen, get_ta
	from agente_fiscal.cli import _procesar_cliente_pipeline
	from agente_fiscal.domain.models import ClientConfig
	from agente_fiscal.pipeline.service import PipelineService, _completar_cliente_desde_padron

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

	from agente_fiscal.adapters.browser.provider import build_browser_provider
	from agente_fiscal.features import IntegrationDisabledError, integration_enabled

	if not integration_enabled('browser'):
		raise IntegrationDisabledError('browser')

	browser = build_browser_provider()
	with_browser = browser is not None

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


def _run_browser_tool(
	spec: ToolSpec,
	cuit: str,
	echo_func: Optional[Callable[[str], None]] = None,
	on_live_url: Optional[Callable[[str], None]] = None,
	on_step: Optional[Callable[[int, str, str, str], None]] = None,
	*,
	session_store: object | None = None,
	binding: object | None = None,
	on_task_metrics: Optional[Callable[[dict], None]] = None,
) -> dict[str, Any] | None:
	"""Ejecuta una tool de browser (Phase-1) vía el provider configurado.

	Generalización de ``_handle_sistemaregistral``: para cualquier ToolSpec con
	``needs_browser=True`` corre ``build_browser_tasks(**spec.task_flags)`` →
	``BrowserPort.run_single`` → devuelve el dict de salida para el
	formatter. Mantiene los guards existentes (COMPOSIO_KEY_MISSING /
	INTEGRATION_DISABLED / BROWSER_ERROR).

	``on_live_url`` se invoca en cuanto el provider provisiona la sesión de browser
	(viva), para que el frontend pueda embeberla mientras la automatización corre.

	``session_store``/``binding``/``on_task_metrics`` habilitan el reuso de
	sesión persistida de Browserbase: el provider recibe el binding (context
	ya logueado) y devuelve las métricas reales del run vía el callback síncrono
	(el wiring async las persiste con await).
	"""
	from agente_fiscal.api.deps import REPRESENTANTE_CUIT, get_ta
	from agente_fiscal.adapters.browser.factory import build_browser_tasks
	from agente_fiscal.adapters.browser.provider import build_browser_provider
	from agente_fiscal.config import get_settings
	from agente_fiscal.domain.models import ClientConfig
	from agente_fiscal.features import integration_enabled

	token, sign = get_ta()
	if not token or not sign:
		return None

	creds = get_settings().credentials
	if not integration_enabled('browser'):
		return {
			'error': 'INTEGRATION_DISABLED',
			'detail': 'La integración de browser (Composio) está deshabilitada (BROWSER_ENABLED=false).',
		}

	browser = build_browser_provider(
		session_store=session_store,
		binding=binding,
	)
	if browser is None:
		return {
			'error': 'COMPOSIO_KEY_MISSING',
			'detail': f'Falta COMPOSIO_API_KEY o ESTUDIO_CLAVE_FISCAL en .env para usar {spec.tool_name}.',
		}
	try:
		tasks = build_browser_tasks(
			cuit=REPRESENTANTE_CUIT,
			clave=creds.clave_fiscal,
			cliente_cuit=cuit,
			**spec.task_flags,
		)
		_metrics_holder: dict[str, Any] = {}

		def _real_metrics(metrics: dict) -> None:
			# Propaga al caller (holder last-write + SSE) solo si algo se emitió;
			# _metrics_holder local permite detectar providers sin telemetría.
			_metrics_holder.update(metrics)
			if on_task_metrics:
				on_task_metrics(metrics)

		out = browser.run_single(
			ClientConfig(cuit=cuit),
			tasks=tasks,
			echo_func=echo_func,
			on_live_url=on_live_url,
			on_step=on_step,
			on_task_metrics=_real_metrics,
		)
		# ADR-7: Composio no emite métricas por callback (run_single lo ignora).
		# Resuelve session_id + event_count vía telemetría API post-run —
		# best-effort, nunca falla; mock queda con session_id NULL por diseño.
		if not _metrics_holder and hasattr(browser, '_api_key'):
			from agente_fiscal.adapters.browser.composio_telemetry import ComposioTelemetry

			run = ComposioTelemetry(browser._api_key).resolve_run()
			if run:
				_run_metrics: dict[str, Any] = {}
				if run.get('session_id'):
					_run_metrics['session_id'] = run['session_id']
				if run.get('event_count'):
					_run_metrics['tasks'] = build_session_tasks(
						spec.tool_key or spec.tool_name,
						'completed',
						count=int(run['event_count']),
					)
				if _run_metrics and on_task_metrics:
					on_task_metrics(_run_metrics)
	except Exception as exc:
		return {'error': 'BROWSER_ERROR', 'detail': str(exc)}

	if out.error:
		return {'error': 'BROWSER_ERROR', 'detail': out.error, 'live_url': out.live_url}
	# mode='json': date/Decimal → ISO/float, seguro para el framing SSE.
	return out.model_dump(mode='json')


def _run_engine_tool(
	spec: ToolSpec,
	cuit: str,
	echo_func: Optional[Callable[[str], None]] = None,
) -> dict[str, Any] | None:
	"""Ejecuta una tool determinista (Phase-2) sin sessión de browser.

	Design D1 (opción b): ``consultaarca`` → padrón A5 (``arca_ws.consultar_cuit``);
	``calendariovencimientosarca`` → ``RulesEngine.calcular``. Reusa los códigos
	de error de ``routes/calendar.py`` (TA_UNAVAILABLE | TAXPAYER_QUERY_FAILED |
	TAXPAYER_NOT_FOUND | CALENDAR_FAILED) y emite un ``progress`` por etapa.

	``PadronNotFoundError`` (SOAP Fault ``No existe persona con ese Id``) se
	mapea a ``TAXPAYER_NOT_FOUND``; el resto de fallos del padrón a
	``TAXPAYER_QUERY_FAILED``. Para ``TA_UNAVAILABLE`` se incluye la causa real
	de ``get_ta_error()`` (certificados ausentes, WSAA caído, timeout, etc.).
	"""
	from datetime import datetime

	from agente_fiscal.adapters.arca_ws import PadronNotFoundError, consultar_cuit, get_ta_error
	from agente_fiscal.api.deps import REPRESENTANTE_CUIT, get_engine, get_ta

	token, sign = get_ta()
	if not token or not sign:
		reason = get_ta_error() or 'No se pudo obtener el Ticket de Acceso de ARCA'
		return {'error': 'TA_UNAVAILABLE', 'detail': reason}

	if echo_func:
		echo_func('  Consultando Padrón A5 ...')
	try:
		result = consultar_cuit(cuit, token, sign, REPRESENTANTE_CUIT)
		output = result.to_output()
	except PadronNotFoundError as exc:
		return {'error': 'TAXPAYER_NOT_FOUND', 'detail': str(exc)}
	except Exception as exc:
		return {'error': 'TAXPAYER_QUERY_FAILED', 'detail': str(exc)}

	if output.errorConstancia:
		errors = '; '.join(output.errorConstancia.error)
		return {'error': 'TAXPAYER_NOT_FOUND', 'detail': errors}

	if spec.tool_key == 'consultaarca':
		return result.to_dict()

	if spec.tool_key == 'calendariovencimientosarca':
		if echo_func:
			echo_func('  Calculando calendario fiscal ...')
		now = datetime.utcnow()
		engine = get_engine()
		try:
			calendario = engine.calcular(output, now.month, now.year)
		except Exception as exc:
			return {'error': 'CALENDAR_FAILED', 'detail': str(exc)}
		# mode='json': date/Decimal → ISO/float, seguro para SSE.
		return calendario.model_dump(mode='json')

	return {'error': 'BROWSER_ERROR', 'detail': f'Motor no implementado para tool {spec.tool_key}'}


def _handle_tool_data(
	spec: ToolSpec,
	cuit: str,
	echo_func: Optional[Callable[[str], None]] = None,
) -> dict[str, Any] | None:
	"""Dispatch no-streaming de una tool: browser o motor según el ToolSpec."""
	if spec.needs_browser:
		return _run_browser_tool(spec, cuit, echo_func=echo_func)
	return _run_engine_tool(spec, cuit, echo_func=echo_func)


def format_registro_response(data: dict[str, Any] | None, cuit: str) -> str:
	"""Formatea el RegistroOutput del Sistema Registral en markdown coherente al CUIT."""
	if not data or data.get('error'):
		err = (data or {}).get('error')
		# Composio connection failures (HTTP 403 / BROWSER_ERROR) map to a short,
		# user-friendly reason instead of leaking the raw Composio traceback.
		if err == 'BROWSER_ERROR':
			return (
				f'No pude consultar el Sistema Registral para el CUIT {cuit}.\n\n'
				'**Motivo:** Error de conexión'
			)
		detail = (data or {}).get('detail') or 'Error desconocido'
		return (
			f'No pude consultar el Sistema Registral para el CUIT {cuit}.\n\n'
			f'**Motivo:** `{err}` — {detail}'
		)
	registro = data.get('registro') or {}
	jurisdiccion = registro.get('jurisdiccion')
	domicilios = registro.get('domicilios') or []
	actividades = registro.get('actividades') or []
	impuestos = registro.get('impuestos') or []
	puntos = registro.get('puntos_de_venta') or []

	lines = [f'**Sistema Registral (ARCA)** — CUIT {cuit}', '']
	if jurisdiccion:
		lines.append(f'- **Jurisdicción:** {jurisdiccion}')
	if domicilios:
		lines.append('- **Domicilios:**')
		for d in domicilios[:3]:
			calle = d.get('calle') or d.get('direccion') or ''
			loc = d.get('localidad') or d.get('provincia') or ''
			lines.append(f'  - {calle} — {loc}'.strip())
	if actividades:
		lines.append('- **Actividades:**')
		for a in actividades[:5]:
			cod = a.get('codigo', '')
			desc = a.get('descripcion', '')
			lines.append(f'  - `{cod}` {desc}'.strip())
	if impuestos:
		lines.append('- **Impuestos inscriptos:**')
		for i in impuestos[:8]:
			cod = i.get('codigo', '')
			desc = i.get('descripcion', '')
			lines.append(f'  - `{cod}` {desc}'.strip())
	if puntos:
		lines.append(f'- **Puntos de venta:** {len(puntos)}')
	lines.append('')
	lines.append('_Datos obtenidos del Sistema Registral ARCA en vivo (CUIT coherente)._')
	return '\n'.join(lines)


# ── Resolver de formatters por ToolSpec ─────────────────────────────────────
# ``format_registro_response`` vive en este módulo (chat.py, design: reusarlo
# vía ``formatter_name``); los 5 restantes en domain/response_builder.py.

_FORMATTERS: dict[str, Callable[[dict[str, Any] | None, str], str]] = {
	'format_registro_response': format_registro_response,
	'format_deuda_response': format_deuda_response,
	'format_facilidades_response': format_facilidades_response,
	'format_rentas_response': format_rentas_response,
	'format_consultaarca_response': format_consultaarca_response,
	'format_calendario_response': format_calendario_response,
}


def _resolve_formatter(formatter_name: str) -> Callable[[dict[str, Any] | None, str], str]:
	"""Resuelve el formatter por nombre desde el registro del dispatch."""
	formatter = _FORMATTERS.get(formatter_name)
	if formatter is None:
		raise KeyError(f'formatter no registrado: {formatter_name}')
	return formatter


def _json_safe(data: dict[str, Any] | None) -> dict[str, Any] | None:
	"""Aplana valores no serializables (datetime, date, PosixPath…) a str."""
	if not data:
		return None
	safe: dict[str, Any] = {}
	for k, v in data.items():
		if isinstance(v, (str, int, float, bool, list, dict, type(None))):
			safe[k] = v
		else:
			safe[k] = str(v)
	return safe


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

	from agente_fiscal.api.deps import REPRESENTANTE_CUIT, get_engine, get_memory, get_pdf_gen, get_ta
	from agente_fiscal.cli import _procesar_cliente_pipeline
	from agente_fiscal.domain.models import ClientConfig
	from agente_fiscal.pipeline.service import PipelineService, _completar_cliente_desde_padron

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

	from agente_fiscal.adapters.browser.provider import build_browser_provider
	from agente_fiscal.features import IntegrationDisabledError, integration_enabled

	if not integration_enabled('browser'):
		raise IntegrationDisabledError('browser')

	browser = build_browser_provider()
	with_browser = browser is not None

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

	from agente_fiscal.api.deps import REPRESENTANTE_CUIT, get_engine, get_memory, get_pdf_gen, get_ta
	from agente_fiscal.cli import _procesar_cliente_pipeline
	from agente_fiscal.domain.models import ClientConfig
	from agente_fiscal.pipeline.service import _completar_cliente_desde_padron

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

	uses_browser = tasks.deuda or tasks.facilidades or tasks.registro or tasks.iibb
	browser = None

	if uses_browser:
		from agente_fiscal.adapters.browser.provider import build_browser_provider
		from agente_fiscal.features import IntegrationDisabledError, integration_enabled

		if not integration_enabled('browser'):
			raise IntegrationDisabledError('browser')

		browser = build_browser_provider()
		if browser is None:
			echo_func('  ⚠️  Credenciales de browser no configuradas — algunas tareas no estarán disponibles')

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


# ── Multi-tool: consolidated pipeline (arbitrary subset) ──────────────────


def _resolve_tool_flags(tools: list[str] | None) -> tuple[WizardTasks | None, set[str], bool]:
	"""Mapea una lista de tool-keys a los flags del pipeline consolidado.

	Returns:
		``(tasks, deterministic, send_email)``:
		- ``tasks``: ``WizardTasks`` con los flags booleanos de las tools de
		  browser, resueltos desde ``TOOL_SPECS[key].task_flags`` (fuente única,
		  sin hardcodear mapeos en otro lado). ``None`` si no hay tools.
		- ``deterministic``: set de tools de motor determinista presentes
		  (consultaarca / calendariovencimientosarca — no son flags de pipeline).
		- ``send_email``: ``True`` cuando la selección incluye ``enviarmail``.
	"""
	if not tools:
		return None, set(), False

	keys = [k for k in tools if k]
	flags = {'with_deuda': False, 'with_facilidades': False, 'with_registro': False, 'with_iibb': False}
	deterministic: set[str] = set()

	# ``informefiscal`` equivale a TODAS las tools de datos (reporte completo):
	# los 4 flags de browser y los 2 motores deterministas.
	if 'informefiscal' in keys:
		flags = {k: True for k in flags}
		deterministic = {'consultaarca', 'calendariovencimientosarca'}

	for key in keys:
		spec = TOOL_SPECS.get(key)
		if spec is None:
			continue
		for flag, val in (spec.task_flags or {}).items():
			if flag in flags:
				flags[flag] = bool(val)
		if not spec.needs_browser:
			deterministic.add(key)

	tasks = WizardTasks(
		deuda=flags['with_deuda'],
		facilidades=flags['with_facilidades'],
		registro=flags['with_registro'],
		iibb=flags['with_iibb'],
	)
	send_email = 'enviarmail' in keys
	return tasks, deterministic, send_email


def _mail_input_marker(pdf_path: object) -> str:
	"""Build the ``[MAIL_INPUT_REPLACEMENT:<b64>]`` marker for a report PDF.

	Encodes only the basename of the PDF (``Path.name``) with urlsafe base64
	(no padding), same encoding family as the ``INFORME_FISCAL_BUTTON`` marker.
	"""
	import base64

	filename = Path(str(pdf_path)).name
	marker = base64.urlsafe_b64encode(filename.encode('utf-8')).decode('ascii').rstrip('=')
	return f'[MAIL_INPUT_REPLACEMENT:{marker}]'


# Flag WizardTasks → tool_key (action) y label para la respuesta consolidada.
_PIPELINE_FLAG_TO_ACTION: dict[str, str] = {
	'deuda': 'deudavencimientos',
	'facilidades': 'misfacilidades',
	'registro': 'sistemaregistral',
	'iibb': 'rentascordoba',
}

_PIPELINE_FLAG_LABELS: dict[str, str] = {
	'deuda': 'Deuda y vencimientos (ARCA)',
	'facilidades': 'Mis Facilidades (ARCA)',
	'registro': 'Sistema Registral (ARCA)',
	'iibb': 'IIBB Córdoba (Rentas)',
}

#: Orden canónico de las tools de browser en la respuesta consolidada.
_PIPELINE_FLAG_ORDER: tuple[str, ...] = ('deuda', 'facilidades', 'registro', 'iibb')

#: Orden de los motores deterministas en la respuesta consolidada.
_DETERMINISTIC_ORDER: tuple[str, ...] = ('consultaarca', 'calendariovencimientosarca')

#: Tools de browser que corren como UNA corrida consolidada de pipeline.
#: Toque ordenado: la primera key de esta tupla presente en la selección
#: etiqueta la única fila de telemetría del pipeline (AST-2).
_PIPELINE_TOOL_KEYS: tuple[str, ...] = (
	'informefiscal',
	'deudavencimientos',
	'misfacilidades',
	'sistemaregistral',
	'rentascordoba',
	'enviarmail',
)


def _primary_pipeline_tool_key(tools: list[str]) -> str:
	"""Tool key primaria para la fila consolidada del pipeline de browser.

	Fila única por corrida consolidada (AST-2): se etiqueta con la primera
	tool de browser de la selección; si la selección no trae browser keys se
	usa ``informefiscal`` como fallback honesto (sin inventar una tool).
	"""
	for key in tools or []:
		if key in _PIPELINE_TOOL_KEYS:
			return key
	return 'informefiscal'


def _handle_selected_tools_pipeline(
	cuit: str,
	tools: list[str],
	echo_func: Callable[[str], None],
	*,
	fastapi_request: Request | None = None,
	conversation_id: str = '',
	message_id: str | None = None,
	profile_id: UUID | None = None,
	tenant_id: UUID | None = None,
	prestarted_ids: dict[str, str] | None = None,
) -> dict[str, Any]:
	"""Ejecuta una selección arbitraria de tools como UN solo pipeline consolidado.

	Las tools de browser (sistemaregistral / deudavencimientos / misfacilidades
	/ rentascordoba) corren como una única ejecución de
	``_procesar_cliente_pipeline`` con los flags resueltos desde ``TOOL_SPECS``
	(reusa exactamente el machinery del wizard). Los motores deterministas
	(consultaarca / calendariovencimientosarca) se ejecutan individualmente vía
	``_run_engine_tool`` y sus resultados se mergean en el reply/data final.

	Best-effort por tool: ninguna falla propaga excepción — los errores se
	colectan en el reply y ``actions_taken`` solo marca las tools completadas.

	El pipeline es síncrono (corre en ``asyncio.to_thread``), así que NO
	persiste nada: colecta registros livianos de telemetría (AST-2/3) en
	``sessions`` y cada caller async los persiste tras el retorno con
	``_persist_agent_session`` (nunca ``asyncio.run`` dentro del loop). Los
	kwargs de contexto (``conversation_id``/``message_id``/``profile_id``/
	``tenant_id``) se estampan en cada registro; son opcionales para no romper
	callers existentes y tests.

	``prestarted_ids`` (tool_key → id de fila ``running`` ya insertada por el
	caller antes de ``to_thread``) se estampa en cada registro como
	``agent_session_id``: el persist post-run completa la MISMA fila en vez de
	crear una nueva. Una key sin id prestarteado queda sin ``agent_session_id``
	y el caller vuelve al flujo anterior (INSERT completo post-run).

	Returns:
		Dict compatible con ``ChatResponse``:
		``{reply, data, actions_taken, sessions}``.
	"""
	tasks, deterministic, send_email = _resolve_tool_flags(tools)

	data: dict[str, Any] = {}
	actions_taken: list[str] = []
	notes: list[str] = []
	errors: list[str] = []
	#: Telemetría agent_sessions (AST-2/3): una fila por run real ejecutado.
	#: Registros livianos; el persist async lo hace el caller (ADR-3).
	sessions: list[dict[str, Any]] = []
	#: Pedido de dirección de email (marker) — se anexa SIEMPRE al final del reply.
	email_prompt: str | None = None

	# ── Pipeline consolidado de browser (una sola corrida) ───────────────
	# Corre también cuando solo se pide enviarmail: el pipeline es la fuente
	# del reporte que hay que enviar. Con solo tools deterministas no corre.
	uses_pipeline = tasks is not None and (
		tasks.deuda or tasks.facilidades or tasks.registro or tasks.iibb or send_email
	)
	_primary_key = _primary_pipeline_tool_key(tools)
	if uses_pipeline:
		_pipeline_started = datetime.now(timezone.utc)
		pipeline = _handle_wizard_pipeline(cuit, tasks, echo_func, send_email=send_email)
		_pipeline_completed = datetime.now(timezone.utc)
		if pipeline is None:
			errors.append('No se pudo ejecutar el pipeline consolidado (credenciales ARCA no disponibles).')
		else:
			pipeline = _json_safe(pipeline)
			data.update(pipeline)
			if pipeline.get('error'):
				errors.append(f'Pipeline consolidado: {pipeline["error"]}')
			else:
				for flag in _PIPELINE_FLAG_ORDER:
					if getattr(tasks, flag):
						actions_taken.append(_PIPELINE_FLAG_TO_ACTION[flag])
						notes.append(f'✅ {_PIPELINE_FLAG_LABELS[flag]}')
			if send_email:
				actions_taken.append('send_email')
				if pipeline.get('email'):
					notes.append('✅ Email enviado al cliente')
				elif pipeline.get('pdf_path'):
					# El pedido de dirección va SIEMPRE como última línea del reply
					# (email_prompt se anexa al final en la sección de reply).
					email_prompt = (
						'⚠️ Email no enviado (sin dirección configurada). Escribí la dirección para enviar el reporte: '
						f'{_mail_input_marker(pipeline["pdf_path"])}'
					)
				else:
					notes.append('⚠️ Email no enviado (sin dirección configurada o error en la extracción)')
		# AST-2: UNA fila por corrida consolidada de browser. Status derivado
		# del resultado (None o ``error`` → 'error'); ``tasks`` sigue la regla
		# de la tool primaria (7 labels solo para consultaarca).
		_pipeline_status = 'error' if (pipeline is None or pipeline.get('error')) else 'completed'
		sessions.append(
			{
				'tool': _primary_key,
				'status': _pipeline_status,
				'message_id': message_id,
				'conversation_id': conversation_id,
				'profile_id': profile_id,
				'tenant_id': tenant_id,
				'tasks': build_session_tasks(_primary_key, _pipeline_status),
				'started_at': _pipeline_started,
				'completed_at': _pipeline_completed,
				'agent_session_id': (prestarted_ids or {}).get(_primary_key),
			}
		)

	# ── Motores deterministas (best-effort individual) ───────────────────
	for key in _DETERMINISTIC_ORDER:
		if key not in deterministic:
			continue
		spec = TOOL_SPECS[key]
		_run_started = datetime.now(timezone.utc)
		resultado = _run_engine_tool(spec, cuit, echo_func)
		_run_completed = datetime.now(timezone.utc)
		_tool_key = spec.tool_key or spec.tool_name
		# AST-2: una fila por engine determinista realmente ejecutado; status
		# desde el dict (error key), duración = round-trip (ADR-3).
		_run_status = 'error' if (resultado and resultado.get('error')) else 'completed'
		sessions.append(
			{
				'tool': _tool_key,
				'status': _run_status,
				'message_id': message_id,
				'conversation_id': conversation_id,
				'profile_id': profile_id,
				'tenant_id': tenant_id,
				'tasks': build_session_tasks(_tool_key, _run_status),
				'started_at': _run_started,
				'completed_at': _run_completed,
				'agent_session_id': (prestarted_ids or {}).get(_tool_key),
			}
		)
		if resultado and not resultado.get('error'):
			data[key] = resultado
			actions_taken.append(key)
			notes.append(_resolve_formatter(spec.formatter_name)(resultado, cuit))
		else:
			detalle = (resultado or {}).get('detail') or (resultado or {}).get('error') or 'Error desconocido'
			errors.append(f'⚠️ **{spec.tool_name}:** no se pudo consultar ({detalle})')

	# ── Reply consolidado ────────────────────────────────────────────────
	lines = [f'**Reporte consolidado — CUIT {cuit}**', '']
	if notes:
		lines.append('\n\n'.join(notes))
	if errors:
		lines.append('\n')
		lines.append('### Consultas con errores')
		lines.append('\n'.join(errors))
	if not notes and not errors and not actions_taken:
		lines.append('No se reconoció ninguna herramienta seleccionada.')

	# El pedido de dirección del email va SIEMPRE al final del reply.
	if email_prompt:
		lines.append('\n')
		lines.append(email_prompt)

	return {'reply': '\n'.join(lines), 'data': data or None, 'actions_taken': actions_taken, 'sessions': sessions}


async def _append_and_persist(
	fastapi_request: Request,
	conversation_id: str,
	message: str,
	reply: str,
	tenant_id: object | None,
	store: RedisStore | None,
	*,
	profile_id: UUID | None,
) -> None:
	"""Persiste user+assistant (Redis + Postgres) para los handlers multi-tool."""
	if tenant_id and store is not None:
		await store.append_messages(
			tenant_id,
			conversation_id,
			[
				{'role': 'user', 'content': message},
				{'role': 'assistant', 'content': reply},
			],
		)
	await _persist_conversation(
		fastapi_request,
		conversation_id,
		[
			{'role': 'user', 'content': message},
			{'role': 'assistant', 'content': reply},
		],
		profile_id=profile_id,
		status='done',
	)


async def _prestart_agent_sessions(
	fastapi_request: Request,
	*,
	tools: list[str],
	message_id: str | None,
	conversation_id: str,
	tenant_id: uuid.UUID | None,
	profile_id: UUID | None,
) -> dict[str, str]:
	"""Pre-inicia (status ``running``) las filas agent_sessions que el pipeline creará.

	Corre en el caller async ANTES de ``asyncio.to_thread``: para cada tool que
	realmente produce una fila de telemetría se inserta el row YA (AST-2/3) —
	"Iniciando un chat…" en la UI se emite en el mismo dispatch. Pre-inicia SOLO
	las keys que generan row (tool primaria del pipeline + engines deterministas:
	una selección con varias browser tools crea UNA sola fila consolidada; el
	resto de las keys no crea row y no se pre-inicia para no dejar filas
	huérfanas en estado ``running``). Best-effort (ADR-3): sin factory/tenant o
	fallo de DB → esa key no se prestarta y el persist post-run vuelve al flujo
	anterior (INSERT completo).
	"""
	_tasks, _deterministic, _send_email = _resolve_tool_flags(tools or [])
	_keys: list[str] = []
	if _tasks is not None and (
		_tasks.deuda or _tasks.facilidades or _tasks.registro or _tasks.iibb or _send_email
	):
		_keys.append(_primary_pipeline_tool_key(tools or []))
	_keys.extend(k for k in _DETERMINISTIC_ORDER if k in _deterministic)
	prestarted_ids: dict[str, str] = {}
	for _tool in _keys:
		_sid = await _persist_agent_session_start(
			fastapi_request,
			tool=_tool,
			message_id=message_id,
			conversation_id=conversation_id,
			tenant_id=tenant_id,
			profile_id=profile_id,
		)
		if _sid:
			prestarted_ids[_tool] = _sid
	return prestarted_ids


async def _handle_multi_tool_message(
	request: ChatRequest,
	fastapi_request: Request,
	cuit: str | None,
	conversation_id: str,
	tenant_id: object | None,
	store: RedisStore | None,
	message: str,
) -> ChatResponse:
	"""Dispatch no-streaming de una solicitud con ``tools`` explícito."""
	if not cuit:
		reply = 'Por favor, proporcioná un CUIT válido para realizar la consulta.'
		await _append_and_persist(
			fastapi_request,
			conversation_id,
			message,
			reply,
			tenant_id,
			store,
			profile_id=request.profile_id,
		)
		return ChatResponse(conversation_id=conversation_id, reply=reply, actions_taken=[])

	# Telemetría agent_sessions (AST-2/3, ADR-3): pre-inicia las filas running
	# ANTES del run (el row ya está en la DB cuando la UI dice "Iniciando…") y
	# persiste el complete post-run best-effort — nunca corre dentro del thread
	# (asyncio.run no es seguro allí). ``prestarted_ids`` estampa el id en cada
	# registro (la pipeline lo anexa) para completar la MISMA fila.
	prestarted_ids = await _prestart_agent_sessions(
		fastapi_request,
		tools=request.tools,
		message_id=request.message_id,
		conversation_id=conversation_id,
		tenant_id=UUID(str(tenant_id)) if tenant_id else None,
		profile_id=request.profile_id,
	)
	result = await asyncio.to_thread(
		_handle_selected_tools_pipeline,
		cuit,
		request.tools,
		lambda _msg: None,  # sin superficie de progreso en el flujo no-stream
		conversation_id=conversation_id,
		message_id=request.message_id,
		profile_id=request.profile_id,
		tenant_id=UUID(str(tenant_id)) if tenant_id else None,
		prestarted_ids=prestarted_ids,
	)
	# Telemetría agent_sessions (AST-2/3, ADR-3): persist POST-run best-effort —
	# completa la fila pre-initada (agent_session_id) o inserta completa si no
	# había (fallback); cada registro ya trae todo su contexto.
	for _row in result.get('sessions', []):
		await _persist_agent_session(fastapi_request, **_row)
	reply = result['reply']
	await _append_and_persist(
		fastapi_request,
		conversation_id,
		message,
		reply,
		tenant_id,
		store,
		profile_id=request.profile_id,
	)
	return ChatResponse(
		conversation_id=conversation_id,
		reply=reply,
		actions_taken=result['actions_taken'],
		data=result['data'],
	)


async def _chat_multi_tool_stream(
	request: ChatRequest,
	fastapi_request: Request,
	cuit: str | None,
	conversation_id: str,
	tenant_id: object | None,
	store: RedisStore | None,
	message: str,
) -> StreamingResponse:
	"""SSE del pipeline consolidado multi-tool (mismo contrato que el wizard)."""
	headers = {'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no'}

	if not cuit:
		reply = 'Por favor, proporcioná un CUIT válido para realizar la consulta.'
		await _append_and_persist(
			fastapi_request,
			conversation_id,
			message,
			reply,
			tenant_id,
			store,
			profile_id=request.profile_id,
		)
		return StreamingResponse(_iter_sse_early(conversation_id, reply), media_type='text/event-stream', headers=headers)

	# La fila de la conversación queda en Postgres ANTES de que el pipeline
	# corra (status 'running') para que el sidebar la muestre al instante;
	# el upsert post-run (status 'done') completa la MISMA fila.
	await _persist_conversation_start(
		fastapi_request, conversation_id, message, request.profile_id
	)

	queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
	_loop = asyncio.get_running_loop()
	_progress_messages: list[str] = []

	def _progress(msg: str) -> None:
		_progress_messages.append(msg)
		_loop.call_soon_threadsafe(queue.put_nowait, ('progress', msg))

	async def _run():
		try:
			# Telemetría agent_sessions (AST-2/3, ADR-3): pre-inicia las filas
			# running ANTES de correr el pipeline (el row ya está en la DB cuando
			# la UI dice "Iniciando…"); cada registro estampa su id (la pipeline
			# lo anexa via ``prestarted_ids``) para completar la MISMA fila.
			prestarted_ids = await _prestart_agent_sessions(
				fastapi_request,
				tools=request.tools,
				message_id=request.message_id,
				conversation_id=conversation_id,
				tenant_id=UUID(str(tenant_id)) if tenant_id else None,
				profile_id=request.profile_id,
			)
			result = await asyncio.to_thread(
				_handle_selected_tools_pipeline,
				cuit,
				request.tools,
				_progress,
				conversation_id=conversation_id,
				message_id=request.message_id,
				profile_id=request.profile_id,
				tenant_id=UUID(str(tenant_id)) if tenant_id else None,
				prestarted_ids=prestarted_ids,
			)
			reply = result['reply']
			# Telemetría agent_sessions (AST-2/3, ADR-3): persist POST-run desde
			# el loop async (nunca dentro del thread); _persist_agent_session
			# traga sus propios fallos → el SSE no se rompe.
			for _row in result.get('sessions', []):
				await _persist_agent_session(fastapi_request, **_row)
			await _append_and_persist(
				fastapi_request,
				conversation_id,
				message,
				reply,
				tenant_id,
				store,
				profile_id=request.profile_id,
			)
			complete_payload: dict[str, Any] = {
				'reply': reply,
				'data': result['data'],
				'actions_taken': result['actions_taken'],
				'conversation_id': conversation_id,
			}
			if _progress_messages:
				complete_payload['pipeline_steps'] = list(_progress_messages)
			await queue.put(('complete', complete_payload))
		except Exception as exc:
			reply = f'Ocurrió un error al ejecutar las herramientas: {exc}'
			await _append_and_persist(
				fastapi_request,
				conversation_id,
				message,
				reply,
				tenant_id,
				store,
				profile_id=request.profile_id,
			)
			await queue.put(('complete', {'reply': reply, 'data': None, 'conversation_id': conversation_id}))

	async def _generate():
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

	return StreamingResponse(_generate(), media_type='text/event-stream', headers=headers)


# ── Wizard endpoint ─────────────────────────────────────────────────────


def _descubrir_cliente_desde_padron(cuit: str) -> dict | None:
	"""Discover client info from padrón A5. Returns dict or None."""
	from agente_fiscal.api.deps import REPRESENTANTE_CUIT, get_ta
	from agente_fiscal.domain.models import ClientConfig
	from agente_fiscal.pipeline.service import _completar_cliente_desde_padron

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

	from agente_fiscal.api.deps import REPRESENTANTE_CUIT, get_ta

	cuit = request.cuit
	tasks = request.tasks
	conversation_id = request.conversation_id or str(uuid.uuid4())
	_tenant_id = getattr(fastapi_request.state, 'tenant_id', None)

	# ── Helper: validar CUIT ───────────────────────────────────────────
	def _cuit_valido(raw: str) -> bool:
		import re

		return bool(re.fullmatch(r'\d{11}', raw.strip()))

	# ── Helper: buscar cliente en YAML ─────────────────────────────────
	def _buscar_en_yaml(cuit_raw: str) -> dict | None:
		from pathlib import Path
		import yaml
		from agente_fiscal.domain.models import AppConfig

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
		from agente_fiscal.adapters.arca_ws import get_ta, get_ta_error

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

	# ── Case 2b: active-profile invariant (report generation requires an ACTIVE profile) ──
	report_ctx = await _resolve_active_profile(fastapi_request, request.profile_id)
	from datetime import datetime

	_chat_now = datetime.utcnow()
	chat_mes, chat_anio = _chat_now.month, _chat_now.year

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
			# AST-2/3: UNA fila de telemetría para la corrida consolidada del
			# wizard. Fecha de dispatch/retorno alrededor del pipeline (ADR-3);
			# status derivado del resultado (None o ``error`` → 'error'). El row
			# se pre-inicia con status 'running' ANTES del run (la UI muestra
			# "Iniciando un chat…" en ese mismo dispatch) y se completa post-run.
			_wiz_sid = await _persist_agent_session_start(
				fastapi_request,
				tool='informefiscal',
				message_id=None,
				conversation_id=conversation_id,
				tenant_id=UUID(str(_tenant_id)) if _tenant_id else None,
				profile_id=request.profile_id,
			)
			# La fila de la conversación queda en Postgres ANTES de que el
			# pipeline corra (status 'running') para que el sidebar la muestre
			# al instante; el upsert post-run (status 'done') completa la MISMA
			# fila (idempotente por role/content — nunca duplica el mensaje).
			await _persist_conversation_start(
				fastapi_request,
				conversation_id,
				f'Generar reporte fiscal para CUIT {cuit}',
				request.profile_id,
			)
			_wiz_started = datetime.now(timezone.utc)
			data = await asyncio.to_thread(_handle_wizard_pipeline, cuit, tasks, _progress, request.send_email)
			_wiz_completed = datetime.now(timezone.utc)
			_wiz_status = 'error' if (data is None or data.get('error')) else 'completed'
			await _persist_agent_session(
				fastapi_request,
				tool='informefiscal',
				agent_session_id=_wiz_sid,
				message_id=None,
				conversation_id=conversation_id,
				tenant_id=UUID(str(_tenant_id)) if _tenant_id else None,
				profile_id=request.profile_id,
				status=_wiz_status,
				tasks=build_session_tasks('informefiscal', _wiz_status),
				started_at=_wiz_started,
				completed_at=_wiz_completed,
			)
			from agente_fiscal.domain.response_builder import format_reporte_response

			if data is None:
				from agente_fiscal.adapters.arca_ws import get_ta_error

				reply = format_reporte_response(data, cuit, arca_error=get_ta_error())
			else:
				reply = format_reporte_response(data, cuit)
			report_run_id = await _persist_chat_report_run(
				fastapi_request,
				ctx=report_ctx,
				cuit=cuit,
				data=data,
				progress_msgs=_progress_messages,
				mes=chat_mes,
				anio=chat_anio,
			)
			if report_run_id and data and data.get('pdf_path'):
				await _persist_chat_pdf(fastapi_request, report_run_id, str(data['pdf_path']))
			pdf_url = None
			if data and data.get('pdf_path'):
				# Extract filename for download URL
				# and ensure pdf_path is a string (not PosixPath) for JSON serialization
				import os

				data['pdf_path'] = str(data['pdf_path'])
				filename = os.path.basename(data['pdf_path'])
				pdf_url = f'/v1/chat/reports/{filename}'
			await _persist_conversation(
				fastapi_request,
				conversation_id,
				[
					{'role': 'user', 'content': f'Generar reporte fiscal para CUIT {cuit}'},
					{'role': 'assistant', 'content': reply},
				],
				profile_id=request.profile_id,
				status='done',
			)
			complete_payload: dict[str, Any] = {
				'reply': reply,
				'data': data,
				'pdf_url': pdf_url,
				'conversation_id': conversation_id,
			}
			if report_run_id:
				complete_payload['report_run_id'] = report_run_id
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
	message_id = request.message_id
	tenant_id = getattr(fastapi_request.state, 'tenant_id', None)
	store: RedisStore | None = getattr(fastapi_request.app.state, 'store', None)

	# Prep history as multi-turn context
	context = message
	if request.history:
		history_text = '\n'.join(m['content'] for m in request.history if m.get('content'))
		context = f'{history_text}\n{message}'

	# 1. Detect intent + extract CUIT (with history context)
	intent, cuit, _params = detect(context)

	# 1b. Explicit multi-tool request: bypass detect() — run a consolidated pipeline.
	if request.tools:
		return await _chat_multi_tool_stream(
			request,
			fastapi_request,
			cuit,
			conversation_id,
			tenant_id,
			store,
			message,
		)

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
		await _persist_conversation(
			fastapi_request,
			conversation_id,
			[
				{'role': 'user', 'content': message},
				{'role': 'assistant', 'content': reply},
			],
			profile_id=request.profile_id,
			status='done',
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
		await _persist_conversation(
			fastapi_request,
			conversation_id,
			[
				{'role': 'user', 'content': message},
				{'role': 'assistant', 'content': reply},
			],
			profile_id=request.profile_id,
			status='done',
		)
		return StreamingResponse(
			_iter_sse_early(conversation_id, reply),
			media_type='text/event-stream',
			headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
		)

	tool_key = INTENT_TO_KEY.get(intent)
	if tool_key is not None:
		# ── Streaming genérico de browser tools (ToolSpec dispatch) ──────
		# Emite `conversation_start` → `progress*` → (`live_url` + `agent_step`
		# solo con sesión Composio viva) → (`task_update` con métricas reales del
		# run Browserbase) → `complete`. Reusa el mismo framing SSE que
		# REPORTE_COMPLETO; engines deterministas (consultaarca /
		# calendariovencimientosarca) no emiten live_url/agent_step.
		spec = TOOL_SPECS[tool_key]
		queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
		_loop = asyncio.get_running_loop()
		_progress_messages: list[str] = []

		# ── Reuso de sesión Browserbase: store + acquire ANTES de correr ──
		# El store es opcional y NUNCA rompe la tool: si no hay factory, el
		# acquire falla o el reuso está deshabilitado, se sigue como antes
		# (run efímero sin contexto persistido).
		session_store: object | None = None
		binding: object | None = None
		if spec.needs_browser:
			from agente_fiscal.adapters.db_browser_sessions import PostgresBrowserSessionsRepository
			from agente_fiscal.config import get_settings as _get_browser_settings

			_browser_cfg = _get_browser_settings()
			_factory = getattr(fastapi_request.app.state, 'session_factory', None)
			if _factory is not None and tenant_id and getattr(_browser_cfg, 'browser_session_reuse', True):
				try:
					session_store = PostgresBrowserSessionsRepository(_factory)
					_tenant_uuid = uuid.UUID(str(tenant_id))
					_profile_uuid = request.profile_id
					binding = await session_store.acquire(
						_tenant_uuid,
						_profile_uuid,
						provider='browserbase',
					)
				except Exception as exc:
					logger.warning('Reuso de sesión browser no disponible: %s', exc)
					session_store = None
					binding = None

		def _progress(msg: str) -> None:
			_progress_messages.append(msg)
			_loop.call_soon_threadsafe(queue.put_nowait, ('progress', msg))

		def _on_live_url(url: str) -> None:
			_loop.call_soon_threadsafe(queue.put_nowait, ('live_url', url))

		def _on_step(step, goal, url, status='running'):
			_loop.call_soon_threadsafe(queue.put_nowait, ('agent_step', {'step': step, 'goal': goal, 'url': url, 'status': status}))

		def _on_task_metrics(metrics: dict) -> None:
			# Síncrono (corre en to_thread): actualiza el holder last-write y
			# solo encola; el persist async se hace en _generate_tool cuando
			# drena el evento 'task_metrics'.
			_last_metrics.update(metrics)  # thread-safe last-write holder (ADR-3)
			_loop.call_soon_threadsafe(queue.put_nowait, ('task_metrics', metrics))

		async def _persist_task_metrics(metrics: dict) -> None:
			"""Persiste la sesión real del run (create si fue efímera, release si
			se reusó un binding) desde el loop async. Nunca rompe el stream."""
			if session_store is None:
				return
			from agente_fiscal.config import get_settings as _get_browser_settings
			from datetime import datetime as _dt, timedelta as _td, timezone as _tz

			_ttl = getattr(_get_browser_settings(), 'browser_session_ttl_seconds', 3600)
			_now = _dt.now(_tz.utc)
			_expires_at = _now + _td(seconds=_ttl) if _ttl else None
			_context_id = (metrics.get('context_id') or '').strip() or None
			_session_id = (metrics.get('session_id') or '').strip() or None
			try:
				if binding is not None:
					await session_store.release(
						id=uuid.UUID(str(binding.id)),
						context_id=_context_id,
						session_id=_session_id,
						proxy_bytes=metrics.get('proxy_bytes'),
						duration_ms=metrics.get('duration_ms'),
						cost_cents=metrics.get('cost_cents') or 0,
						started_at=_dt.fromisoformat(metrics['started_at']) if metrics.get('started_at') else _now,
						ended_at=_dt.fromisoformat(metrics['ended_at']) if metrics.get('ended_at') else _now,
						last_used_at=_now,
						expires_at=_expires_at,
					)
				elif _context_id:
					await session_store.create(
						tenant_id=uuid.UUID(str(tenant_id)),
						profile_id=request.profile_id,
						provider='browserbase',
						context_id=_context_id,
						expires_at=_expires_at,
					)
			except Exception as exc:
				logger.warning('No se pudo persistir la sesión de browser: %s', exc)

		# Thread-safe last-write holder para métricas del provider (Browserbase):
		# el callback corre en el hilo del to_thread; el run se lee post-dispatch.
		_last_metrics: dict[str, Any] = {}

		async def _run_tool():
			try:
				# ADR-3: started_at captura el dispatch ("Comenzó"); completed_at
				# se mide al retornar → duración = round-trip del tool run.
				# Alias local: chat_message_stream enlaza SU PROPIO 'datetime'
				# (rama REPORTE_COMPLETO) — un closure sobre esa local no asociada
				# crashea con 'free variable not found' si la rama no corrió.
				from datetime import datetime as _dt_run, timezone as _tz_run

				started_at = _dt_run.now(_tz_run.utc)
				if spec.needs_browser:
					data = await asyncio.to_thread(
						_run_browser_tool,
						spec,
						cuit,
						_progress,
						_on_live_url,
						_on_step,
						session_store=session_store,
						binding=binding,
						on_task_metrics=_on_task_metrics,
					)
				else:
					data = await asyncio.to_thread(_run_engine_tool, spec, cuit, _progress)
				completed_at = _dt_run.now(_tz_run.utc)
				# AST-2: una fila por run, status completed|error desde el dict.
				_run_status = 'error' if (data and data.get('error')) else 'completed'
				_tool_key = spec.tool_key or spec.tool_name
				# Browser: session_id real del provider (last-write holder);
				# engine: sin sesión (NULL, AST-3). Tasks: métricas reales si el
				# provider las dio, si no el template DEFAULT (7 para consultaarca).
				_browser_session_id = (
					(_last_metrics.get('session_id') or '').strip() or None
					if spec.needs_browser
					else None
				)
				_metric_tasks = _last_metrics.get('tasks') or []
				_tasks = build_session_tasks(
					_tool_key,
					_run_status,
					count=len(_metric_tasks) if _metric_tasks else None,
				)
				_cost = int(_last_metrics.get('cost_cents') or 0) if spec.needs_browser else 0
				reply = _resolve_formatter(spec.formatter_name)(data, cuit)
				safe_data = _json_safe(data)
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
				# Persistencia en Postgres: la conversación queda 'done' al
				# emitir complete (la DB nunca rompe el streaming).
				await _persist_conversation(
					fastapi_request,
					conversation_id,
					[
						{'role': 'user', 'content': message},
						{'role': 'assistant', 'content': reply},
					],
					profile_id=request.profile_id,
					status='done',
				)
				# Telemetría agent_sessions (AST-2/3, ADR-3): persist POST-run,
				# best-effort — la DB nunca rompe el SSE.
				await _persist_agent_session(
					fastapi_request,
					tool=_tool_key,
					message_id=message_id,
					conversation_id=conversation_id,
					tenant_id=UUID(str(tenant_id)) if tenant_id else None,
					profile_id=request.profile_id,
					status=_run_status,
					tasks=_tasks,
					cost_cents=_cost,
					session_id=_browser_session_id,
					started_at=started_at,
					completed_at=completed_at,
				)
				complete_payload: dict[str, Any] = {'reply': reply, 'data': safe_data, 'conversation_id': conversation_id}
				# Mismo canal FIFO que progress/live_url/agent_step (call_soon_threadsafe):
				# si el hilo del worker dejó progresos en cola, el loop los drena
				# ANTES del complete (ver race fix en test_chat_stream 6.1).
				_loop.call_soon_threadsafe(queue.put_nowait, ('complete', complete_payload))
			except Exception as exc:
				_loop.call_soon_threadsafe(
					queue.put_nowait,
					(
						'complete',
						{'reply': f'Ocurrió un error al consultar {spec.tool_name}: {exc}', 'data': None, 'conversation_id': conversation_id},
					),
				)

		async def _generate_tool():
			yield f'event: conversation_start\ndata: {json.dumps({"conversation_id": conversation_id})}\n\n'
			task = asyncio.create_task(_run_tool())
			while True:
				event_type, payload = await queue.get()
				if event_type == 'progress':
					yield f'event: progress\ndata: {json.dumps({"message": payload})}\n\n'
				elif event_type == 'live_url':
					yield f'event: live_url\ndata: {json.dumps({"url": payload})}\n\n'
				elif event_type == 'agent_step':
					yield f'event: agent_step\ndata: {json.dumps(payload)}\n\n'
				elif event_type == 'task_metrics':
					# Metadatos del run terminado: persiste la sesión (async) y
					# emite el evento task_update con las métricas REALES.
					await _persist_task_metrics(payload)
					yield f'event: task_update\ndata: {json.dumps({
						'status': 'finished',
						'durationMs': payload.get('duration_ms') or 0,
						'costCents': payload.get('cost_cents') or 0,
						'proxyBytes': payload.get('proxy_bytes') or 0,
						'sessionId': payload.get('session_id') or '',
						'contextId': payload.get('context_id') or '',
					})}\n\n'
				elif event_type == 'complete':
					yield f'event: complete\ndata: {json.dumps(payload)}\n\n'
					break
			await task

		# La fila de la conversación queda en Postgres ANTES de que la tool
		# corra (status 'running') para que el sidebar la muestre al instante;
		# el upsert post-run (status 'done') completa la MISMA fila.
		await _persist_conversation_start(
			fastapi_request, conversation_id, message, request.profile_id
		)

		return StreamingResponse(
			_generate_tool(),
			media_type='text/event-stream',
			headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no'},
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
		await _persist_conversation(
			fastapi_request,
			conversation_id,
			[
				{'role': 'user', 'content': message},
				{'role': 'assistant', 'content': reply},
			],
			profile_id=request.profile_id,
			status='done',
		)
		return StreamingResponse(
			_iter_sse_early(conversation_id, reply),
			media_type='text/event-stream',
			headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
		)

	# 3b. Active-profile invariant gate (report generation requires an ACTIVE profile).
	report_ctx = await _resolve_active_profile(fastapi_request, request.profile_id)
	from datetime import datetime

	_chat_now = datetime.utcnow()
	chat_mes, chat_anio = _chat_now.month, _chat_now.year

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
			report_run_id = await _persist_chat_report_run(
				fastapi_request,
				ctx=report_ctx,
				cuit=cuit,
				data=data,
				progress_msgs=_progress_messages,
				mes=chat_mes,
				anio=chat_anio,
			)
			if report_run_id and data and data.get('pdf_path'):
				await _persist_chat_pdf(fastapi_request, report_run_id, str(data['pdf_path']))
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
			await _persist_conversation(
				fastapi_request,
				conversation_id,
				[
					{'role': 'user', 'content': message},
					{'role': 'assistant', 'content': reply},
				],
				profile_id=request.profile_id,
				status='done',
			)
			# Ensure data is JSON-serializable (e.g. PosixPath → str)
			safe_data: dict[str, Any] | None = None
			if data:
				safe_data = {}
				for k, v in data.items():
					safe_data[k] = str(v) if not isinstance(v, (str, int, float, bool, list, dict, type(None))) else v
			complete_payload: dict[str, Any] = {'reply': reply, 'data': safe_data, 'conversation_id': conversation_id}
			if report_run_id:
				complete_payload['report_run_id'] = report_run_id
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
			await _persist_conversation(
				fastapi_request,
				conversation_id,
				[
					{'role': 'user', 'content': message},
					{'role': 'assistant', 'content': reply},
				],
				profile_id=request.profile_id,
				status='done',
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
	Intent.SISTEMA_REGISTRAL: 'sistemaregistral',
	Intent.DEUDA_VENCIMIENTOS: 'deudavencimientos',
	Intent.MIS_FACILIDADES: 'misfacilidades',
	Intent.RENTAS_CORDOBA: 'rentascordoba',
	Intent.CONSULTA_ARCA: 'consultaarca',
	Intent.CALENDARIO_VENCIMIENTOS_ARCA: 'calendariovencimientosarca',
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

	# La fila de la conversación queda en Postgres ANTES de que la tool/pipeline
	# corra (status 'running') para que el sidebar la muestre al instante; el
	# upsert post-run (status 'done') completa la MISMA fila. Cubre multi-tool
	# (request.tools) y single-intent (TAXPAYER_QUERY, REPORTE_COMPLETO,
	# engines deterministas INTENT_TO_KEY). Los early-returns de no-CUIT y
	# UNKNOWN ya persisten 'done' síncronamente (upsert idempotente: misma fila).
	await _persist_conversation_start(
		fastapi_request, conversation_id, message, request.profile_id
	)

	# 1b. Explicit multi-tool request: bypass detect() — run a consolidated pipeline.
	if request.tools:
		return await _handle_multi_tool_message(
			request,
			fastapi_request,
			cuit,
			conversation_id,
			tenant_id,
			store,
			message,
		)

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
		await _persist_conversation(
			fastapi_request,
			conversation_id,
			[
				{'role': 'user', 'content': message},
				{'role': 'assistant', 'content': reply},
			],
			profile_id=request.profile_id,
			status='done',
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
		await _persist_conversation(
			fastapi_request,
			conversation_id,
			[
				{'role': 'user', 'content': message},
				{'role': 'assistant', 'content': reply},
			],
			profile_id=request.profile_id,
			status='done',
		)
		return ChatResponse(
			conversation_id=conversation_id,
			reply=reply,
			actions_taken=[],
		)

	# 3b. Active-profile invariant gate (report generation requires an ACTIVE profile).
	if intent == Intent.REPORTE_COMPLETO:
		report_ctx = await _resolve_active_profile(fastapi_request, request.profile_id)
		from datetime import datetime

		_chat_now = datetime.utcnow()
		chat_mes, chat_anio = _chat_now.month, _chat_now.year
	else:
		report_ctx = None
		chat_mes, chat_anio = None, None

	# 4. Dispatch to sync handler in thread pool
	action = _ACTION_NAMES.get(intent, 'unknown')

	try:
		if intent == Intent.TAXPAYER_QUERY:
			data = await asyncio.to_thread(_handle_taxpayer, cuit)
			reply = format_taxpayer_response(data, cuit)
		elif intent == Intent.REPORTE_COMPLETO:
			data = await asyncio.to_thread(_handle_reporte, cuit)
			if report_ctx is not None:
				report_run_id = await _persist_chat_report_run(
					fastapi_request,
					ctx=report_ctx,
					cuit=cuit,
					data=data,
					progress_msgs=[],
					mes=chat_mes,
					anio=chat_anio,
				)
				if report_run_id and isinstance(data, dict):
					data['report_run_id'] = report_run_id
					if data.get('pdf_path'):
						await _persist_chat_pdf(fastapi_request, report_run_id, str(data['pdf_path']))
			reply = format_reporte_response(data, cuit)
		elif intent in INTENT_TO_KEY:
			spec = TOOL_SPECS[INTENT_TO_KEY[intent]]
			data = await asyncio.to_thread(_handle_tool_data, spec, cuit)
			reply = _resolve_formatter(spec.formatter_name)(data, cuit)
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
		await _persist_conversation(
			fastapi_request,
			conversation_id,
			[
				{'role': 'user', 'content': message},
				{'role': 'assistant', 'content': reply},
			],
			profile_id=request.profile_id,
			status='done',
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
	await _persist_conversation(
		fastapi_request,
		conversation_id,
		[
			{'role': 'user', 'content': message},
			{'role': 'assistant', 'content': reply},
		],
		profile_id=request.profile_id,
		status='done',
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


# ── Send report by email (mail input flow) ──────────────────────────────────


class SendReportEmailRequest(BaseModel):
	"""Body for ``POST /v1/chat/reports/send`` — user-provided recipient."""

	model_config = ConfigDict(extra='forbid')

	email_address: str = Field(description='Email del destinatario', examples=['ana@acme.io'])
	pdf_path: str = Field(description='Nombre o ruta del archivo PDF del reporte a enviar')


# Local fallback for ``/app/output``: where PdfGenerator writes by default
# (``agente_fiscal/storage/calendarios``), same location the GET download
# endpoint serves from in non-Docker setups.
_REPORTS_STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / 'storage' / 'calendarios'


def _resolve_report_pdf(filename: str) -> Path | None:
	"""Resolve a report PDF filename to an existing file (traversal-safe).

	Only ``Path(filename).name`` is ever used, so absolute paths and ``..``
	can never escape the allowed report directories. Searches ``/app/output``
	first and falls back to ``storage/calendarios`` (mirrors the GET
	``/v1/chat/reports/{filename}`` availability).
	"""
	name = Path(filename).name
	if not name:
		return None
	for base in (REPORTS_DIR, _REPORTS_STORAGE_DIR):
		base_resolved = base.resolve()
		candidate = (base_resolved / name).resolve()
		try:
			candidate.relative_to(base_resolved)
		except ValueError:
			continue
		if candidate.is_file():
			return candidate
	return None


@router.post(
	'/v1/chat/reports/send',
	summary='Enviar reporte PDF por email al destinatario indicado',
)
async def send_report_email(body: SendReportEmailRequest) -> dict[str, object]:
	"""Send an existing report PDF to a user-provided email address via Resend.

	The file must exist under ``/app/output`` or ``storage/calendarios`` (the
	same locations the GET download endpoint resolves). Outbound failures of
	the Resend API are surfaced as structured errors (never propagated as
	exceptions) so the client can display the cause and let the user retry.
	"""
	from datetime import datetime

	from agente_fiscal.adapters.resend_email import ResendEmailSender
	from agente_fiscal.api.routes.clients import _EMAIL_RE, _invalid_email
	from agente_fiscal.config import get_settings
	from agente_fiscal.domain.models import ClientConfig

	if not _EMAIL_RE.fullmatch(body.email_address):
		raise _invalid_email()

	pdf = _resolve_report_pdf(body.pdf_path)
	if pdf is None:
		raise HTTPException(
			status_code=404,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='REPORT_NOT_FOUND', cause='Archivo del reporte no encontrado'),
			).model_dump(),
		)

	settings = get_settings()
	api_key = getattr(settings, 'resend_api_key', '')
	from_addr = getattr(settings, 'email_from', '')
	if not api_key or not from_addr:
		raise HTTPException(
			status_code=503,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='EMAIL_NOT_CONFIGURED', cause='Servicio de email no configurado'),
			).model_dump(),
		)

	sender = ResendEmailSender(api_key=api_key, from_addr=from_addr)
	# ResendEmailSender uses cliente.email (recipient) + cliente.nombre/cuit as
	# name placeholder only; an empty cuit/nombre does not break the send.
	cliente = ClientConfig(cuit='', email=body.email_address)
	now = datetime.utcnow()
	ok = sender.enviar(cliente, pdf, now.month, now.year)
	if not ok:
		raise HTTPException(
			status_code=502,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='EMAIL_SEND_FAILED', cause='El envío del email falló (servicio de email). Intentá de nuevo.'),
			).model_dump(),
		)

	return {'sent': True, 'email': body.email_address}
