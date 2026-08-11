"""Tests for the in-process report worker (``fiscal_agent.worker.runner``).

No external services or real DB are used: the session factory is a lightweight
fake returning a controllable ``AsyncSession``, and both ``get_ta`` and
``PipelineService`` are patched so the only thing under test is the worker's
state-transition logic (``queued -> running -> done/failed``).
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from fiscal_agent.db.models import ReportRun
from fiscal_agent.pipeline.models import PipelineResult
from fiscal_agent.worker.runner import ReportRunner

VALID_CUIT = '20301234561'
MES = 6
ANIO = 2026


def _make_run(status: str = 'queued') -> ReportRun:
	return ReportRun(
		id=uuid.uuid4(),
		tenant_id=uuid.uuid4(),
		cuit=VALID_CUIT,
		status=status,
		steps={'period': {'mes': MES, 'anio': ANIO}},
	)


class FakeSession:
	"""Minimal fake async session: ``get`` returns the run, ``commit`` no-op."""

	def __init__(self, run: ReportRun) -> None:
		self._run = run
		self.commits = 0

	async def __aenter__(self) -> 'FakeSession':
		return self

	async def __aexit__(self, *exc) -> bool:
		return False

	async def get(self, model, pk):
		assert pk == self._run.id
		return self._run

	async def commit(self) -> None:
		self.commits += 1


class FakePipelineService:
	"""Stand-in for ``PipelineService`` with a controllable outcome."""

	result: PipelineResult | None = None
	exc: Exception | None = None

	def __init__(self, engine, pdf_gen, memory_client=None) -> None:
		self.engine = engine
		self.pdf_gen = pdf_gen
		self.memory_client = memory_client

	def run_pipeline(self, *args, **kwargs):
		if FakePipelineService.exc is not None:
			raise FakePipelineService.exc
		return FakePipelineService.result


def _build_runner(run: ReportRun) -> ReportRunner:
	return ReportRunner(
		session_factory=lambda: FakeSession(run),
		engine=MagicMock(),
		pdf_gen=MagicMock(),
		memory_client=None,
	)


@pytest.mark.asyncio
async def test_queued_run_transitions_to_done_with_summary() -> None:
	run = _make_run(status='queued')
	FakePipelineService.result = PipelineResult(cliente='ACME', cuit=VALID_CUIT, pdf=True)
	FakePipelineService.exc = None

	runner = _build_runner(run)
	with (
		patch('fiscal_agent.worker.runner.PipelineService', FakePipelineService),
		patch('fiscal_agent.worker.runner.get_ta', return_value=('token', 'sign')),
	):
		await runner.process_run(run.id)

	assert run.status == 'done'
	assert run.started_at is not None
	assert run.finished_at is not None
	assert run.error is None
	assert run.result_summary is not None
	assert run.result_summary['pdf'] is True
	assert run.result_summary['cuit'] == VALID_CUIT
	# Progress callback must have been exercised by the pipeline.
	assert isinstance((run.steps or {}).get('progress'), list)


@pytest.mark.asyncio
async def test_exception_during_run_transitions_to_failed() -> None:
	run = _make_run(status='queued')
	FakePipelineService.result = None
	FakePipelineService.exc = RuntimeError('ARCA down')

	runner = _build_runner(run)
	with (
		patch('fiscal_agent.worker.runner.PipelineService', FakePipelineService),
		patch('fiscal_agent.worker.runner.get_ta', return_value=('token', 'sign')),
	):
		await runner.process_run(run.id)

	assert run.status == 'failed'
	assert run.finished_at is not None
	assert run.error is not None
	assert run.error['code'] == 'RUN_FAILED'
	assert 'ARCA down' in run.error['cause']


@pytest.mark.asyncio
async def test_ta_unavailable_marks_failed() -> None:
	run = _make_run(status='queued')
	runner = _build_runner(run)
	with (
		patch('fiscal_agent.worker.runner.PipelineService', FakePipelineService),
		patch('fiscal_agent.worker.runner.get_ta', return_value=(None, None)),
	):
		await runner.process_run(run.id)

	assert run.status == 'failed'
	assert run.error is not None
	assert run.error['code'] == 'TA_UNAVAILABLE'
