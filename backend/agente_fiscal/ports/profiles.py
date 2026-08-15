"""Profile admin port — per-tenant profile CRUD.

A profile is a first-class, tenant-scoped system identity that aggregates
reports, token spend and activity (future per-profile storage). It is NOT a
fiscal ``Client`` (the CUIT taxpayer a report is filed for) and NOT a browser
mock. Invariant enforced at the API boundary: NO report generation without an
ACTIVE profile belonging to the current tenant.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from agente_fiscal.domain.models import Profile


class ProfileAlreadyExistsError(Exception):
	"""Raised when a profile with the same (tenant_id, cuit) already exists."""

	def __init__(self, cuit: str) -> None:
		self.cuit = cuit
		super().__init__(f'Profile with CUIT {cuit} already exists for this tenant')


class ProfileHasRunsError(Exception):
	"""Raised when a profile is referenced by ``report_runs`` rows (delete blocked)."""


@runtime_checkable
class ProfileRepository(Protocol):
	"""CRUD for the tenant-scoped ``profiles`` identities."""

	async def create_profile(
		self,
		tenant_id: uuid.UUID,
		*,
		name: str,
		cuit: str | None = None,
		config: dict | None = None,
		created_by: uuid.UUID | None = None,
	) -> Profile:
		"""Create a profile under *tenant_id*. Raises :class:`ProfileAlreadyExistsError`
		on a duplicate (tenant_id, cuit)."""
		...

	async def list_profiles(
		self,
		tenant_id: uuid.UUID,
		*,
		limit: int = 50,
		offset: int = 0,
		status: str | None = None,
	) -> list[Profile]:
		"""List profiles of a tenant, newest first, with pagination and status filter."""
		...

	async def count_profiles(
		self,
		tenant_id: uuid.UUID,
		*,
		status: str | None = None,
	) -> int:
		"""Count profiles matching the given filters for a tenant (for X-Total-Count)."""
		...

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
		"""Partial-update a profile, verifying tenant ownership.

		Raises :class:`ProfileAlreadyExistsError` if a new CUIT collides with an
		existing (tenant_id, cuit). Returns ``None`` if the profile doesn't exist
		or belongs to another tenant.
		"""
		...

	async def get_profile(self, tenant_id: uuid.UUID, profile_id: uuid.UUID) -> Profile | None:
		"""Fetch a profile by id, scoped to *tenant_id*. ``None`` if not found/foreign."""
		...

	async def delete_profile(self, tenant_id: uuid.UUID, profile_id: uuid.UUID) -> bool:
		"""Delete a profile, verifying tenant ownership.

		Raises :class:`ProfileHasRunsError` when ``report_runs`` reference it
		(their FK is ``RESTRICT`` — the profile must be kept for its audit trail).
		Returns ``False`` if the profile doesn't exist.
		"""
		...


__all__ = [
	'Profile',
	'ProfileAlreadyExistsError',
	'ProfileHasRunsError',
	'ProfileRepository',
]