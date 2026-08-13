"""Tests for ``agente_fiscal.worker.runner.ReportRunner``.

The state machine persists its transitions on the REAL test Postgres
(``report_runs`` rows), while every external dependency — ``get_ta``,
``PipelineService`` and the settings used by ``_build_browser`` — is patched.
"""

from __future__ import annotations

import asyncio
import sys
import types
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from agente_fiscal.worker import runner as runner_mod
from agente_fiscal.adapters.browser import ComposioBrowser
from agente_fiscal.db.models import ReportRun
from agente_fiscal.domain.models import ClientConfig
from agente_fiscal.pipeline.models import PipelineResult, ProposalOutcome
from agente_fiscal.worker.runner import ReportRunner, start_worker

pytestmark = pytest.mark.usefixtures('db_reset')

CUIT = '20301234561'
_STEPS = {'period': {'mes': 6, 'anio': 2026}}


def _make_runner(test_session_factory) -> ReportRunner:
    return ReportRunner(
        session_factory=test_session_factory,
        engine=MagicMock(),
        pdf_gen=MagicMock(),
        memory_client=None,
    )


def _settings(arca: bool = True, browser: bool = False) -> SimpleNamespace:
    """Settings stand-in exposing the feature-flag attributes."""
    return SimpleNamespace(
        arca_enabled=arca,
        browser_enabled=browser,
        pdf_enabled=True,
        credentials=SimpleNamespace(composio_api_key='', clave_fiscal=''),
    )


def _pipeline_fake(
    result: PipelineResult | None = None,
    exc: Exception | None = None,
    pending_actions: list[str] | None = None,
):
    """A stand-in for PipelineService whose proposal/execution phases are
    deterministic (mirrors the real two-phase API the worker calls)."""

    class FakePipelineService:
        def __init__(self, engine, pdf_gen, memory_client=None):
            self.engine = engine
            self.pdf_gen = pdf_gen
            self.memory_client = memory_client

        def run_proposal(self, *args, progress_callback=None, **kwargs):
            if progress_callback:
                progress_callback('mock step 1')
                progress_callback('mock step 2')
            if exc is not None:
                raise exc
            return ProposalOutcome(
                result=result, pending_actions=list(pending_actions or [])
            )

        def execute_actions(self, *args, actions=None, progress_callback=None, **kwargs):
            if progress_callback:
                progress_callback('mock resume step')
            if exc is not None:
                raise exc
            return result

    return FakePipelineService


async def _insert_run(
    test_session_factory,
    tenant_id,
    *,
    cuit: str = CUIT,
    status: str = 'queued',
    steps: dict | None = None,
    client_id=None,
    created_at=None,
) -> ReportRun:
    async with test_session_factory() as session:
        run = ReportRun(
            tenant_id=tenant_id,
            client_id=client_id,
            cuit=cuit,
            status=status,
            steps=steps or {},
        )
        if created_at is not None:
            run.created_at = created_at
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run


async def _get_run(test_session_factory, run_id):
    async with test_session_factory() as session:
        return await session.get(ReportRun, run_id)


# ─── process_run: queued -> running -> done ─────────────────────────────────


async def test_process_run_happy_path(test_session_factory, make_tenant, monkeypatch) -> None:
    monkeypatch.setattr(runner_mod, 'get_settings', lambda: _settings(arca=True))
    monkeypatch.setattr(runner_mod, 'get_ta', lambda *a, **k: ('tok', 'sign'))
    monkeypatch.setattr(
        runner_mod, 'PipelineService', _pipeline_fake(result=PipelineResult(cliente='Acme', cuit=CUIT))
    )
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(test_session_factory, tenant.id, steps=dict(_STEPS))
    assert run.started_at is None and run.finished_at is None

    runner = _make_runner(test_session_factory)
    await runner.process_run(run.id)

    persisted = await _get_run(test_session_factory, run.id)
    assert persisted.status == 'done'
    assert persisted.started_at is not None
    assert persisted.finished_at is not None
    assert persisted.error is None
    assert persisted.result_summary == PipelineResult(
        cliente='Acme', cuit=CUIT
    ).model_dump()
    assert persisted.steps['period'] == {'mes': 6, 'anio': 2026}
    assert persisted.steps['progress'] == ['mock step 1', 'mock step 2']


