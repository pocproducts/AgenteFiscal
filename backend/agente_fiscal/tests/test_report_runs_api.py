"""Tests for ``agente_fiscal.api.routes.report_runs``.

The route coroutines are invoked directly with a constructed Starlette
``Request`` (``request.state.tenant_id`` set/omitted) and a real test session,
so no app/middleware is needed and the ``Depends(get_db_session)`` resolution
is skipped on purpose.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from starlette.requests import Request

from agente_fiscal.api.routes.report_runs import (
    CreateReportRunRequest,
    create_report_run,
    get_report_run,
)
from agente_fiscal.db.models import ReportRun

pytestmark = pytest.mark.usefixtures('db_reset')

CUIT = '20301234561'
CUIT_B = '20123456780'


def _request(tenant_id=None, path: str = '/v1/report-runs') -> Request:
    scope = {
        'type': 'http',
        'method': 'POST' if path == '/v1/report-runs' else 'GET',
        'path': path,
        'raw_path': path.encode(),
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
    return req


async def _insert_run(test_session_factory, tenant_id, *, cuit=CUIT, status='queued'):
    async with test_session_factory() as session:
        run = ReportRun(tenant_id=tenant_id, cuit=cuit, status=status)
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run


# ─── POST /v1/report-runs ───────────────────────────────────────────────────


async def test_create_report_run_success(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)

    async with test_session_factory() as session:
        resp = await create_report_run(
            request=_request(tenant.id),
            body=CreateReportRunRequest(
                cuit=CUIT,
                period={'mes': 6, 'anio': 2026},
                flags={'with_deuda': True},
            ),
            session=session,
        )

    assert resp.status == 'success'
    assert resp.error is None
    assert resp.result['status'] == 'queued'

    run_id = uuid.UUID(resp.result['report_run_id'])
    async with test_session_factory() as session:
        run = await session.get(ReportRun, run_id)
        assert run is not None
        assert run.tenant_id == tenant.id
        assert run.cuit == CUIT
        assert run.status == 'queued'
        assert run.steps == {'period': {'mes': 6, 'anio': 2026}, 'flags': {'with_deuda': True}}
        assert run.started_at is None
        assert run.finished_at is None


async def test_create_report_run_minimal_payload(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)

    async with test_session_factory() as session:
        resp = await create_report_run(
            request=_request(tenant.id),
            body=CreateReportRunRequest(cuit=CUIT),
            session=session,
        )
    assert resp.status == 'success'
    assert resp.result['status'] == 'queued'


async def test_create_report_run_without_tenant_returns_unauthenticated(
    test_session_factory,
) -> None:
    async with test_session_factory() as session:
        resp = await create_report_run(
            request=_request(None),
            body=CreateReportRunRequest(cuit=CUIT),
            session=session,
        )
    assert resp.status == 'error'
    assert resp.error.code == 'UNAUTHENTICATED'


async def test_create_report_run_non_uuid_tenant_returns_unauthenticated(
    test_session_factory,
) -> None:
    async with test_session_factory() as session:
        resp = await create_report_run(
            request=_request('i-am-not-a-uuid'),
            body=CreateReportRunRequest(cuit=CUIT),
            session=session,
        )
    assert resp.status == 'error'
    assert resp.error.code == 'UNAUTHENTICATED'


@pytest.mark.parametrize('bad_cuit', ['123', '2030123456a', '2030123456101', ''])
async def test_create_report_run_invalid_cuit(test_session_factory, make_tenant, bad_cuit) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    async with test_session_factory() as session:
        resp = await create_report_run(
            request=_request(tenant.id),
            body=CreateReportRunRequest(cuit=bad_cuit),
            session=session,
        )
    assert resp.status == 'error'
    assert resp.error.code == 'INVALID_CUIT'
    # Nothing got persisted.
    async with test_session_factory() as session:
        rows = (await session.execute(select(ReportRun))).scalars().all()
    assert rows == []


async def test_create_report_run_fk_failure_returns_create_failed(
    test_session_factory,
) -> None:
    ghost_tenant = uuid.uuid4()  # valid UUID but no tenants row -> FK violation
    async with test_session_factory() as session:
        resp = await create_report_run(
            request=_request(ghost_tenant),
            body=CreateReportRunRequest(cuit=CUIT),
            session=session,
        )
    assert resp.status == 'error'
    assert resp.error.code == 'REPORT_RUN_CREATE_FAILED'


# ─── GET /v1/report-runs/{id} ───────────────────────────────────────────────


async def test_get_report_run_foreign_tenant_not_found(
    test_session_factory, make_tenant
) -> None:
    async with test_session_factory() as session:
        tenant_a = await make_tenant(session)
        tenant_b = await make_tenant(session, name='Rival Ltd')
    run_b = await _insert_run(test_session_factory, tenant_b.id, cuit=CUIT_B)

    async with test_session_factory() as session:
        resp = await get_report_run(
            report_run_id=run_b.id, request=_request(tenant_a.id), session=session
        )
    assert resp.status == 'error'
    assert resp.error.code == 'REPORT_RUN_NOT_FOUND'


async def test_get_report_run_missing_run_same_error_as_foreign(
    test_session_factory, make_tenant
) -> None:
    """A missing run returns the SAME error as a foreign tenant's run — no
    existence disclosure."""
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    async with test_session_factory() as session:
        resp = await get_report_run(
            report_run_id=uuid.uuid4(), request=_request(tenant.id), session=session
        )
    assert resp.status == 'error'
    assert resp.error.code == 'REPORT_RUN_NOT_FOUND'


async def test_get_report_run_own_run_success(test_session_factory, make_tenant) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(test_session_factory, tenant.id, cuit=CUIT)

    async with test_session_factory() as session:
        resp = await get_report_run(
            report_run_id=run.id, request=_request(tenant.id), session=session
        )
    assert resp.status == 'success'
    assert resp.result['report_run_id'] == str(run.id)
    assert resp.result['status'] == 'queued'
    assert resp.result['cuit'] == CUIT
    assert resp.result['steps'] == {}
    assert resp.result['result_summary'] is None
    assert resp.result['error'] is None
    assert resp.result['started_at'] is None
    assert resp.result['finished_at'] is None


async def test_get_report_run_without_tenant_returns_unauthenticated(
    test_session_factory, make_tenant
) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(test_session_factory, tenant.id)

    async with test_session_factory() as session:
        resp = await get_report_run(
            report_run_id=run.id, request=_request(None), session=session
        )
    assert resp.status == 'error'
    assert resp.error.code == 'UNAUTHENTICATED'


async def test_get_report_run_non_uuid_tenant_returns_unauthenticated(
    test_session_factory, make_tenant
) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    run = await _insert_run(test_session_factory, tenant.id)

    async with test_session_factory() as session:
        resp = await get_report_run(
            report_run_id=run.id, request=_request('nope'), session=session
        )
    assert resp.status == 'error'
    assert resp.error.code == 'UNAUTHENTICATED'