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
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID

from agente_fiscal.api.profile_gate import ActiveProfileContext, validate_active_profile
from agente_fiscal.api.store import RedisStore
from agente_fiscal.db.models import ReportRun
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
from agente_fiscal.domain.tool_spec import INTENT_TO_KEY, TOOL_SPECS, ToolSpec

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
	from agente_fiscal.config import get_settings
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

	creds = get_settings().credentials
	browser = None
	with_browser = bool(creds.composio_api_key and creds.clave_fiscal)

	if with_browser:
		from agente_fiscal.adapters.browser import ComposioBrowser
		from agente_fiscal.features import IntegrationDisabledError, integration_enabled

		if not integration_enabled('browser'):
			raise IntegrationDisabledError('browser')

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


def _run_browser_tool(
	spec: ToolSpec,
	cuit: str,
	echo_func: Optional[Callable[[str], None]] = None,
	on_live_url: Optional[Callable[[str], None]] = None,
	on_step: Optional[Callable[[int, str, str, str], None]] = None,
) -> dict[str, Any] | None:
	"""Ejecuta una tool de browser (Phase-1) vía ComposioBrowser.

	Generalización de ``_handle_sistemaregistral``: para cualquier ToolSpec con
	``needs_browser=True`` corre ``build_browser_tasks(**spec.task_flags)`` →
	``ComposioBrowser.run_single`` → devuelve el dict de salida para el
	formatter. Mantiene los guards existentes (COMPOSIO_KEY_MISSING /
	INTEGRATION_DISABLED / BROWSER_ERROR).

	``on_live_url`` se invoca en cuanto Composio provisiona la sesión de browser
	(viva), para que el frontend pueda embeberla mientras la automatización corre.
	"""
	from agente_fiscal.api.deps import REPRESENTANTE_CUIT, get_ta
	from agente_fiscal.adapters.browser import ComposioBrowser
	from agente_fiscal.adapters.browser.factory import build_browser_tasks
	from agente_fiscal.config import get_settings
	from agente_fiscal.domain.models import ClientConfig
	from agente_fiscal.features import integration_enabled

	token, sign = get_ta()
	if not token or not sign:
		return None

	creds = get_settings().credentials
	if not creds.composio_api_key or not creds.clave_fiscal:
		return {
			'error': 'COMPOSIO_KEY_MISSING',
			'detail': f'Falta COMPOSIO_API_KEY o ESTUDIO_CLAVE_FISCAL en .env para usar {spec.tool_name}.',
		}
	if not integration_enabled('browser'):
		return {
			'error': 'INTEGRATION_DISABLED',
			'detail': 'La integración de browser (Composio) está deshabilitada (BROWSER_ENABLED=false).',
		}

	browser = ComposioBrowser(
		composio_api_key=creds.composio_api_key,
		estudio_cuit=REPRESENTANTE_CUIT,
		estudio_clave=creds.clave_fiscal,
	)
	try:
		tasks = build_browser_tasks(
			cuit=REPRESENTANTE_CUIT,
			clave=creds.clave_fiscal,
			cliente_cuit=cuit,
			**spec.task_flags,
		)
		out = browser.run_single(
			ClientConfig(cuit=cuit),
			tasks=tasks,
			echo_func=echo_func,
			on_live_url=on_live_url,
			on_step=on_step,
		)
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
	"""
	from datetime import datetime

	from agente_fiscal.api.deps import REPRESENTANTE_CUIT, get_engine, get_ta
	from agente_fiscal.adapters.arca_ws import consultar_cuit

	token, sign = get_ta()
	if not token or not sign:
		return {'error': 'TA_UNAVAILABLE', 'detail': 'No se pudo obtener Ticket de Acceso de ARCA'}

	if echo_func:
		echo_func('  Consultando Padrón A5 ...')
	try:
		result = consultar_cuit(cuit, token, sign, REPRESENTANTE_CUIT)
		output = result.to_output()
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
	from agente_fiscal.config import get_settings
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

	creds = get_settings().credentials
	browser = None
	with_browser = bool(creds.composio_api_key and creds.clave_fiscal)

	if with_browser:
		from agente_fiscal.adapters.browser import ComposioBrowser
		from agente_fiscal.features import IntegrationDisabledError, integration_enabled

		if not integration_enabled('browser'):
			raise IntegrationDisabledError('browser')

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

	from agente_fiscal.api.deps import REPRESENTANTE_CUIT, get_engine, get_memory, get_pdf_gen, get_ta
	from agente_fiscal.cli import _procesar_cliente_pipeline
	from agente_fiscal.config import get_settings
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

	creds = get_settings().credentials
	uses_browser = tasks.deuda or tasks.facilidades or tasks.registro or tasks.iibb
	browser = None

	if uses_browser:
		if not (creds.composio_api_key and creds.clave_fiscal):
			echo_func('  ⚠️  Credenciales de browser no configuradas — algunas tareas no estarán disponibles')
		else:
			from agente_fiscal.adapters.browser import ComposioBrowser
			from agente_fiscal.features import IntegrationDisabledError, integration_enabled

			if not integration_enabled('browser'):
				raise IntegrationDisabledError('browser')

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
			data = await asyncio.to_thread(_handle_wizard_pipeline, cuit, tasks, _progress, request.send_email)
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

	tool_key = INTENT_TO_KEY.get(intent)
	if tool_key is not None:
		# ── Streaming genérico de browser tools (ToolSpec dispatch) ──────
		# Emite `conversation_start` → `progress*` → (`live_url` + `agent_step`
		# solo con sesión Composio viva) → `complete`. Reusa el mismo framing
		# SSE que REPORTE_COMPLETO; engines deterministas (consultaarca /
		# calendariovencimientosarca) no emiten live_url/agent_step.
		spec = TOOL_SPECS[tool_key]
		queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
		_loop = asyncio.get_running_loop()
		_progress_messages: list[str] = []

		def _progress(msg: str) -> None:
			_progress_messages.append(msg)
			_loop.call_soon_threadsafe(queue.put_nowait, ('progress', msg))

		def _on_live_url(url: str) -> None:
			_loop.call_soon_threadsafe(queue.put_nowait, ('live_url', url))

		def _on_step(step, goal, url, status='running'):
			_loop.call_soon_threadsafe(queue.put_nowait, ('agent_step', {'step': step, 'goal': goal, 'url': url, 'status': status}))

		async def _run_tool():
			try:
				if spec.needs_browser:
					data = await asyncio.to_thread(_run_browser_tool, spec, cuit, _progress, _on_live_url, _on_step)
				else:
					data = await asyncio.to_thread(_run_engine_tool, spec, cuit, _progress)
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
				elif event_type == 'complete':
					yield f'event: complete\ndata: {json.dumps(payload)}\n\n'
					break
			await task

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
