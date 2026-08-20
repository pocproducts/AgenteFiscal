"""Agent-sessions telemetry port — persisted rows for one agent tool run.

Owns ``agent_sessions`` (AST-1): the backend writes ONE row per tool run
(engine + browser) after execution completes (ADR-3), never from provider
callbacks. The chat stream and the ``GET /v1/agent-sessions`` API consume the
port; concrete persistence lives in ``adapters/db_agent_sessions.py``.

Coexists with ``browser_sessions`` (ADR-1): this port is user-facing telemetry
(Acciones/Comenzó/Duración), the other is infra state (context reuse,
active↔in_use, expires). Both are written on Browserbase runs, different
concerns.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class AgentSession(BaseModel):
    """Domain contract of a persisted agent-session row (no ORM leak)."""

    id: str
    tool: str
    message_id: str | None = None
    conversation_id: str | None = None
    profile_id: str | None = None
    tenant_id: str
    user_id: str | None = None
    session_id: str | None = None
    status: str = 'completed'
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    cost_cents: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None


@runtime_checkable
class AgentSessionsRepository(Protocol):
    """Append-only telemetry store for agent tool runs (AST-2)."""

    async def record(self, session: AgentSession) -> None:
        """Persist one session row (one row per tool run, post-execution)."""
        ...

    async def list_for(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None,
        role: str,
        conversation_id: str | None = None,
        limit: int = 100,
    ) -> list[AgentSession]:
        """List rows for the tenant, newest first.

        Ownership mirrors the conversation repo: ``owner``/``admin`` see every
        row of the tenant, ``member`` only their own (``user_id``). Pass
        ``conversation_id`` to scope to one chat. Returns at most ``limit``.
        """
        ...


__all__ = ['AgentSession', 'AgentSessionsRepository']