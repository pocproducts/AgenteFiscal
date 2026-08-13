"""Pipeline orchestration service — extracted from CLI for shared use across CLI, API, and MCP.

Replaces the raw pipeline logic in ``_procesar_cliente_pipeline()``
with a tested, injectable ``PipelineService`` class.

Infrastructure dependencies (ARCA WS, email, settings, browser) are injected
as ports; when a port is ``None`` the real adapter is constructed lazily so
existing callers continue to work unchanged.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from agente_fiscal.domain.models import AppConfig, ClientConfig, TipoContribuyente, TipoPersona
from agente_fiscal.domain.rules_engine import RulesEngine
from agente_fiscal.pipeline.models import PipelineResult

logger = logging.getLogger(__name__)


# ── Module-level helpers (moved from cli.py) ──────────────────────────────────────


def _completar_cliente_desde_padron(
	cliente: ClientConfig,
	token: str,
	sign: str,
	representante_cuit: str,
	padron_provider: Optional[Callable[..., object]],
) -> ClientConfig:
	"""Completa campos faltantes de ClientConfig desde Padrón A5.

	Solo consulta el WS si al menos uno de los campos deducibles
	(``nombre``, ``tipo``, ``tipo_persona``, ``cierre_ejercicio``)
	está ausente.
	"""
	if all(
		[
			cliente.nombre,
			cliente.tipo,
			cliente.tipo_persona,
			cliente.cierre_ejercicio,
		]
	):
		return cliente

	result = padron_provider(cliente.cuit, token, sign, representante_cuit)
	output = result.to_output()
	output_dict = result.to_dict()

	if output.errorConstancia:
		raise ValueError(f'Error al consultar CUIT {cliente.cuit}: {"; ".join(output.errorConstancia.error)}')

	nombre = output_dict.get('nombre') or ''
	if not nombre and output.datosGenerales:
		nombre = (
			output.datosGenerales.razonSocial
			or f'{output.datosGenerales.nombre or ""} {output.datosGenerales.apellido or ""}'.strip()
		)
	nombre = nombre or cliente.cuit

	provincia = None
	if output.domicilioFiscal and output.domicilioFiscal.descripcionProvincia:
		provincia = output.domicilioFiscal.descripcionProvincia

	return ClientConfig(
		cuit=cliente.cuit,
		clave_fiscal=cliente.clave_fiscal,
		email=cliente.email,
		nombre=cliente.nombre or nombre,
		tipo=cliente.tipo or TipoContribuyente(output_dict.get('tipo')),
		tipo_persona=cliente.tipo_persona
		or (TipoPersona.fisica if output_dict.get('tipo_persona', '').upper() == 'FISICA' else TipoPersona.juridica),
		cierre_ejercicio=cliente.cierre_ejercicio or output_dict.get('mes_cierre'),
		provincias=(cliente.provincias or ([provincia] if provincia else None)),
	)


def _memory_save_extraction(
	memory_client: object,
	cuit: str,
	extraction_type: str,
	parts: list[str],
) -> None:
	"""Save a browser-extraction summary to Engram memory."""
	data = {
		'extraction_type': extraction_type,
		'has_data': bool(parts),
	}
	status = 'success' if parts else 'no_data'
	memory_client.save_extraction_result(cuit, extraction_type, data, status)


def _derive_iibb_provincia(cliente: ClientConfig) -> str | None:
	"""Deriva provincia para IIBB según provincias configuradas.

	- None/vacío → None (dispara fallback Córdoba en IIBBRouter)
	- 1 provincia → esa provincia
	- 2+ provincias → primera (Convenio Multilateral)
	"""
	if not cliente.provincias:
		return None
	return cliente.provincias[0]


# ── PipelineService ───────────────────────────────────────────────────────────────


class PipelineService:
	"""Pipeline orchestration for a single client.

	Encapsulates the full fiscal pipeline:
	WS API (Padrón A5) → Rules Engine → Browser extraction → PDF → Email.

	Accepts dependencies via constructor injection for testability.
	Infrastructure ports default to real adapters when omitted.
	"""

	def __init__(
		self,
		engine: RulesEngine,
		pdf_gen: object,
		memory_client: object | None = None,
		padron: object | None = None,
		email_sender: object | None = None,
		settings: object | None = None,
	) -> None:
		self._engine = engine
		self._pdf_gen = pdf_gen
		self._memory_client = memory_client
		self._padron = padron
		self._email_sender = email_sender
		self._settings = settings

	# ── Port resolution helpers (lazy real-adapter fallbacks) ────────────────

	def _padron_provider(self) -> Callable[..., object]:
		"""Return the ARCA padron query callable, building the adapter if needed."""
		if self._padron is not None:
			return self._padron
		from agente_fiscal.adapters.arca_ws import consultar_cuit

		return consultar_cuit

	def _settings_obj(self) -> object:
		"""Return the settings port, lazily resolving config when not injected."""
		if self._settings is not None:
			return self._settings
		from agente_fiscal.config import get_settings

		return get_settings()

	def _representante_cuit(self) -> str:
		"""CUIT del representante — from settings port or config fallback."""
		settings = self._settings_obj()
		return getattr(settings, 'representante_cuit', None) or getattr(
			getattr(settings, 'credentials', None), 'cuit', ''
		)

	def _clave_fiscal(self) -> str:
		"""Clave fiscal del estudio — from settings port or config fallback."""
		settings = self._settings_obj()
		return getattr(settings, 'clave_fiscal', None) or getattr(
			getattr(settings, 'credentials', None), 'clave_fiscal', ''
		)

	def _email_sender_obj(self) -> object:
		"""Return a ready-to-use ``EmailSenderPort`` instance.

		Resolves ``ResendEmailSender`` from settings (``RESEND_API_KEY``/
		``EMAIL_FROM``) when nothing was injected — the live default for the
		API/worker paths. Missing config degrades gracefully (the adapter logs
		and returns ``False`` per send, it never raises).
		"""
		if self._email_sender is not None:
			return self._email_sender
		from agente_fiscal.adapters.resend_email import ResendEmailSender

		settings = self._settings_obj()
		return ResendEmailSender(
			api_key=getattr(settings, 'resend_api_key', ''),
			from_addr=getattr(settings, 'email_from', ''),
		)

	def run_pipeline(
		self,
		cliente: ClientConfig,
		token: str,
		sign: str,
		mes: int,
		anio: int,
		browser: Optional[object] = None,
		*,
		with_deuda: bool = False,
		with_facilidades: bool = False,
		with_registro: bool = False,
		with_iibb: bool = False,
		send_email: bool = True,
		config: Optional[AppConfig] = None,
		output_dir: Optional[Path] = None,
		progress_callback: Callable[[str], None] | None = None,
	) -> PipelineResult:
		"""Run the full fiscal pipeline for a single client.

		Mirrors the exact behaviour of ``_procesar_cliente_pipeline()``
		but returns a typed ``PipelineResult`` instead of a raw dict.

		``config`` (``clients.yaml``-derived) no longer drives email — the
		sender is resolved via ``_email_sender_obj()`` (Resend from settings by
		default). Kept in the signature for existing callers (CLI); accepted
		but unused here.
		"""
		if progress_callback is None:
			progress_callback = lambda _: None  # no-op

		resultado = PipelineResult(
			cliente=cliente.nombre or cliente.cuit,
			cuit=cliente.cuit,
		)

		representante_cuit = self._representante_cuit()
		estudio_clave = self._clave_fiscal()
		padron_provider = self._padron_provider()

		try:
			# ── Memory: check recent padron history ─────────────────────────────
			if self._memory_client is not None:
				historial = self._memory_client.get_padron_history(cliente.cuit, limit=1)
				if historial:
					logger.info('[%s] Padron consultado recientemente (%d registro(s))', cliente.cuit, len(historial))
				else:
					logger.info('[%s] Sin historial de padron previo', cliente.cuit)

			# ── WS API ──────────────────────────────────────────────────────────
			progress_callback('  Consultando Padrón A5 ...')
			padron_result = padron_provider(cliente.cuit, token, sign, representante_cuit)
			output = padron_result.to_output()
			resultado.ws_api = True
			if self._memory_client is not None:
				self._memory_client.save_padron_result(cliente.cuit, padron_result.to_dict(), 'success')
			progress_callback(f'  Tipo: {output.datosGenerales.tipoPersona or "N/A"}')

			# ── Auto-complete missing fields from Padrón A5 ────────────────────
			cliente = _completar_cliente_desde_padron(
				cliente,
				token,
				sign,
				representante_cuit,
				padron_provider,
			)
			resultado.cliente = cliente.nombre or cliente.cuit
			if cliente.nombre:
				progress_callback(f'  Nombre: {cliente.nombre}')

			# ── Rules Engine ────────────────────────────────────────────────────
			progress_callback('  Calculando calendario ...')
			calendario = self._engine.calcular(output, mes, anio, provincias=cliente.provincias)
			n = len(calendario.vencimientos)
			resultado.calendario = True
			progress_callback(f'  Vencimientos: {n}')

			if n == 0:
				progress_callback(f'  Sin vencimientos para {cliente.nombre or cliente.cuit} este mes')
				# no early return — las extracciones (deuda, facilidades, registro, IIBB) corren siempre

			# ── Composio Browser (deuda + facilidades) ─────────────────────────
			deuda_output: object = None
			rentas_matching: object = None
			usa_browser_flag = with_deuda or with_facilidades or with_registro or with_iibb

			tasks: list = []
			from agente_fiscal.adapters.browser import FacilidadesTask, IIBBTask, RegistroTask, VencimientosDeudasTask

			if usa_browser_flag and browser is not None:
				if with_deuda:
					tasks.append(
						VencimientosDeudasTask(
							cuit=representante_cuit,
							clave=estudio_clave,
							cliente_cuit=cliente.cuit,
						)
					)
				if with_facilidades:
					tasks.append(
						FacilidadesTask(
							cuit=representante_cuit,
							clave=estudio_clave,
							cliente_cuit=cliente.cuit,
						)
					)
				if with_registro:
					tasks.append(
						RegistroTask(
							cuit=representante_cuit,
							clave=estudio_clave,
							cliente_cuit=cliente.cuit,
						)
					)
				if with_iibb:
					provincia_iibb = _derive_iibb_provincia(cliente)
					tasks.append(
						IIBBTask(
							cuit=representante_cuit,
							clave=estudio_clave,
							cliente_cuit=cliente.cuit,
							provincia=provincia_iibb or 'CORDOBA',
						)
					)

			if tasks and browser is not None:
				progress_callback(f'  Extrayendo vía Composio ({len(tasks)} task(s)) ...')
				deuda_output = browser.run_single(cliente, tasks=tasks, echo_func=progress_callback)
				parts: list[str] = []
				if deuda_output.error:
					error_tag = 'TIMEOUT' if 'Timeout' in deuda_output.error else 'ERROR'
					progress_callback(f'  ⚠️  Composio: {error_tag} — {deuda_output.error}')
					logger.info('[%s] Composio: %s', cliente.cuit, error_tag)
				if deuda_output.saldos or deuda_output.deudas:
					parts.append(f'{len(deuda_output.deudas)} deudas')
				if deuda_output.facilidades:
					parts.append(f'{len(deuda_output.facilidades)} planes')
				if deuda_output.registro:
					r = deuda_output.registro
					dom_count = len(r.domicilios)
					act_count = len(r.actividades)
					imp_count = len(r.impuestos)
					pv_count = len(r.puntos_de_venta)
					parts.append(f'{dom_count} domicilios, {act_count} actividades, {imp_count} impuestos, {pv_count} PV')

				# Memory: record extraction results per type
				if self._memory_client is not None:
					if with_deuda:
						_memory_save_extraction(self._memory_client, cliente.cuit, 'deuda', parts)
					if with_facilidades:
						_memory_save_extraction(self._memory_client, cliente.cuit, 'facilidades', parts)
					if with_registro:
						_memory_save_extraction(self._memory_client, cliente.cuit, 'registro', parts)
					if with_iibb:
						_memory_save_extraction(self._memory_client, cliente.cuit, 'iibb', parts)

				detalle = ', '.join(parts) if parts else 'OK'
				progress_callback(f'  ✅ Composio: {detalle}')
				logger.info('[%s] Composio: OK', cliente.cuit)

			# ── Determinar si browser falló ──────────────────────────────────
			browser_failed = deuda_output is not None and bool(deuda_output.error)
			if browser_failed:
				resultado.error = f'Error de extracción: {deuda_output.error}'

			# ── Rentas Córdoba Matching ──────────────────────────────────────────
			if deuda_output is not None and not browser_failed:
				from agente_fiscal.domain.matching import evaluar_rentas_cordoba

				rentas_matching = evaluar_rentas_cordoba(
					provincias=cliente.provincias,
					impuestos_ws=output.regimenGeneral.impuestos if output.regimenGeneral else None,
					registro_impuestos=deuda_output.registro.impuestos if deuda_output.registro else None,
				)
				if rentas_matching.requiere_integracion:
					progress_callback('  🔗 Matching: Rentas Córdoba (en desarrollo)')

			# ── PDF (solo si no hubo error de browser) ───────────────────────────
			if not browser_failed:
				progress_callback('  Generando PDF ...')
				pdf_path = self._pdf_gen.generar(
					cliente.nombre,
					cliente.cuit,
					calendario.vencimientos,
					mes,
					anio,
					observaciones=calendario.observaciones or None,
					deuda=deuda_output,
					rentas_matching=rentas_matching,
					output_dir=output_dir,
				)
				resultado.pdf = True
				resultado.pdf_path = pdf_path
				if self._memory_client is not None:
					self._memory_client.save_pdf_sent(cliente.cuit, str(pdf_path), '', 'generated')
				progress_callback(f'  PDF: {pdf_path}')
			else:
				deuda_error = deuda_output.error if deuda_output else ''
				progress_callback(f'  ⚠️  Browser: salteando PDF (error en extracción — {deuda_error})')

			# ── Email (solo si hay PDF generado) ─────────────────────────────────
			if not browser_failed and send_email:
				if not cliente.email:
					progress_callback('  ⚠️  Sin email configurado — salteando envío')
				else:
					progress_callback(f'  Enviando email a {cliente.email} ...')
					sender = self._email_sender_obj()
					ok = sender.enviar(cliente, pdf_path, mes, anio)
					resultado.email = ok
					if self._memory_client is not None:
						self._memory_client.save_pdf_sent(cliente.cuit, str(pdf_path), cliente.email, 'sent' if ok else 'failed')
					progress_callback(f'  Email: {"✅" if ok else "❌"}')
			elif not browser_failed:
				progress_callback('  Email: omitido (--no-send)')
			else:
				progress_callback('  Email: omitido (error en extracción)')

			# ── Build pdf_preview markdown ────────────────────────────────────
			try:
				preview_lines: list[str] = []
				preview_lines.append(f'# Reporte Fiscal — {cliente.nombre or cliente.cuit}')
				preview_lines.append('')
				preview_lines.append('---')
				preview_lines.append('')
				preview_lines.append('## Datos del Contribuyente')
				preview_lines.append('')
				preview_lines.append(f'| Campo | Valor |')
				preview_lines.append(f'|-------|-------|')
				preview_lines.append(f'| **CUIT** | `{cliente.cuit}` |')
				preview_lines.append(f'| **Razón Social** | {cliente.nombre or "—"} |')
				preview_lines.append(f'| **Tipo** | {cliente.tipo.value if cliente.tipo else "—"} |')
				preview_lines.append(f'| **Tipo Persona** | {cliente.tipo_persona.value if cliente.tipo_persona else "—"} |')
				if cliente.cierre_ejercicio:
					preview_lines.append(f'| **Cierre Ejercicio** | {cliente.cierre_ejercicio} |')
				if cliente.provincias:
					preview_lines.append(f'| **Provincias** | {", ".join(cliente.provincias)} |')
				preview_lines.append('')
				preview_lines.append('---')
				preview_lines.append('')

				# Calendario
				preview_lines.append('## Calendario Fiscal')
				preview_lines.append('')
				n = len(calendario.vencimientos)
				if n > 0:
					preview_lines.append(f'**{n} vencimiento(s) para {mes}/{anio}**')
					preview_lines.append('')
					for v in calendario.vencimientos:
						preview_lines.append(f'- **{v.impuesto}** — Vence: {v.fecha_vencimiento}')
						if v.observacion:
							preview_lines.append(f'  - {v.observacion}')
				else:
					preview_lines.append('*Sin vencimientos este mes*')
				preview_lines.append('')

				# Extracciones Composio
				if deuda_output:
					preview_lines.append('---')
					preview_lines.append('')
					preview_lines.append('## Extracciones Realizadas')
					preview_lines.append('')
					if deuda_output.saldos or deuda_output.deudas:
						preview_lines.append(f'**Deuda ARCA:** {len(deuda_output.deudas)} deuda(s) detectada(s)')
						preview_lines.append('')
					if deuda_output.facilidades:
						preview_lines.append(f'**Planes de Pago:** {len(deuda_output.facilidades)} plan(es) activo(s)')
						preview_lines.append('')
					if deuda_output.registro:
						r = deuda_output.registro
						preview_lines.append(f'**Registro Tributario:** {len(r.domicilios)} domicilio(s), {len(r.actividades)} actividad(es), {len(r.impuestos)} impuesto(s)')
						preview_lines.append('')

				# PDF
				if resultado.pdf and resultado.pdf_path:
					preview_lines.append('---')
					preview_lines.append('')
					preview_lines.append('✅ **PDF generado exitosamente**')
					preview_lines.append(f'📄 `{resultado.pdf_path}`')
					preview_lines.append('')

				resultado.pdf_preview = '\n'.join(preview_lines)
			except Exception:
				pass  # pdf_preview es best-effort

		except Exception as exc:
			resultado.error = str(exc)
			if self._memory_client is not None:
				self._memory_client.save_pipeline_error(cliente.cuit, 'pipeline', str(exc))
			progress_callback(f'  ❌ Error: {exc}')

		return resultado