"""Agent-sessions telemetry router — exposes persisted tool-run telemetry.

Endpoint matches the path expected by the frontend BFF (P1b):

  - ``GET /v1/agent-sessions`` — list persisted runs, newest first (AST-6)

The rows are produced by the backend itself after every tool run (``chat.py``,
AST-2/3 — one row per engine and browser run). This endpoint is tenant-scoped
and user-scoped: owners/admins see every run of the tenant, members only their
own (same ownership contract as ``conversations.py``).

Storage is Postgres via ``ports/agent_sessions.py`` +
``adapters/db_agent_sessions.py``; the session factory comes from
``request.app.state.session_factory`` (503 when absent, like conversations).
Response keys are snake_case: the BFF layer maps them to the camelCase
``useAgentSidebar`` contract.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from agente_fiscal.adapters.db_agent_sessions import PostgresAgentSessionsRepository
from agente_fiscal.api.routes.conversations import (
	_caller_role,
	_get_session_factory,
	_tenant_uuid,
)
from agente_fiscal.db.models import User

router = APIRouter(tags=['chat'])


@router.get(
	'/v1/agent-sessions',
	status_code=200,
	summary='List agent tool-run telemetry for the tenant/user',
)
async def list_agent_sessions(
	request: Request,
	conversation_id: str | None = Query(default=None),
	limit: int = Query(default=100, ge=1, le=200),
):
	"""List persisted agent runs, newest first.

	- Owners/admins: every run of the tenant.
	- Members: only runs of their own user.
	- ``conversation_id`` filters to a single chat (chat hydrate consumes this).
	- ``limit`` caps the window (default 100, max 200). FastAPI 422s invalid
	  values before this handler runs.

	Returns a **JSON array** of AgentSession rows (snake_case keys); empty list
	when nothing matches. 503 when the store is unavailable — never a lie.
	"""
	tenant_id = _tenant_uuid(request)
	factory = _get_session_factory(request)

	async with factory() as session:
		clerk_user_id = getattr(request.state, 'clerk_user_id', None)
		user_id = None
		if clerk_user_id:
			user_id = await session.scalar(
				select(User.id).where(User.clerk_user_id == clerk_user_id).limit(1)
			)
		repo = PostgresAgentSessionsRepository(factory)
		sessions = await repo.list_for(
			tenant_id=tenant_id,
			user_id=user_id,
			role=_caller_role(request),
			conversation_id=conversation_id,
			limit=limit,
		)
	return JSONResponse(content=[s.model_dump(mode='json') for s in sessions])