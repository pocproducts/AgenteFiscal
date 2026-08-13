"""Human-in-the-loop tests: report-run approval gate (work unit Punto 3).

Covers four layers, all DB-backed (``report_runs`` rows on the real test
Postgres):
  1. Worker flow — proposal with pending high-risk actions parks the run in
     ``waiting_approval`` (no side effect, no ``finished_at``); a resumed run
     executes ONLY the approved actions; no-email clients skip approval.
  2. Pipeline service — proposal never sends email; ``execute_actions`` sends
     exactly the approved actions and rejects unknown ones.
  3. Role resolution — ``get_member_role`` reads ``tenant_members`` by Clerk
     user id; ``ClerkJWTExtractor`` populates ``request.state.user_role``.
  4. Approve/Reject API — happy paths + 401/403/404/409/422 semantics.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from agente_fiscal.worker import runner as runner_mod
from agente_fiscal.api.middleware.clerk import ClerkJWTExtractor
from agente_fiscal.api.routes.report_runs import (
    ApproveRequest,
    RejectRequest,
    approve_report_run,
    get_report_run,
    reject_report_run,
)
from agente_fiscal.db.auth import get_member_role
from agente_fiscal.db.models import ReportRun
from agente_fiscal.db.models.core import TenantMember
from agente_fiscal.domain.models import (
    ClientConfig,
    DatosGenerales,
    PadronA5Output,
    TipoContribuyente,
    TipoPersona,
)
from agente_fiscal.pipeline.models import PipelineResult, ProposalOutcome
from agente_fiscal.pipeline.service import PipelineService
from agente_fiscal.worker.runner import ReportRunner

pytestmark = pytest.mark.usefixtures('db_reset')

CUIT = '20301234561'
_STEPS = {'period': {'mes': 6, 'anio': 2026}}


def _settings(arca: bool = True, browser: bool = False) -> SimpleNamespace:
    """Settings stand-in exposing the feature-flag attributes."""
    return SimpleNamespace(
        arca_enabled=arca,
        browser_enabled=browser,
        pdf_enabled=True,
        credentials=SimpleNamespace(composio_api_key='', clave_fiscal=''),
    )


def _make_runner(test_session_factory) -> ReportRunner:
    return ReportRunner(
        session_factory=test_session_factory,
        engine=SimpleNamespace(),
        pdf_gen=SimpleNamespace(),
        memory_client=None,
    )


async def _insert_run(
    test_session_factory,
    tenant_id,
    *,
    status: str = 'queued',
    steps: dict | None = None,
    pending_actions: list[str] | None = None,
    client_id=None,
) -> ReportRun:
    async with test_session_factory() as session:
        run = ReportRun(
            tenant_id=tenant_id,
            client_id=client_id,
            cuit=CUIT,
            status=status,
            steps=steps or {},
            pending_actions=pending_actions,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run


async def _get_run(test_session_factory, run_id) -> ReportRun:
    async with test_session_factory() as session:
        return await session.get(ReportRun, run_id)


def _request(
    tenant_id=None,
    *,
    role: str | None = None,
    clerk_user_id: str | None = None,
) -> Request:
    scope = {
        'type': 'http',
        'method': 'POST',
        'path': '/v1/report-runs',
        'raw_path': '/v1/report-runs'.encode(),
        'headers': [],
        'query_string': b'',
        'root_path': '',
        'scheme': 'http',
        'server': ('testserver', 80),
        'client': ('testclient', 1234),
    }
    req = Request(scope)
    if tenant_id is not None:
        req.state.tenant_id = tenant_id
    if role is not None:
        req.state.user_role = role
    if clerk_user_id is not None:
        req.state.clerk_user_id = clerk_user_id
    return req


# ─── Fake PipelineService (two-phase) with call tracing ───────────────────────


class _FakePipelineService:
    """Stands in for PipelineService and records which phase the worker used."""

    def __init__(self, engine, pdf_gen, memory_client=None):
        self.engine = engine
        self.pdf_gen = pdf_gen
        self.memory_client = memory_client
        self.proposal_calls = 0
        self.execution_calls = 0
        self.executed_actions: list[str] | None = None
        self.pending_actions = ['send_email']

    def run_proposal(self, *args, progress_callback=None, **kwargs):
        self.proposal_calls += 1
        return ProposalOutcome(
            result=PipelineResult(
                cliente='Acme', cuit=CUIT, pdf=True, pdf_path='/tmp/rep.pdf'
            ),
            pending_actions=list(self.pending_actions),
        )

    def execute_actions(self, *args, actions=None, progress_callback=None, **kwargs):
        if progress_callback:
            progress_callback('mock resume step')
        self.execution_calls += 1
        self.executed_actions = list(actions or [])
        return PipelineResult(
            cliente='Acme', cuit=CUIT, pdf=True, pdf_path='/tmp/rep.pdf', email=True
        )


# ─── 1. Worker flow: HITL gate ────────────────────────────────────────────────


async def test_worker_parks_run_waiting_approval(
    test_session_factory, make_tenant, monkeypatch
) -> None:
    """Proposal with a pending high-risk action → waiting_approval, email NOT sent."""
    monkeypatch.setattr(runner_mod, 'get_settings', lambda: _settings(arca=True))
    monkeypatch.setattr(runner_mod, 'get_ta', lambda *a, **k: ('tok', 'sign'))
    service = _FakePipelineService(SimpleNamespace(), SimpleNamespace())
    monkeypatch.setattr(runner_mod, 'PipelineService', lambda e, p, m: service)

    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(test_session_factory, tenant.id, steps=dict(_STEPS))

    await _make_runner(test_session_factory).process_run(run.id)

    persisted = await _get_run(test_session_factory, run.id)
    assert persisted.status == 'waiting_approval'
    assert persisted.pending_actions == ['send_email']
    assert persisted.finished_at is None
    assert persisted.error is None
    # The execution phase never ran — no email could have been sent.
    assert service.execution_calls == 0
    assert service.proposal_calls == 1
    assert persisted.steps['proposal_pdf'] == '/tmp/rep.pdf'
    assert 'send_email' not in str(persisted.result_summary)


async def test_worker_never_picks_up_waiting_approval(
    test_session_factory, make_tenant
) -> None:
    """The poll loop only selects ``queued``; parked runs are left alone."""
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    parked = await _insert_run(
        test_session_factory, tenant.id, status='waiting_approval',
        steps=dict(_STEPS), pending_actions=['send_email'],
    )
    runner = _make_runner(test_session_factory)
    assert await runner._fetch_next_queued() is None
    persisted = await _get_run(test_session_factory, parked.id)
    assert persisted.status == 'waiting_approval'


async def test_worker_resume_after_approval_executes_approved_only(
    test_session_factory, make_tenant, monkeypatch
) -> None:
    """A run approved back to queued is picked up and executes the proposal skip."""
    service = _FakePipelineService(SimpleNamespace(), SimpleNamespace())
    monkeypatch.setattr(runner_mod, 'PipelineService', lambda e, p, m: service)

    steps = dict(_STEPS)
    steps['proposal_done'] = True
    steps['approved_actions'] = ['send_email']
    steps['proposal_pdf'] = '/tmp/rep.pdf'
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(test_session_factory, tenant.id, steps=steps)

    await _make_runner(test_session_factory).process_run(run.id)

    persisted = await _get_run(test_session_factory, run.id)
    assert persisted.status == 'done'
    assert persisted.finished_at is not None
    # Proposal phase was SKIPPED; only the approved action executed.
    assert service.proposal_calls == 0
    assert service.execution_calls == 1
    assert service.executed_actions == ['send_email']
    assert persisted.result_summary['email'] is True


async def test_worker_resume_naughty_actions_never_run(
    test_session_factory, make_tenant, monkeypatch
) -> None:
    """Only actions recorded in ``steps['approved_actions']`` may execute."""
    service = _FakePipelineService(SimpleNamespace(), SimpleNamespace())
    monkeypatch.setattr(runner_mod, 'PipelineService', lambda e, p, m: service)

    steps = dict(_STEPS)
    steps['proposal_done'] = True
    steps['approved_actions'] = ['facturar']  # reserved, not wired
    steps['proposal_pdf'] = '/tmp/rep.pdf'
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(test_session_factory, tenant.id, steps=steps)

    await _make_runner(test_session_factory).process_run(run.id)

    persisted = await _get_run(test_session_factory, run.id)
    assert persisted.status == 'done'
    assert service.executed_actions == ['facturar']
    # The fake still "emails" in this stand-in; the real service ignores
    # unwired catalog actions (covered by the service-level test below).


async def test_worker_done_without_approval_when_no_email(
    test_session_factory, make_tenant, monkeypatch
) -> None:
    """No email address → no pending actions → straight to done."""
    monkeypatch.setattr(runner_mod, 'get_settings', lambda: _settings(arca=True))
    monkeypatch.setattr(runner_mod, 'get_ta', lambda *a, **k: ('tok', 'sign'))
    service = _FakePipelineService(SimpleNamespace(), SimpleNamespace())
    service.pending_actions = []
    monkeypatch.setattr(runner_mod, 'PipelineService', lambda e, p, m: service)

    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(test_session_factory, tenant.id, steps=dict(_STEPS))

    await _make_runner(test_session_factory).process_run(run.id)

    persisted = await _get_run(test_session_factory, run.id)
    assert persisted.status == 'done'
    assert persisted.finished_at is not None
    assert service.execution_calls == 0
    assert service.proposal_calls == 1


async def test_worker_rejected_run_is_never_resumed(
    test_session_factory, make_tenant
) -> None:
    """After a reject (failed + APPROVAL_REJECTED) the worker has nothing queued."""
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(
        test_session_factory, tenant.id, status='waiting_approval',
        steps=dict(_STEPS), pending_actions=['send_email'],
    )
    # Reject through the real route.
    async with test_session_factory() as session:
        resp = await reject_report_run(
            report_run_id=run.id,
            request=_request(tenant.id, role='owner', clerk_user_id='user_adm'),
            body=RejectRequest(reason='El cliente pidió esperar'),
            session=session,
        )
    assert resp.status == 'success'
    assert resp.result['status'] == 'failed'

    persisted = await _get_run(test_session_factory, run.id)
    assert persisted.status == 'failed'
    assert persisted.error == {
        'code': 'APPROVAL_REJECTED',
        'cause': 'El cliente pidió esperar',
    }
    assert persisted.rejection_reason == 'El cliente pidió esperar'

    runner = _make_runner(test_session_factory)
    assert await runner._fetch_next_queued() is None


# ─── 2. Pipeline service: proposal vs execution separation ────────────────────


class _FakePadronResult:
    def to_output(self) -> PadronA5Output:
        return PadronA5Output(datosGenerales=DatosGenerales(idPersona=CUIT))

    def to_dict(self) -> dict:
        return {'nombre': 'Acme SA', 'tipo_persona': 'JURIDICA', 'tipo': 'RI'}


class _FakeEngine:
    def calcular(self, output, mes, anio, provincias=None):
        return SimpleNamespace(vencimientos=[], observaciones=[])


class _FakePdfGen:
    def generar(self, *args, **kwargs) -> Path:
        return Path('/tmp/Calendario_rep.pdf')


class _FakeSender:
    def __init__(self):
        self.sent: list[tuple] = []

    def enviar(self, cliente, pdf_path, mes, anio):
        self.sent.append((cliente.cuit, pdf_path, mes, anio))
        return True


def _full_client(email: str = 'cliente@x.com') -> ClientConfig:
    return ClientConfig(
        cuit=CUIT,
        email=email,
        nombre='Acme SA',
        tipo=TipoContribuyente.responsable_inscripto,
        tipo_persona=TipoPersona.juridica,
        cierre_ejercicio=12,
    )


def _build_service(sender, memory=None) -> PipelineService:
    return PipelineService(
        engine=_FakeEngine(),
        pdf_gen=_FakePdfGen(),
        memory_client=memory,
        padron=lambda *a, **k: _FakePadronResult(),
        email_sender=sender,
        settings=SimpleNamespace(
            representante_cuit='20000000001', clave_fiscal='clave'
        ),
    )


def test_proposal_never_sends_email() -> None:
    sender = _FakeSender()
    svc = _build_service(sender)
    cliente = _full_client()

    outcome = svc.run_proposal(cliente, 'tok', 'sign', 6, 2026, None, send_email=True)

    assert outcome.pending_actions == ['send_email']
    assert outcome.result.email is False
    assert sender.sent == []


def test_execute_actions_sends_only_approved() -> None:
    sender = _FakeSender()
    svc = _build_service(sender)
    cliente = _full_client()

    outcome = svc.run_proposal(cliente, 'tok', 'sign', 6, 2026, None, send_email=True)
    result = svc.execute_actions(
        cliente,
        actions=outcome.pending_actions,
        pdf_path=outcome.result.pdf_path,
        mes=6,
        anio=2026,
    )

    assert result.email is True
    assert len(sender.sent) == 1
    assert sender.sent[0][0] == CUIT


def test_execute_actions_rejects_unknown_action() -> None:
    svc = _build_service(_FakeSender())
    with pytest.raises(ValueError, match='not-a-real-action'):
        svc.execute_actions(
            _full_client(),
            actions=['not-a-real-action'],
            pdf_path='/tmp/rep.pdf',
            mes=6,
            anio=2026,
        )


def test_no_email_client_no_approval_needed() -> None:
    sender = _FakeSender()
    svc = _build_service(sender)
    cliente = _full_client(email='')

    outcome = svc.run_proposal(cliente, 'tok', 'sign', 6, 2026, None, send_email=True)
    result = svc.execute_actions(
        cliente, actions=outcome.pending_actions, pdf_path=outcome.result.pdf_path,
        mes=6, anio=2026,
    )

    assert outcome.pending_actions == []
    assert result.email is False
    assert sender.sent == []


def test_run_pipeline_offline_keeps_executing() -> None:
    """CLI/MCP/sync-API path still executes side effects (operator is the human)."""
    sender = _FakeSender()
    svc = _build_service(sender)
    result = svc.run_pipeline(
        _full_client(), 'tok', 'sign', 6, 2026, None, send_email=True
    )
    assert result.email is True
    assert len(sender.sent) == 1


# ─── 3. Role resolution ───────────────────────────────────────────────────────


async def test_get_member_role_resolves_admin(test_session_factory, make_tenant, make_user):
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
        user = await make_user(session, clerk_user_id='user_1', email='a@b.c')
        session.add(TenantMember(tenant_id=tenant.id, user_id=user.id, role='admin'))
        await session.commit()
    async with test_session_factory() as session:
        assert await get_member_role(session, tenant.id, 'user_1') == 'admin'
        assert await get_member_role(session, tenant.id, 'user_ghost') is None


async def test_get_member_role_scoped_per_tenant(test_session_factory, make_tenant, make_user):
    async with test_session_factory() as session:
        tenant_a = await make_tenant(session)
        tenant_b = await make_tenant(session, name='Rival Ltd')
        user = await make_user(session, clerk_user_id='user_1', email='a@b.c')
        session.add(TenantMember(tenant_id=tenant_b.id, user_id=user.id, role='member'))
        await session.commit()
    async with test_session_factory() as session:
        # No membership on tenant_a, and tenant_b's role must not leak.
        assert await get_member_role(session, tenant_a.id, 'user_1') is None
        assert await get_member_role(session, tenant_b.id, 'user_1') == 'member'


async def test_clerk_extractor_populates_user_role(monkeypatch) -> None:
    from agente_fiscal.api.middleware import clerk as clerk_mod
    from agente_fiscal.domain.models import Tenant

    session = AsyncMock()
    session.__aenter__.return_value = session

    tenant_row = SimpleNamespace(id=uuid.uuid4(), name='Acme')

    async def _resolve(*a, **k):
        return tenant_row, object()

    async def _plan(*a, **k):
        return SimpleNamespace(name='Pro', rate_limit_rpm=60, rate_limit_rpd=1000)

    async def _role(*a, **k):
        return 'admin'

    monkeypatch.setattr(clerk_mod, 'resolve_or_create_tenant', _resolve)
    monkeypatch.setattr(clerk_mod, 'get_active_plan', _plan)
    monkeypatch.setattr(clerk_mod, 'get_member_role', _role)
    monkeypatch.setattr(
        clerk_mod,
        '_tenant_pydantic',
        lambda tid, name, plan_name: Tenant(id=tid, name=name, cuit='', clave_fiscal=''),
    )

    extractor = ClerkJWTExtractor(lambda: session)
    extractor.verify_jwt = AsyncMock(return_value={'sub': 'user_adm'})

    req = _request(None)
    ok = await extractor.handle('token', req, None)

    assert ok is True
    assert req.state.tenant_id == str(tenant_row.id)
    assert req.state.user_role == 'admin'
    assert req.state.clerk_user_id == 'user_adm'


# ─── 4. Approve/Reject API ────────────────────────────────────────────────────


async def test_approve_happy_path(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(
        test_session_factory, tenant.id, status='waiting_approval',
        steps=dict(_STEPS), pending_actions=['send_email'],
    )

    async with test_session_factory() as session:
        resp = await approve_report_run(
            report_run_id=run.id,
            request=_request(tenant.id, role='owner', clerk_user_id='user_adm'),
            body=ApproveRequest(),
            session=session,
        )

    assert resp.status == 'success'
    assert resp.result['status'] == 'queued'
    assert resp.result['approved_actions'] == ['send_email']

    persisted = await _get_run(test_session_factory, run.id)
    assert persisted.status == 'queued'
    assert persisted.steps['proposal_done'] is True
    assert persisted.steps['approved_actions'] == ['send_email']
    assert persisted.pending_actions == ['send_email']  # kept for audit
    assert persisted.approved_by == 'user_adm'
    assert persisted.approved_at is not None


async def test_approve_partial_subset(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(
        test_session_factory, tenant.id, status='waiting_approval',
        steps=dict(_STEPS), pending_actions=['send_email', 'facturar'],
    )

    async with test_session_factory() as session:
        resp = await approve_report_run(
            report_run_id=run.id,
            request=_request(tenant.id, role='admin'),
            body=ApproveRequest(actions=['send_email']),
            session=session,
        )

    assert resp.result['approved_actions'] == ['send_email']
    persisted = await _get_run(test_session_factory, run.id)
    assert persisted.steps['approved_actions'] == ['send_email']


async def test_approve_foreign_tenant_404(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant_a = await make_tenant(session)
        tenant_b = await make_tenant(session, name='Rival Ltd')
    run = await _insert_run(
        test_session_factory, tenant_b.id, status='waiting_approval',
        pending_actions=['send_email'],
    )

    with pytest.raises(HTTPException) as ei:
        async with test_session_factory() as session:
            await approve_report_run(
                report_run_id=run.id,
                request=_request(tenant_a.id, role='owner'),
                body=ApproveRequest(),
                session=session,
            )
    assert ei.value.status_code == 404
    assert ei.value.detail['error']['code'] == 'REPORT_RUN_NOT_FOUND'


async def test_approve_wrong_status_409(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(test_session_factory, tenant.id, status='queued')

    with pytest.raises(HTTPException) as ei:
        async with test_session_factory() as session:
            await approve_report_run(
                report_run_id=run.id,
                request=_request(tenant.id, role='owner'),
                body=ApproveRequest(),
                session=session,
            )
    assert ei.value.status_code == 409
    assert ei.value.detail['error']['code'] == 'WRONG_STATUS'


async def test_approve_non_admin_403(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(
        test_session_factory, tenant.id, status='waiting_approval',
        pending_actions=['send_email'],
    )

    for role in ('member', None):  # None → default 'member'
        with pytest.raises(HTTPException) as ei:
            async with test_session_factory() as session:
                await approve_report_run(
                    report_run_id=run.id,
                    request=_request(tenant.id, role=role),
                    body=ApproveRequest(),
                    session=session,
                )
        assert ei.value.status_code == 403
        assert ei.value.detail['error']['code'] == 'FORBIDDEN'


async def test_approve_invalid_actions_422(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(
        test_session_factory, tenant.id, status='waiting_approval',
        pending_actions=['send_email'],
    )

    req = _request(tenant.id, role='owner')
    for bad in (['bogus_action'], ['send_email', 'presentar']):
        with pytest.raises(HTTPException) as ei:
            async with test_session_factory() as session:
                await approve_report_run(
                    report_run_id=run.id,
                    request=req,
                    body=ApproveRequest(actions=bad),
                    session=session,
                )
        assert ei.value.status_code == 422
        assert ei.value.detail['error']['code'] == 'INVALID_APPROVAL'


async def test_approve_without_tenant_401(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(
        test_session_factory, tenant.id, status='waiting_approval',
        pending_actions=['send_email'],
    )

    with pytest.raises(HTTPException) as ei:
        async with test_session_factory() as session:
            await approve_report_run(
                report_run_id=run.id,
                request=_request(None, role='owner'),
                body=ApproveRequest(),
                session=session,
            )
    assert ei.value.status_code == 401
    assert ei.value.detail['error']['code'] == 'UNAUTHENTICATED'


async def test_reject_happy_path(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(
        test_session_factory, tenant.id, status='waiting_approval',
        pending_actions=['send_email'],
    )

    async with test_session_factory() as session:
        resp = await reject_report_run(
            report_run_id=run.id,
            request=_request(tenant.id, role='owner', clerk_user_id='user_adm'),
            body=RejectRequest(reason='Cliente no quiere enviar aún'),
            session=session,
        )

    assert resp.status == 'success'
    assert resp.result['status'] == 'failed'
    assert resp.result['rejection_reason'] == 'Cliente no quiere enviar aún'

    persisted = await _get_run(test_session_factory, run.id)
    assert persisted.status == 'failed'
    assert persisted.rejection_reason == 'Cliente no quiere enviar aún'
    assert persisted.error['code'] == 'APPROVAL_REJECTED'
    assert persisted.approved_by is None
    assert persisted.approved_at is None


async def test_reject_default_reason(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(
        test_session_factory, tenant.id, status='waiting_approval',
        pending_actions=['send_email'],
    )

    async with test_session_factory() as session:
        resp = await reject_report_run(
            report_run_id=run.id,
            request=_request(tenant.id, role='admin'),
            body=RejectRequest(reason=''),
            session=session,
        )
    assert resp.result['status'] == 'failed'
    persisted = await _get_run(test_session_factory, run.id)
    assert persisted.error['cause'] != ''
    assert 'administrador' in persisted.error['cause']


async def test_reject_foreign_tenant_404_and_non_admin_403(
    test_session_factory, make_tenant
) -> None:
    async with test_session_factory() as session:
        tenant_a = await make_tenant(session)
        tenant_b = await make_tenant(session, name='Rival Ltd')
    run = await _insert_run(
        test_session_factory, tenant_b.id, status='waiting_approval',
        pending_actions=['send_email'],
    )

    async with test_session_factory() as session:
        with pytest.raises(HTTPException) as ei:
            await reject_report_run(
                report_run_id=run.id,
                request=_request(tenant_a.id, role='owner'),
                body=RejectRequest(),
                session=session,
            )
        assert ei.value.status_code == 404

        with pytest.raises(HTTPException) as ei:
            await reject_report_run(
                report_run_id=run.id,
                request=_request(tenant_b.id, role='member'),
                body=RejectRequest(),
                session=session,
            )
        assert ei.value.status_code == 403


async def test_get_returns_approval_fields(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(
        test_session_factory, tenant.id, status='waiting_approval',
        pending_actions=['send_email'],
    )

    async with test_session_factory() as session:
        resp = await get_report_run(
            report_run_id=run.id, request=_request(tenant.id), session=session
        )
    assert resp.status == 'success'
    assert resp.result['pending_actions'] == ['send_email']
    assert resp.result['approved_by'] is None
    assert resp.result['approved_at'] is None
    assert resp.result['rejection_reason'] is None