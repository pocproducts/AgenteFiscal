"""Core in-process runner that executes queued report runs in the background.

This is the SIMPLE, in-process async worker (no external queue). A single
asyncio task polls ``report_runs`` rows with ``status='queued'``, executes the
full (synchronous) ``PipelineService.run_pipeline`` for each, and updates the
row ``queued -> running -> done/failed`` so a future GET can show live state.

Design notes:
- The heavy ``run_pipeline`` call is blocking/synchronous. It runs inside
  ``asyncio.to_thread`` so it does NOT block the event loop that drives the
  worker, the API, or other concurrent tasks.
- Concurrency is intentionally 1: TA and the Composio browser are single
  session, so runs are never parallelized.
- A fresh scoped session is opened per poll iteration (and per run) to avoid
  long-lived transactions.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agente_fiscal.adapters.arca_ws import get_ta
from agente_fiscal.adapters.browser import ComposioBrowser
from agente_fiscal.config import REPRESENTANTE_CUIT, get_settings
from agente_fiscal.db.models import Client, ReportRun
from agente_fiscal.domain.models import ClientConfig
from agente_fiscal.pipeline.service import PipelineService
from agente_fiscal.telemetry import init_telemetry

logger = logging.getLogger(__name__)

init_telemetry("backend-worker")


class _TaUnavailable(Exception):
	"""Internal sentinel: no Ticket de Acceso could be obtained from ARCA."""


class ReportRunner:
	"""Executes queued ``ReportRun`` rows against the heavy pipeline.

	Accepts the session factory plus the heavy dependencies (rules engine,
	PDF generator, and optional memory client) via constructor injection so it
	can be unit-tested without real external services.
	"""

	def __init__(
		self,
		session_factory: async_sessionmaker[AsyncSession],
		engine,
		pdf_gen,
		memory_client=None,
	) -> None:
		self._session_factory = session_factory
		self._engine = engine
		self._pdf_gen = pdf_gen
		self._memory_client = memory_client

	async def process_run(self, report_run_id: UUID) -> None:
		"""Load one report run, execute its pipeline, and persist the outcome.

		Any exception (including TA/browser issues) is caught and recorded as
		``failed``; the row is always left with ``finished_at`` set.
		"""
		# Open a fresh scoped session for this run so the transaction is short.
		async with self._session_factory() as session:
			run = await session.get(ReportRun, report_run_id)
			if run is None:
				logger.warning('ReportRun %s not found — skipping', report_run_id)
				return

			# ── queued -> running ────────────────────────────────────────────
			run.status = 'running'
			run.started_at = datetime.now(timezone.utc)
			await session.commit()

			steps = dict(run.steps or {})
			progress_msgs: list[str] = []

			try:
				period = steps.get('period') or {}
				mes = int(period.get('mes') or 0)
				anio = int(period.get('anio') or 0)
				flags = steps.get('flags') or {}
				with_deuda = bool(flags.get('with_deuda'))
				with_facilidades = bool(flags.get('with_facilidades'))
				with_registro = bool(flags.get('with_registro'))
				with_iibb = bool(flags.get('with_iibb'))

				if not mes or not anio:
					raise ValueError('missing period in report_runs.steps (mes/anio)')

				# ── TA (shared cache: CLI, API, MCP) ───────────────────────
				token, sign = get_ta()
				if not token or not sign:
					raise _TaUnavailable()

				cliente = await self._build_cliente(session, run)
				browser = self._build_browser(
					with_deuda or with_facilidades or with_registro or with_iibb
				)

				def progress_callback(msg: str) -> None:
					progress_msgs.append(msg)

				svc = PipelineService(self._engine, self._pdf_gen, self._memory_client)
				# run_pipeline is blocking → offload to a thread so the loop stays responsive.
				result = await asyncio.to_thread(
					svc.run_pipeline,
					cliente,
					token,
					sign,
					mes,
					anio,
					browser,
					with_deuda=with_deuda,
					with_facilidades=with_facilidades,
					with_registro=with_registro,
					with_iibb=with_iibb,
					send_email=True,
					progress_callback=progress_callback,
				)

				steps['progress'] = progress_msgs
				run.steps = steps
				if result.error:
					run.status = 'failed'
					run.error = {'code': 'PIPELINE_FAILED', 'cause': result.error}
				else:
					run.status = 'done'
					run.result_summary = result.model_dump()
			except _TaUnavailable:
				steps['progress'] = progress_msgs
				run.steps = steps
				run.status = 'failed'
				run.error = {
					'code': 'TA_UNAVAILABLE',
					'cause': 'No se pudo obtener Ticket de Acceso de ARCA',
					'remediation': 'Verificar certificados en .certificados-arca/',
				}
			except Exception as exc:
				logger.exception('ReportRun %s failed', report_run_id)
				steps['progress'] = progress_msgs
				run.steps = steps
				run.status = 'failed'
				run.error = {'code': 'RUN_FAILED', 'cause': str(exc)}
			finally:
				run.finished_at = datetime.now(timezone.utc)
				await session.commit()

	async def _build_cliente(self, session: AsyncSession, run: ReportRun) -> ClientConfig:
		"""Build the pipeline's ``ClientConfig``, resolving email/nombre from ``clients`` when linked.

		``report_runs.client_id`` is optional (a run may target a bare CUIT with
		no stored client) — email stays empty in that case and the pipeline
		skips sending rather than failing.
		"""
		if run.client_id is None:
			return ClientConfig(cuit=run.cuit)
		client_row = await session.get(Client, run.client_id)
		if client_row is None:
			return ClientConfig(cuit=run.cuit)
		return ClientConfig(cuit=run.cuit, nombre=client_row.name, email=client_row.email or '')

	def _build_browser(self, needed: bool) -> Optional[ComposioBrowser]:
		"""Lazily build the Composio browser only when a flag requires it."""
		if not needed:
			return None
		creds = get_settings().credentials
		composio_key = creds.composio_api_key
		estudio_clave = creds.clave_fiscal
		if not composio_key or not estudio_clave:
			raise RuntimeError('Missing COMPOSIO_API_KEY or ESTUDIO_CLAVE_FISCAL in .env')
		return ComposioBrowser(
			composio_api_key=composio_key,
			estudio_cuit=REPRESENTANTE_CUIT,
			estudio_clave=estudio_clave,
		)

	async def _fetch_next_queued(self) -> Optional[UUID]:
		"""Return the id of the oldest ``queued`` run, or ``None``."""
		async with self._session_factory() as session:
			stmt = (
				select(ReportRun.id)
				.where(ReportRun.status == 'queued')
				.order_by(ReportRun.created_at.asc(), ReportRun.id)
				.limit(1)
			)
			result = await session.execute(stmt)
			row = result.first()
			return row[0] if row else None

	async def run_loop(
		self,
		poll_interval: float = 5.0,
		stop_event: Optional[asyncio.Event] = None,
	) -> None:
		"""Poll for queued runs and process them, one at a time.

		Exits as soon as ``stop_event`` is set.
		"""
		logger.info('ReportRunner loop started (poll_interval=%ss)', poll_interval)
		while stop_event is None or not stop_event.is_set():
			try:
				run_id = await self._fetch_next_queued()
				if run_id is not None:
					logger.info('Processing queued report run %s', run_id)
					await self.process_run(run_id)
			except Exception as exc:
				# Never let a broken iteration kill the worker.
				logger.exception('Worker iteration error: %s', exc)
			await asyncio.sleep(poll_interval)
		logger.info('ReportRunner loop stopped')


async def run_loop(
	poll_interval: float = 5.0,
	stop_event: Optional[asyncio.Event] = None,
) -> None:
	"""Module-level convenience: run the default worker loop until stop.

	Builds a ``ReportRunner`` from the shared engine/PDF/memory deps and the
	app session factory, then polls for queued report runs. Provided so the
	worker can be launched from a script without wiring up dependencies by hand.
	"""
	from agente_fiscal.api.deps import get_engine, get_memory, get_pdf_gen
	from agente_fiscal.db.session import async_session_factory

	runner = ReportRunner(
		session_factory=async_session_factory,
		engine=get_engine(),
		pdf_gen=get_pdf_gen(),
		memory_client=get_memory(),
	)
	await runner.run_loop(poll_interval=poll_interval, stop_event=stop_event)


@asynccontextmanager
async def start_worker(app) -> AsyncIterator[None]:
	"""Plug the worker into the FastAPI lifespan.

	Starts the poll loop as an asyncio task on boot (before ``yield``) and
	cancels it on shutdown (after ``yield``). Uses ``app.state.session_factory``
	so the worker shares the app engine.
	"""
	from agente_fiscal.api.deps import get_engine, get_memory, get_pdf_gen

	session_factory = getattr(app.state, 'session_factory', None)
	if session_factory is None:
		logger.warning('app.state.session_factory not set — worker disabled')
		yield
		return

	runner = ReportRunner(
		session_factory=session_factory,
		engine=get_engine(),
		pdf_gen=get_pdf_gen(),
		memory_client=get_memory(),
	)
	stop_event = asyncio.Event()
	task = asyncio.create_task(runner.run_loop(stop_event=stop_event))
	try:
		yield
	finally:
		stop_event.set()
		try:
			await task
		except asyncio.CancelledError:
			logger.info('Worker task cancelled during shutdown')