async def test_process_run_pipeline_error_flags_failed(
    test_session_factory, make_tenant, monkeypatch
) -> None:
    result = PipelineResult(cliente='Acme', cuit=CUIT, error='extraction broke')
    monkeypatch.setattr(runner_mod, 'get_settings', lambda: _settings(arca=True))
    monkeypatch.setattr(runner_mod, 'get_ta', lambda *a, **k: ('tok', 'sign'))
    monkeypatch.setattr(runner_mod, 'PipelineService', _pipeline_fake(result=result))

    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(test_session_factory, tenant.id, steps=dict(_STEPS))

    await _make_runner(test_session_factory).process_run(run.id)

    persisted = await _get_run(test_session_factory, run.id)
    assert persisted.status == 'failed'
    assert persisted.error == {'code': 'PIPELINE_FAILED', 'cause': 'extraction broke'}


async def test_process_run_pipeline_raises_runs_failed(
    test_session_factory, make_tenant, monkeypatch
) -> None:
    monkeypatch.setattr(runner_mod, 'get_settings', lambda: _settings(arca=True))
    monkeypatch.setattr(runner_mod, 'get_ta', lambda *a, **k: ('tok', 'sign'))
    monkeypatch.setattr(
        runner_mod, 'PipelineService', _pipeline_fake(exc=RuntimeError('kaboom'))
    )
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(test_session_factory, tenant.id, steps=dict(_STEPS))

    await _make_runner(test_session_factory).process_run(run.id)

    persisted = await _get_run(test_session_factory, run.id)
    assert persisted.status == 'failed'
    assert persisted.error['code'] == 'RUN_FAILED'
    assert 'kaboom' in persisted.error['cause']


async def test_process_run_ta_unavailable(
    test_session_factory, make_tenant, monkeypatch
) -> None:
    monkeypatch.setattr(runner_mod, 'get_settings', lambda: _settings(arca=True))
    monkeypatch.setattr(runner_mod, 'get_ta', lambda *a, **k: (None, None))
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(test_session_factory, tenant.id, steps=dict(_STEPS))

    await _make_runner(test_session_factory).process_run(run.id)

    persisted = await _get_run(test_session_factory, run.id)
    assert persisted.status == 'failed'
    assert persisted.error['code'] == 'TA_UNAVAILABLE'
    assert 'remediation' in persisted.error


async def test_process_run_arca_disabled_marks_failed(
    test_session_factory, make_tenant, monkeypatch
) -> None:
    """A disabled ARCA integration fails the run with INTEGRATION_DISABLED."""
    monkeypatch.setattr(runner_mod, 'get_settings', lambda: _settings(arca=False))
    monkeypatch.setattr(runner_mod, 'get_ta', lambda *a, **k: ('tok', 'sign'))
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(test_session_factory, tenant.id, steps=dict(_STEPS))

    await _make_runner(test_session_factory).process_run(run.id)

    persisted = await _get_run(test_session_factory, run.id)
    assert persisted.status == 'failed'
    assert persisted.error['code'] == 'INTEGRATION_DISABLED'
    assert 'arca' in persisted.error['cause'].lower()


async def test_process_run_missing_period_fails(
    test_session_factory, make_tenant, monkeypatch
) -> None:
    monkeypatch.setattr(runner_mod, 'get_ta', lambda *a, **k: ('tok', 'sign'))
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(test_session_factory, tenant.id, steps=None)

    await _make_runner(test_session_factory).process_run(run.id)

    persisted = await _get_run(test_session_factory, run.id)
    assert persisted.status == 'failed'
    assert persisted.error['code'] == 'RUN_FAILED'
    assert 'mes' in persisted.error['cause'] or 'period' in persisted.error['cause']


async def test_process_run_not_found_is_noop(test_session_factory) -> None:
    runner = _make_runner(test_session_factory)
    await runner.process_run(uuid.uuid4())  # unknown id -> warning + return
    async with test_session_factory() as session:
        count = (await session.execute(select(ReportRun))).scalars().all()
    assert count == []


