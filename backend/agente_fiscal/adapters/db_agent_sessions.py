"""Postgres adapter for the agent-sessions telemetry port.

Implements :class:`agente_fiscal.ports.agent_sessions.AgentSessionsRepository`
against the ORM ``AgentSession`` row of ``agente_fiscal.db.models.business``.
Stateless and thread-safe: every call opens its own session from the injected
``async_sessionmaker`` (mirrors ``adapters/db_browser_sessions.py``).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agente_fiscal.db.conversation_repo import _ADMIN_ROLES
from agente_fiscal.db.models.business import AgentSession as AgentSessionRow
from agente_fiscal.ports.agent_sessions import AgentSession

logger = logging.getLogger(__name__)

#: Caps the API limit (query param) so a malicious client cannot over-select.
_MAX_LIMIT = 200


def _to_session(row: AgentSessionRow) -> AgentSession:
	"""Mapea una fila ORM ``AgentSession`` al contrato de dominio."""
	return AgentSession(
		id=str(row.id),
		tool=row.tool,
		message_id=row.message_id,
		conversation_id=row.conversation_id,
		profile_id=str(row.profile_id) if row.profile_id else None,
		tenant_id=str(row.tenant_id),
		user_id=str(row.user_id) if row.user_id else None,
		session_id=row.session_id,
		status=row.status,
		tasks=list(row.tasks or []),
		cost_cents=row.cost_cents or 0,
		started_at=row.started_at,
		completed_at=row.completed_at,
		created_at=row.created_at,
	)


class PostgresAgentSessionsRepository:
	"""Port concreto: telemetría de runs de agentes en Postgres (AST-1/2)."""

	def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
		self._session_factory = session_factory

	async def record(self, session: AgentSession) -> None:
		"""Persistir una fila (append-only). Raise on failure — el caller
		best-effort (chat.py) captura y loguea sin romper el stream."""
		async with self._session_factory() as db:
			row = AgentSessionRow(
				id=uuid.UUID(session.id),
				tool=session.tool,
				message_id=session.message_id,
				conversation_id=session.conversation_id,
				profile_id=uuid.UUID(session.profile_id) if session.profile_id else None,
				tenant_id=uuid.UUID(session.tenant_id),
				user_id=uuid.UUID(session.user_id) if session.user_id else None,
				session_id=session.session_id,
				status=session.status,
				tasks=session.tasks,
				cost_cents=session.cost_cents,
				started_at=session.started_at,
				completed_at=session.completed_at,
			)
			db.add(row)
			await db.commit()

	async def complete(
		self,
		session_id: str,
		*,
		status: str,
		tasks: list[dict[str, Any]],
		completed_at: datetime,
		cost_cents: int = 0,
	) -> None:
		"""Completar una fila iniciada en el dispatch (status running → terminal).

		El row ya existe (lo creó ``record`` con status ``running`` antes de que
		la tool ejecutara): esta carga por primary key (``id``) y actualiza SOLO
		``status``/``tasks``/``completed_at``/``cost_cents`` — nunca toca la
		tool, los ids de mensaje/conversación ni ``started_at``. Raise on
		failure (o si la fila no existe) — el caller best-effort (chat.py)
		captura y loguea sin romper el stream.
		"""
		async with self._session_factory() as db:
			row = await db.get(AgentSessionRow, uuid.UUID(str(session_id)))
			if row is None:
				raise ValueError(
					f'agent session {session_id} no existe — nunca se inició'
				)
			row.status = status
			row.tasks = tasks
			row.completed_at = completed_at
			row.cost_cents = cost_cents
			await db.commit()

	async def list_for(
		self,
		*,
		tenant_id: uuid.UUID,
		user_id: uuid.UUID | None,
		role: str,
		conversation_id: str | None = None,
		limit: int = 100,
	) -> list[AgentSession]:
		rows: Sequence[AgentSessionRow]
		limit = max(1, min(int(limit or 100), _MAX_LIMIT))
		stmt = select(AgentSessionRow).where(AgentSessionRow.tenant_id == tenant_id)
		if conversation_id:
			stmt = stmt.where(AgentSessionRow.conversation_id == conversation_id)
		if role not in _ADMIN_ROLES:
			if user_id is None:
				return []
			stmt = stmt.where(AgentSessionRow.user_id == user_id)
		stmt = stmt.order_by(AgentSessionRow.created_at.desc()).limit(limit)
		async with self._session_factory() as db:
			rows = (await db.execute(stmt)).scalars().all()
		return [_to_session(row) for row in rows]


__all__ = ['PostgresAgentSessionsRepository']