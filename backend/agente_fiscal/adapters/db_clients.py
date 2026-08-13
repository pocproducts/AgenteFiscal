"""Postgres-backed client (CUIT) adapter (cutover Phase 5 continuation).

Implements :class:`agente_fiscal.ports.clients.ClientRepository` against the
``Client`` ORM model in ``agente_fiscal.db.models.business`` — the same table
``report_runs.client_id`` already references.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agente_fiscal.db.models.business import Client as ClientRow
from agente_fiscal.domain.models import Client
from agente_fiscal.ports.clients import ClientAlreadyExistsError


def _to_client(row: ClientRow) -> Client:
	"""Map an ORM ``Client`` row to the pydantic domain contract."""
	return Client(
		id=str(row.id),
		tenant_id=str(row.tenant_id),
		cuit=row.cuit,
		name=row.name,
		email=row.email,
		config=row.config or {},
		created_at=row.created_at,
	)


class PostgresClientRepository:
	"""Concrete port: per-tenant client (CUIT) CRUD over Postgres.

	Accepts an ``async_sessionmaker`` (the app's ``async_session_factory``).
	Sessions are created per call, so the repository is stateless and safe to
	share across requests/workers.
	"""

	def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
		self._session_factory = session_factory

	async def create_client(
		self,
		tenant_id: uuid.UUID,
		*,
		cuit: str,
		name: str,
		email: str | None = None,
		config: dict | None = None,
	) -> Client:
		async with self._session_factory() as session:
			row = ClientRow(
				tenant_id=tenant_id,
				cuit=cuit,
				name=name,
				email=email,
				config=config or {},
			)
			session.add(row)
			try:
				await session.commit()
			except IntegrityError as exc:
				await session.rollback()
				raise ClientAlreadyExistsError(cuit) from exc
			await session.refresh(row)
			return _to_client(row)

	async def list_clients(
		self,
		tenant_id: uuid.UUID,
		*,
		limit: int = 50,
		offset: int = 0,
		q: str | None = None,
		cuit: str | None = None,
	) -> list[Client]:
		async with self._session_factory() as session:
			stmt = select(ClientRow).where(ClientRow.tenant_id == tenant_id)
			if q:
				stmt = stmt.where(ClientRow.name.ilike(f'%{q}%'))
			if cuit:
				stmt = stmt.where(ClientRow.cuit == cuit)
			stmt = stmt.order_by(ClientRow.created_at.desc()).limit(limit).offset(offset)
			rows = (await session.execute(stmt)).scalars().all()
			return [_to_client(r) for r in rows]

	async def count_clients(
		self,
		tenant_id: uuid.UUID,
		*,
		q: str | None = None,
		cuit: str | None = None,
	) -> int:
		async with self._session_factory() as session:
			stmt = select(func.count()).select_from(ClientRow).where(
				ClientRow.tenant_id == tenant_id
			)
			if q:
				stmt = stmt.where(ClientRow.name.ilike(f'%{q}%'))
			if cuit:
				stmt = stmt.where(ClientRow.cuit == cuit)
			return int((await session.execute(stmt)).scalar_one())

	async def update_client(
		self,
		tenant_id: uuid.UUID,
		client_id: uuid.UUID,
		*,
		cuit: str | None = None,
		name: str | None = None,
		email: str | None = None,
		config: dict | None = None,
	) -> Client | None:
		async with self._session_factory() as session:
			row = await session.get(ClientRow, client_id)
			if row is None or row.tenant_id != tenant_id:
				return None
			if cuit is not None:
				row.cuit = cuit
			if name is not None:
				row.name = name
			if email is not None:
				row.email = email
			if config is not None:
				row.config = config
			try:
				await session.commit()
			except IntegrityError as exc:
				await session.rollback()
				raise ClientAlreadyExistsError(cuit or '') from exc
			await session.refresh(row)
			return _to_client(row)

	async def get_client(self, tenant_id: uuid.UUID, client_id: uuid.UUID) -> Client | None:
		async with self._session_factory() as session:
			row = await session.get(ClientRow, client_id)
			if row is None or row.tenant_id != tenant_id:
				return None
			return _to_client(row)

	async def delete_client(self, tenant_id: uuid.UUID, client_id: uuid.UUID) -> bool:
		async with self._session_factory() as session:
			row = await session.get(ClientRow, client_id)
			if row is None or row.tenant_id != tenant_id:
				return False
			await session.delete(row)
			await session.commit()
			return True


__all__ = ['PostgresClientRepository']