# ─── _build_cliente ─────────────────────────────────────────────────────────


async def test_build_cliente_without_client_id(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(test_session_factory, tenant.id)

    cliente = await _make_runner(test_session_factory)._build_cliente(
        MagicMock(), run
    )
    assert cliente == ClientConfig(cuit=CUIT)
    assert cliente.email == ''
    assert cliente.nombre is None


async def test_build_cliente_with_client_row(test_session_factory, make_tenant, make_client) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
        client = await make_client(
            session, tenant_id=tenant.id, cuit=CUIT, name='Acme SA', email='x@y.com'
        )
        run = await _insert_run(test_session_factory, tenant.id, client_id=client.id)
        cliente = await _make_runner(test_session_factory)._build_cliente(session, run)
    assert cliente.cuit == CUIT
    assert cliente.nombre == 'Acme SA'
    assert cliente.email == 'x@y.com'


async def test_build_cliente_missing_client_row() -> None:
    """A dangling ``client_id`` is impossible to insert via the ORM (FK
    constraint + ondelete SET NULL), so reach it only via a missing row."""
    runner = _make_runner(None)
    run = ReportRun(tenant_id=uuid.uuid4(), cuit=CUIT, client_id=uuid.uuid4())

    session = AsyncMock()
    session.get.return_value = None
    cliente = await runner._build_cliente(session, run)
    assert cliente == ClientConfig(cuit=CUIT)


# ─── _build_browser ─────────────────────────────────────────────────────────


async def test_build_browser_not_needed_returns_none() -> None:
    assert _make_runner(None)._build_browser(needed=False) is None


async def test_build_browser_missing_creds_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        runner_mod,
        'get_settings',
        lambda: SimpleNamespace(
            browser_enabled=True,
            credentials=SimpleNamespace(composio_api_key='', clave_fiscal=''),
        ),
    )
    runner = _make_runner(None)
    with pytest.raises(RuntimeError, match='COMPOSIO_API_KEY|ESTUDIO_CLAVE_FISCAL'):
        runner._build_browser(needed=True)


async def test_build_browser_partial_creds_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        runner_mod,
        'get_settings',
        lambda: SimpleNamespace(
            browser_enabled=True,
            credentials=SimpleNamespace(composio_api_key='key', clave_fiscal=''),
        ),
    )
    runner = _make_runner(None)
    with pytest.raises(RuntimeError, match='ESTUDIO_CLAVE_FISCAL'):
        runner._build_browser(needed=True)


async def test_build_browser_with_creds(monkeypatch) -> None:
    from agente_fiscal.config import REPRESENTANTE_CUIT

    monkeypatch.setattr(
        runner_mod,
        'get_settings',
        lambda: SimpleNamespace(
            browser_enabled=True,
            credentials=SimpleNamespace(composio_api_key='composio-key', clave_fiscal='clave'),
        ),
    )
    browser = _make_runner(None)._build_browser(needed=True)
    assert isinstance(browser, ComposioBrowser)
    assert browser._api_key == 'composio-key'
    assert browser._estudio_cuit == REPRESENTANTE_CUIT
    assert browser._estudio_clave == 'clave'


async def test_build_browser_disabled_raises(monkeypatch) -> None:
    """A disabled browser integration fails cleanly before touching creds."""
    monkeypatch.setattr(
        runner_mod,
        'get_settings',
        lambda: SimpleNamespace(
            browser_enabled=False,
            credentials=SimpleNamespace(composio_api_key='composio-key', clave_fiscal='clave'),
        ),
    )
    runner = _make_runner(None)
    with pytest.raises(runner_mod.IntegrationDisabledError) as exc_info:
        runner._build_browser(needed=True)
    assert exc_info.value.integration == 'browser'


# ─── _fetch_next_queued ─────────────────────────────────────────────────────


