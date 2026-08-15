"""Postgres-backed profile adapter.

Implements :class:`agente_fiscal.ports.profiles.ProfileRepository` against the
``Profile`` ORM model in ``agente_fiscal.db.models.business`` — the same table
``report_runs.profile_id`` references.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agente_fiscal.db.models.business import Profile as ProfileRow
from agente_fiscal.db.models.business import ReportRun
from agente_fiscal.domain.models import Profile
from agente_fiscal.ports.profiles import ProfileAlreadyExistsError, ProfileHasRunsError


def _to_profile(row: ProfileRow) -> Profile:
	"""Map an ORM ``Profile`` row to the pydantic domain contract."""
	return Profile(
		id=str(row.id),
		tenant_id=str(row.tenant_id),
		created_by=str(row.created_by) if row.created_by else None,
		name=row.name,
		cuit=row.cuit,
		status=row.status,
		config=row.config or {},
		created_at=row.created_at,
	)


class PostgresProfileRepository:
	"""Concrete port: per-tenant profile CRUD over Postgres.

	Accepts an ``async_sessionmaker`` (the app's ``async_session_factory``).
	Sessions are created per call, so the repository is stateless and safe to
	share across requests/workers.
	"""

	def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
		self._session_factory = session_factory

	def _normalise_status(self, status: str | None) -> str | None:
		if status is None:
			return None
		return status.strip().lower() or None

	async def create_profile(
		self,
		tenant_id: uuid.UUID,
		*,
		name: str,
		cuit: str | None = None,
		config: dict | None = None,
		created_by: uuid.UUID | None = None,
	) -> Profile:
		async with self._session_factory() as session:
			row = ProfileRow(
				tenant_id=tenant_id,
				created_by=created_by,
				name=name,
				cuit=cuit,
				status='active',
				config=config or {},
			)
			session.add(row)
			try:
				await session.commit()
			except IntegrityError as exc:
				await session.rollback()
				raise ProfileAlreadyExistsError(cuit or '') from exc
			await session.refresh(row)
			return _to_profile(row)

	async def list_profiles(
		self,
		tenant_id: uuid.UUID,
		*,
		limit: int = 50,
		offset: int = 0,
		status: str | None = None,
	) -> list[Profile]:
		async with self._session_factory() as session:
			stmt = select(ProfileRow).where(ProfileRow.tenant_id == tenant_id)
			status = self._normalise_status(status)
			if status:
				stmt = stmt.where(ProfileRow.status == status)
			stmt = stmt.order_by(ProfileRow.created_at.desc()).limit(limit).offset(offset)
			rows = (await session.execute(stmt)).scalars().all()
			return [_to_profile(r) for r in rows]

	async def count_profiles(
		self,
		tenant_id: uuid.UUID,
		*,
		status: str | None = None,
	) -> int:
		async with self._session_factory() as session:
			stmt = select(func.count()).select_from(ProfileRow).where(
				ProfileRow.tenant_id == tenant_id
			)
			status = self._normalise_status(status)
			if status:
				stmt = stmt.where(ProfileRow.status == status)
			return int((await session.execute(stmt)).scalar_one())

	async def update_profile(
		self,
		tenant_id: uuid.UUID,
		profile_id: uuid.UUID,
		*,
		name: str | None = None,
		cuit: str | None = None,
		status: str | None = None,
		config: dict | None = None,
	) -> Profile | None:
		async with self._session_factory() as session:
			row = await session.get(ProfileRow, profile_id)
			if row is None or row.tenant_id != tenant_id:
				return None
			if name is not None:
				row.name = name
			if cuit is not None:
				row.cuit = cuit or None
			if status is not None:
				row.status = self._normalise_status(status) or row.status
			if config is not None:
				row.config = config
			try:
				await session.commit()
			except IntegrityError as exc:
				await session.rollback()
				raise ProfileAlreadyExistsError(cuit or '') from exc
			await session.refresh(row)
			return _to_profile(row)

	async def get_profile(self, tenant_id: uuid.UUID, profile_id: uuid.UUID) -> Profile | None:
		async with self._session_factory() as session:
			row = await session.get(ProfileRow, profile_id)
			if row is None or row.tenant_id != tenant_id:
				return None
			return _to_profile(row)

	async def delete_profile(self, tenant_id: uuid.UUID, profile_id: uuid.UUID) -> bool:
		async with self._session_factory() as session:
			row = await session.get(ProfileRow, profile_id)
			if row is None or row.tenant_id != tenant_id:
				return False
			ref = await session.scalar(
				select(ReportRun.id).where(ReportRun.profile_id == profile_id).limit(1)
			)
			if ref is not None:
				raise ProfileHasRunsError()
			await session.delete(row)
			await session.commit()
			return True


__all__ = ['PostgresProfileRepository']