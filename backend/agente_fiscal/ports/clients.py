"""Client (CUIT) admin port — per-tenant client CRUD (cutover Phase 5 continuation).

Replaces the legacy Redis ``TenantStore`` behind ``/v1/admin/tenants``, which
modeled a "Tenant" as a single accounting firm with its own CUIT/clave_fiscal
— a shape that doesn't fit the Postgres ``tenants`` table (a Clerk org). The
real equivalent — the CUIT taxpayers a tenant manages — already had a home in
Postgres (``clients`` table, wired to ``report_runs.client_id`` since Fase 3);
it only lacked a port/adapter/routes. This port fills that gap.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from agente_fiscal.domain.models import Client


class ClientAlreadyExistsError(Exception):
	"""Raised when a client with the same (tenant_id, cuit) already exists."""

	def __init__(self, cuit: str) -> None:
		self.cuit = cuit
		super().__init__(f'Client with CUIT {cuit} already exists for this tenant')


@runtime_checkable
class ClientRepository(Protocol):
	"""CRUD for the CUIT taxpayers ("clients") a tenant manages."""

	async def create_client(
		self,
		tenant_id: uuid.UUID,
		*,
		cuit: str,
		name: str,
		email: str | None = None,
		config: dict | None = None,
	) -> Client:
		"""Create a client under *tenant_id*. Raises :class:`ClientAlreadyExistsError`
		on a duplicate (tenant_id, cuit)."""
		...

	async def list_clients(
		self,
		tenant_id: uuid.UUID,
		*,
		limit: int = 50,
		offset: int = 0,
		q: str | None = None,
		cuit: str | None = None,
	) -> list[Client]:
		"""List clients of a tenant, newest first, with pagination and filters."""
		...

	async def count_clients(
		self,
		tenant_id: uuid.UUID,
		*,
		q: str | None = None,
		cuit: str | None = None,
	) -> int:
		"""Count clients matching the given filters for a tenant (for X-Total-Count)."""
		...

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
		"""Partial-update a client, verifying tenant ownership.

		Raises :class:`ClientAlreadyExistsError` if a new CUIT collides with an
		existing (tenant_id, cuit). Returns ``None`` if the client doesn't exist
		or belongs to another tenant.
		"""
		...

	async def get_client(self, tenant_id: uuid.UUID, client_id: uuid.UUID) -> Client | None:
		"""Fetch a client by id, scoped to *tenant_id*. ``None`` if not found/foreign."""
		...

	async def delete_client(self, tenant_id: uuid.UUID, client_id: uuid.UUID) -> bool:
		"""Delete a client, verifying tenant ownership. Returns ``False`` if not found."""
		...


__all__ = [
	'Client',
	'ClientAlreadyExistsError',
	'ClientRepository',
]