async def test_fetch_next_queued_oldest_first(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)

    older = await _insert_run(
        test_session_factory,
        tenant.id,
        status='done',
        created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    first = await _insert_run(
        test_session_factory,
        tenant.id,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    second = await _insert_run(
        test_session_factory,
        tenant.id,
        created_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
    )

    run_id = await _make_runner(test_session_factory)._fetch_next_queued()
    assert run_id == first.id
    assert run_id != older.id
    assert run_id != second.id


async def test_fetch_next_queued_none_when_empty(test_session_factory) -> None:
    assert await _make_runner(test_session_factory)._fetch_next_queued() is None


# ─── claim_next_queued (atomic claim) ───────────────────────────────────────


async def test_claim_next_queued_oldest_first_flips_running(
    test_session_factory, make_tenant
) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    older = await _insert_run(
        test_session_factory,
        tenant.id,
        status='done',
        created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    first = await _insert_run(
        test_session_factory,
        tenant.id,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    second = await _insert_run(
        test_session_factory,
        tenant.id,
        created_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
    )

    run_id = await _make_runner(test_session_factory).claim_next_queued()

    # Oldest *queued* run wins (done rows are skipped), FIFO is preserved.
    assert run_id == first.id
    assert run_id != older.id
    assert run_id != second.id

    # The claim flip is committed in the SAME transaction: the row is now
    # ``running`` with started_at set, so no other worker can pick it again.
    claimed = await _get_run(test_session_factory, first.id)
    assert claimed.status == 'running'
    assert claimed.started_at is not None
    assert (await _get_run(test_session_factory, second.id)).status == 'queued'
    assert (await _get_run(test_session_factory, older.id)).status == 'done'


async def test_claim_next_queued_none_when_empty(test_session_factory) -> None:
    assert await _make_runner(test_session_factory).claim_next_queued() is None


async def test_claim_next_queued_concurrent_no_double_claim(
    test_session_factory, make_tenant
) -> None:
    """Two workers RACING on N queued rows — no row is ever claimed twice.

    Exercises ``SELECT ... FOR UPDATE SKIP LOCKED``: the row lock is held
    from SELECT time until the queued -> running flip commits, so a sibling
    worker at BEST takes the next row and never the same one. This is the
    regression test for the ``--workers 2`` double-execution bug.
    """
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    runs = [await _insert_run(test_session_factory, tenant.id) for _ in range(8)]

    runner = _make_runner(test_session_factory)

    async def worker() -> list:
        claimed = []
        while True:
            run_id = await runner.claim_next_queued()
            if run_id is None:
                return claimed
            claimed.append(run_id)
            await asyncio.sleep(0)  # yield so the sibling task interleaves

    worker_a, worker_b = await asyncio.gather(worker(), worker())

    all_claimed = worker_a + worker_b
    assert len(all_claimed) == len(runs)          # every row was claimed...
    assert len(set(all_claimed)) == len(runs)     # ...exactly once (no duplicates)
    assert set(all_claimed) == {r.id for r in runs}

    # And every row now sits in ``running`` — none left queued, none done.
    async with test_session_factory() as session:
        remaining = (
            await session.execute(
                select(ReportRun.id).where(ReportRun.status == 'queued')
            )
        ).scalars().all()
        statuses = set((await session.execute(select(ReportRun.status))).scalars().all())
    assert remaining == []
    assert statuses == {'running'}


# ─── run_loop ───────────────────────────────────────────────────────────────


async def test_run_loop_processes_run_then_stops(
    test_session_factory, make_tenant, monkeypatch
) -> None:
    monkeypatch.setattr(runner_mod, 'get_settings', lambda: _settings(arca=True))
    monkeypatch.setattr(runner_mod, 'get_ta', lambda *a, **k: ('tok', 'sign'))
    monkeypatch.setattr(
        runner_mod, 'PipelineService', _pipeline_fake(result=PipelineResult(cliente='A', cuit=CUIT))
    )
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(test_session_factory, tenant.id, steps=dict(_STEPS))

    stop_event = asyncio.Event()
    task = asyncio.create_task(
        _make_runner(test_session_factory).run_loop(poll_interval=0.01, stop_event=stop_event)
    )
    try:
        for _ in range(300):
            persisted = await _get_run(test_session_factory, run.id)
            if persisted.status in ('done', 'failed'):
                break
            await asyncio.sleep(0.01)
        stop_event.set()
    finally:
        await task

    persisted = await _get_run(test_session_factory, run.id)
    assert persisted.status == 'done'
    assert task.done()


async def test_run_loop_broken_iteration_keeps_going(
    test_session_factory, monkeypatch
) -> None:
    runner = _make_runner(test_session_factory)

    async def boom():
        raise RuntimeError('worker hiccup')

    monkeypatch.setattr(runner, '_fetch_next_queued', boom)
    stop_event = asyncio.Event()
    task = asyncio.create_task(runner.run_loop(poll_interval=0.005, stop_event=stop_event))
    await asyncio.sleep(0.05)  # let a couple of failing iterations run
    stop_event.set()
    await task
    assert task.done()


async def test_run_loop_stops_immediately_when_event_set(test_session_factory) -> None:
    stop_event = asyncio.Event()
    stop_event.set()
    await _make_runner(test_session_factory).run_loop(poll_interval=0.01, stop_event=stop_event)


# ─── module-level helpers ───────────────────────────────────────────────────


async def test_module_run_loop_builds_runner(monkeypatch) -> None:
    """Module ``run_loop`` wires the shared deps into a ReportRunner without
    importing the real ``agente_fiscal.db.session`` (fake injected into
    ``sys.modules`` so the Neon URL is never even parsed)."""
    fake_factory = object()
    fake_session = types.ModuleType('agente_fiscal.db.session')
    fake_session.async_session_factory = fake_factory
    monkeypatch.setitem(sys.modules, 'agente_fiscal.db.session', fake_session)

    captured: dict = {}

    class FakeRunner:
        def __init__(self, session_factory, engine, pdf_gen, memory_client):
            captured['session_factory'] = session_factory

        async def run_loop(self, poll_interval, stop_event):
            captured['poll_interval'] = poll_interval
            captured['stop_event'] = stop_event

    monkeypatch.setattr(runner_mod, 'ReportRunner', FakeRunner)
    stop_event = asyncio.Event()
    await runner_mod.run_loop(poll_interval=0.01, stop_event=stop_event)

    assert captured['session_factory'] is fake_factory
    assert captured['poll_interval'] == 0.01
    assert captured['stop_event'] is stop_event


async def test_start_worker_disabled_without_session_factory(monkeypatch) -> None:
    app = SimpleNamespace(state=SimpleNamespace())
    ran = False
    async with start_worker(app):
        ran = True
    assert ran


async def test_start_worker_starts_and_stops_loop(monkeypatch) -> None:
    captured: dict = {}

    class FakeRunner:
        def __init__(self, session_factory, engine, pdf_gen, memory_client):
            captured['session_factory'] = session_factory

        async def run_loop(self, stop_event=None, poll_interval=5.0):
            captured['stop_event'] = stop_event
            await asyncio.sleep(0)

    monkeypatch.setattr(runner_mod, 'ReportRunner', FakeRunner)
    factory = object()
    app = SimpleNamespace(state=SimpleNamespace(session_factory=factory))

    async with start_worker(app):
        await asyncio.sleep(0)  # let the worker task start
        assert captured['session_factory'] is factory
        assert captured['stop_event'] is not None
        assert not captured['stop_event'].is_set()

    assert captured['stop_event'].is_set()


async def test_start_worker_cancelled_task_is_swallowed(monkeypatch) -> None:
    """A CancelledError from the worker task during shutdown is caught."""
    captured: dict = {}

    class CancellingRunner:
        def __init__(self, session_factory, engine, pdf_gen, memory_client):
            captured['session_factory'] = session_factory

        async def run_loop(self, stop_event=None, poll_interval=5.0):
            captured['stop_event'] = stop_event
            await asyncio.sleep(0)
            raise asyncio.CancelledError()

    monkeypatch.setattr(runner_mod, 'ReportRunner', CancellingRunner)
    app = SimpleNamespace(state=SimpleNamespace(session_factory=object()))

    async with start_worker(app):
        await asyncio.sleep(0)  # let the task start and raise CancelledError

    # No exception escapes the context manager; stop was requested.
    assert captured['stop_event'].is_set()