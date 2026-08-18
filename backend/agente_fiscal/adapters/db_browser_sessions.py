"""Adaptador Postgres del store de sesiones de browser.

Implementa :class:`agente_fiscal.ports.browser_sessions.BrowserSessionsRepository`
contra el modelo ORM ``BrowserSession`` de ``agente_fiscal.db.models.business``.
La fila única activa por (tenant, profile, provider) cicla ``active ↔ in_use``
exactamente como el claim atómico de ``worker.runner.claim_next_queued``:
``SELECT ... FOR UPDATE SKIP LOCKED`` dentro de una transacción para que dos
tools concurrentes no doble-claimen el mismo contexto persistido de
Browserbase.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agente_fiscal.db.models.business import BrowserSession as BrowserSessionRow
from agente_fiscal.ports.browser_sessions import BrowserSession


def _to_session(row: BrowserSessionRow) -> BrowserSession:
	"""Mapea una fila ORM ``BrowserSession`` al contrato de dominio."""
	return BrowserSession(
		id=str(row.id),
		tenant_id=str(row.tenant_id),
		profile_id=str(row.profile_id) if row.profile_id else None,
		provider=row.provider,
		context_id=row.context_id,
		status=row.status,
		session_id=row.session_id,
		proxy_bytes=row.proxy_bytes,
		duration_ms=row.duration_ms,
		cost_cents=row.cost_cents,
		started_at=row.started_at,
		ended_at=row.ended_at,
		last_used_at=row.last_used_at,
		expires_at=row.expires_at,
		created_at=row.created_at,
	)


class PostgresBrowserSessionsRepository:
	"""Port concreto: ciclo de vida + métricas de sesiones de browser en Postgres.

	Recibe un ``async_sessionmaker`` (el ``async_session_factory`` de la app).
	Las sesiones se crean por llamada, así que el repositorio es stateless y
	seguro de compartir entre requests/workers.
	"""

	def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
		self._session_factory = session_factory

	async def acquire(
		self,
		tenant_id: uuid.UUID,
		profile_id: uuid.UUID | None,
		*,
		provider: str,
	) -> BrowserSession | None:
		async with self._session_factory() as session:
			now = datetime.now(timezone.utc)
			stmt = (
				select(BrowserSessionRow)
				.where(
					BrowserSessionRow.tenant_id == tenant_id,
					BrowserSessionRow.profile_id == profile_id,
					BrowserSessionRow.provider == provider,
					BrowserSessionRow.status == 'active',
					((BrowserSessionRow.expires_at.is_(None)) | (BrowserSessionRow.expires_at > now)),
				)
				.order_by(BrowserSessionRow.updated_at.desc())
				.limit(1)
				.with_for_update(skip_locked=True)
			)
			row = (await session.execute(stmt)).scalar_one_or_none()
			if row is None:
				return None
			row.status = 'in_use'
			await session.commit()
			return _to_session(row)

	async def create(
		self,
		*,
		tenant_id: uuid.UUID,
		profile_id: uuid.UUID | None,
		provider: str,
		context_id: str,
		expires_at: datetime | None,
	) -> BrowserSession:
		async with self._session_factory() as session:
			row = BrowserSessionRow(
				tenant_id=tenant_id,
				profile_id=profile_id,
				provider=provider,
				context_id=context_id,
				status='in_use',
				expires_at=expires_at,
				last_used_at=datetime.now(timezone.utc),
			)
			session.add(row)
			await session.commit()
			await session.refresh(row)
			return _to_session(row)

	async def release(
		self,
		*,
		id: uuid.UUID,
		context_id: str | None = None,
		status: str = 'active',
		session_id: str | None = None,
		proxy_bytes: int | None = None,
		duration_ms: int | None = None,
		cost_cents: int | None = None,
		started_at: datetime | None = None,
		ended_at: datetime | None = None,
		last_used_at: datetime | None = None,
		expires_at: datetime | None = None,
	) -> BrowserSession | None:
		async with self._session_factory() as session:
			row = await session.get(BrowserSessionRow, id)
			if row is None:
				return None
			row.status = status
			if context_id is not None:
				row.context_id = context_id
			if session_id is not None:
				row.session_id = session_id
			if proxy_bytes is not None:
				row.proxy_bytes = proxy_bytes
			if duration_ms is not None:
				row.duration_ms = duration_ms
			if cost_cents is not None:
				row.cost_cents = cost_cents
			if started_at is not None:
				row.started_at = started_at
			if ended_at is not None:
				row.ended_at = ended_at
			if last_used_at is not None:
				row.last_used_at = last_used_at
			if expires_at is not None:
				row.expires_at = expires_at
			await session.commit()
			await session.refresh(row)
			return _to_session(row)


__all__ = ['PostgresBrowserSessionsRepository']