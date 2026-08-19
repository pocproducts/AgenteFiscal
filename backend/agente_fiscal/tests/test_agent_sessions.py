"""Agent-sessions telemetry tests (AST-1..6, ADR-7).

Covers the ``agent_sessions`` persistence contract against the real test
Postgres (``db_reset`` opt-in) and the Composio ADR-7 resolution with the
provider calls mocked:

- AST-1: the ORM row round-trips (insert with NULL profile, cost default 0).
- AST-2: one row per recorded run (record() + list_for()).
- AST-3: consultaarca rows carry the 7 canonical "Acciones", NULL ids and
  round-trip duration in the row timestamps.
- AST-4/ADR-7: `ComposioTelemetry` resolves session_id from the provider
  Logs API and event_count from the Usage API; every failure degrades to
  NULL/0 without raising (telemetry never breaks the chat stream).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from fastapi import FastAPI, Request
from sqlalchemy import func, select

from agente_fiscal.adapters.browser.composio_telemetry import (
    ComposioTelemetry,
    _deep_session_id,
)
from agente_fiscal.adapters.db_agent_sessions import PostgresAgentSessionsRepository
from agente_fiscal.db.models import AgentSession as AgentSessionRow
from agente_fiscal.domain.session_tasks import (
    CONSULTAARCA_TASKS,
    build_session_tasks,
)
from agente_fiscal.ports.agent_sessions import AgentSession

pytestmark = pytest.mark.usefixtures('db_reset')


def _session(
    *,
    tool: str = 'consultaarca',
    message_id: str = 'msg-1',
    conversation_id: str = 'conv-1',
    session_id: str | None = None,
    profile_id: str | None = None,
    tenant_id: str = str(uuid.uuid4()),
    cost_cents: int = 0,
    status: str = 'completed',
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    tasks: list[dict] | None = None,
) -> AgentSession:
    return AgentSession(
        id=str(uuid.uuid4()),
        tool=tool,
        message_id=message_id,
        conversation_id=conversation_id,
        profile_id=profile_id,
        tenant_id=tenant_id,
        user_id=None,
        session_id=session_id,
        status=status,
        tasks=tasks if tasks is not None else [],
        cost_cents=cost_cents,
        started_at=started_at,
        completed_at=completed_at,
    )


# ── AST-1: persistence table round-trip ────────────────────────────────────


async def test_record_round_trips_engine_row_with_null_profile(
    test_session_factory, make_tenant
) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    repo = PostgresAgentSessionsRepository(test_session_factory)
    started = datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc)
    completed = started + timedelta(seconds=3)

    row = _session(
        tenant_id=str(tenant.id),
        profile_id=None,
        session_id=None,
        started_at=started,
        completed_at=completed,
    )
    await repo.record(row)

    async with test_session_factory() as session:
        rows = (await session.execute(select(AgentSessionRow))).scalars().all()
    assert len(rows) == 1
    assert rows[0].tool == 'consultaarca'
    assert rows[0].profile_id is None
    assert rows[0].session_id is None
    assert rows[0].cost_cents == 0
    assert rows[0].status == 'completed'
    assert rows[0].started_at == started
    assert rows[0].completed_at == completed


async def test_record_with_none_for_all_optionals_is_accepted(
    test_session_factory, make_tenant
) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    repo = PostgresAgentSessionsRepository(test_session_factory)
    row = _session(tenant_id=str(tenant.id))
    await repo.record(row)

    async with test_session_factory() as session:
        rows = (await session.execute(select(AgentSessionRow))).scalars().all()
    assert len(rows) == 1


# ── AST-2: one row per run, list returns them newest-first ──────────────────


async def test_record_and_list_for_scoped_by_tenant(
    test_session_factory, make_tenant
) -> None:
    async with test_session_factory() as session:
        tenant_a = await make_tenant(session, name='Tenant A')
        tenant_b = await make_tenant(session, name='Tenant B')
    repo_a = PostgresAgentSessionsRepository(test_session_factory)

    for i in range(3):
        row = _session(tool=f'tool-{i}', message_id=f'msg-{i}', tenant_id=str(tenant_a.id))
        await repo_a.record(row)
    # A row from another tenant must never be visible to tenant A.
    foreign = _session(tool='leak', tenant_id=str(tenant_b.id))
    await repo_a.record(foreign)

    listed = await repo_a.list_for(
        tenant_id=tenant_a.id,
        user_id=None,
        role='owner',
    )
    assert len(listed) == 3
    assert listed[0].message_id == 'msg-2'  # newest first


async def test_list_for_filters_by_conversation(
    test_session_factory, make_tenant
) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    repo = PostgresAgentSessionsRepository(test_session_factory)
    for conv in ('conv-1', 'conv-2', 'conv-1'):
        row = _session(conversation_id=conv, tenant_id=str(tenant.id))
        await repo.record(row)

    listed = await repo.list_for(
        tenant_id=tenant.id,
        user_id=None,
        role='owner',
        conversation_id='conv-1',
    )
    assert len(listed) == 2


# ── AST-3: consultaarca "Acciones" shape ───────────────────────────────────


async def test_consultaarca_tasks_are_seven_canonical(
    test_session_factory, make_tenant
) -> None:
    tasks = build_session_tasks('consultaarca', 'completed')
    assert len(tasks) == 7
    assert [t['task'] for t in tasks] == [f'task-{i}' for i in range(7)]
    assert [t['label'] for t in tasks] == list(CONSULTAARCA_TASKS)
    assert all(t['status'] == 'completed' for t in tasks)

    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    repo = PostgresAgentSessionsRepository(test_session_factory)
    row = _session(tasks=tasks, tenant_id=str(tenant.id))
    await repo.record(row)

    async with test_session_factory() as session:
        rows = (await session.execute(select(AgentSessionRow))).scalars().all()
    assert rows[0].tasks == tasks


async def test_error_run_marks_each_task_error() -> None:
    tasks = build_session_tasks('consultaarca', 'error')
    assert all(t['status'] == 'error' for t in tasks)


# ── AST-4 / ADR-7: provider telemetry resolution (mocked) ──────────────────


def test_deep_session_id_top_level_and_context() -> None:
    assert _deep_session_id({'session_id': 's1'}) == 's1'
    assert _deep_session_id({'sessionId': 's2'}) == 's2'
    assert _deep_session_id({'context': {'session_id': 's3'}}) == 's3'
    assert _deep_session_id({'context': {'trace_id': 't'}}) is None
    assert _deep_session_id({}) is None


async def test_composio_telemetry_fetch_session_id_from_logs(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, headers, json, timeout):
        captured['url'] = url
        captured['headers'] = headers
        captured['json'] = json
        return _FakeResponse({'items': [{'context': {'session_id': 'sess-42'}}]})

    monkeypatch.setattr('agente_fiscal.adapters.browser.composio_telemetry.requests.post', fake_post)
    resolver = ComposioTelemetry('test-key')
    session_id = resolver.fetch_session_id(
        tool='BROWSER_TOOL_CREATE_TASK',
        start_time='2026-08-19T10:00:00+00:00',
        end_time='2026-08-19T10:01:00+00:00',
    )
    assert session_id == 'sess-42'
    assert '/logs/tool_execution' in captured['url']
    assert captured['headers']['x-api-key'] == 'test-key'
    assert captured['json']['tool'] == 'BROWSER_TOOL_CREATE_TASK'


async def test_composio_telemetry_fetch_event_count_from_usage(monkeypatch) -> None:
    def fake_post(url, headers, json, timeout):
        return _FakeResponse({'event_count': 12})

    monkeypatch.setattr('agente_fiscal.adapters.browser.composio_telemetry.requests.post', fake_post)
    resolver = ComposioTelemetry('test-key')
    count = resolver.fetch_event_count(
        start_time='2026-08-19T10:00:00+00:00',
        end_time='2026-08-19T10:01:00+00:00',
    )
    assert count == 12


async def test_composio_telemetry_failure_degrades_gracefully(monkeypatch) -> None:
    def boom(*_a, **_k):
        raise requests.ConnectionError('provider down')

    monkeypatch.setattr('agente_fiscal.adapters.browser.composio_telemetry.requests.post', boom)
    resolver = ComposioTelemetry('test-key')
    assert resolver.fetch_session_id() is None
    assert resolver.fetch_event_count() is None
    assert resolver.resolve_run() == {}  # never raises


async def test_composio_telemetry_resolve_run_combines_both(monkeypatch) -> None:
    def fake_post(url, headers, json, timeout):
        if '/logs/' in url:
            return _FakeResponse({'items': [{'session_id': 'sess-7'}]})
        return _FakeResponse({'event_count': 7})

    monkeypatch.setattr('agente_fiscal.adapters.browser.composio_telemetry.requests.post', fake_post)
    resolver = ComposioTelemetry('test-key')
    run = resolver.resolve_run()
    assert run.get('session_id') == 'sess-7'
    assert run.get('event_count') == 7


# ── AST-2 integration: chat.py persists one row post-run (Request fake) ─────


def _fake_request(app: FastAPI, *, clerk_user_id: str | None = 'user_1') -> Request:
    scope: dict = {
        'type': 'http',
        'method': 'POST',
        'path': '/v1/chat/message/stream',
        'headers': [],
        'query_string': b'',
        'scheme': 'http',
        'server': ('testserver', 80),
        'client': ('testclient', 50000),
        # ``Request.app`` is read-only in Starlette — it is derived from scope.
        'app': app,
    }
    request = Request(scope)
    if clerk_user_id:
        request.state.clerk_user_id = clerk_user_id
    return request


async def test_chat_persists_agent_session_via_request(
    test_session_factory, make_tenant, make_user
) -> None:
    """The chat stream's own persistence helper writes the row (AST-2/3)."""
    from agente_fiscal.api.routes.chat import _persist_agent_session

    async with test_session_factory() as session:
        tenant = await make_tenant(session)
        user = await make_user(session, clerk_user_id='user_1')
    app = FastAPI()
    app.state.session_factory = test_session_factory

    started = datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc)
    completed = started + timedelta(seconds=3)
    await _persist_agent_session(
        _fake_request(app),
        tool='consultaarca',
        message_id='msg-x',
        conversation_id='conv-x',
        tenant_id=tenant.id,
        profile_id=None,
        status='completed',
        tasks=build_session_tasks('consultaarca', 'completed'),
        cost_cents=0,
        session_id=None,
        started_at=started,
        completed_at=completed,
    )

    async with test_session_factory() as session:
        rows = (await session.execute(select(AgentSessionRow))).scalars().all()
    assert len(rows) == 1
    assert rows[0].tool == 'consultaarca'
    assert rows[0].tenant_id == tenant.id
    assert rows[0].user_id == user.id
    assert rows[0].profile_id is None
    assert rows[0].session_id is None
    assert rows[0].started_at == started
    assert rows[0].completed_at == completed
    assert len(rows[0].tasks) == 7


async def test_chat_persist_skips_without_factory_or_tenant(
    test_session_factory, make_tenant
) -> None:
    """Best-effort: missing factory or tenant → no row, no raise (ADR-3)."""
    from agente_fiscal.api.routes.chat import _persist_agent_session

    async with test_session_factory() as session:
        tenant = await make_tenant(session)
    app = FastAPI()  # no session_factory

    await _persist_agent_session(
        _fake_request(app),
        tool='consultaarca',
        message_id='msg-x',
        conversation_id='conv-x',
        tenant_id=tenant.id,
        profile_id=None,
        status='completed',
        tasks=[],
    )
    await _persist_agent_session(
        _fake_request(app),
        tool='consultaarca',
        message_id='msg-x',
        conversation_id='conv-x',
        tenant_id=None,
        profile_id=None,
        status='completed',
        tasks=[],
    )

    async with test_session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(AgentSessionRow))).scalar_one()
    assert count == 0


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload