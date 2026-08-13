"""Per-tenant client (CUIT) CRUD — cutover Phase 5 continuation.

Replaces the legacy Redis ``TenantStore``-backed ``/v1/admin/tenants``
endpoints (removed). A tenant (Clerk org) manages one or more clients — the
CUIT taxpayers it files fiscal reports for; ``report_runs.client_id`` already
points at this table. Auth follows the same pattern as ``report_runs.py``:
scoped by ``request.state.tenant_id`` (Clerk JWT or API key), no extra scope
check — a client is tenant-private data, not an admin-only resource.
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from agente_fiscal.domain.models import ApiError, UnifiedResponse
from agente_fiscal.ports.clients import ClientAlreadyExistsError, ClientRepository

router = APIRouter()

_CUIT_RE = re.compile(r'^\d{11}$')


class CreateClientRequest(BaseModel):
	"""Payload to register a CUIT taxpayer under the authenticated tenant."""

	cuit: str = Field(
		description='CUIT del contribuyente sin guiones (11 dígitos)',
		examples=['20301234561'],
	)
	name: str = Field(description='Nombre o razón social del cliente', examples=['Pérez SRL'])
	email: str | None = Field(default=None, description='Email de contacto del cliente')
	config: dict = Field(
		default_factory=dict,
		description='Configuración fiscal flexible (clave_fiscal, tipo, provincias, etc.)',
	)


def _require_tenant_uuid(req: Request) -> uuid.UUID:
	"""Resolve ``request.state.tenant_id`` as a UUID, or raise 401."""
	tenant_id = getattr(req.state, 'tenant_id', None)
	if tenant_id is None:
		raise HTTPException(
			status_code=401,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='UNAUTHENTICATED', cause='No se pudo resolver el tenant autenticado'),
			).model_dump(),
		)
	try:
		return uuid.UUID(str(tenant_id))
	except (ValueError, TypeError):
		raise HTTPException(
			status_code=401,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='UNAUTHENTICATED', cause='El tenant autenticado no es un UUID válido'),
			).model_dump(),
		)


@router.post(
	'/v1/clients',
	status_code=201,
	summary='Registrar un cliente (CUIT) del tenant',
	responses={
		409: {'description': 'CUIT duplicado', 'model': UnifiedResponse[ApiError]},
		422: {'description': 'CUIT inválido', 'model': UnifiedResponse[ApiError]},
	},
)
async def create_client(body: CreateClientRequest, req: Request):
	"""Crea un cliente (CUIT) bajo el tenant autenticado."""
	if not _CUIT_RE.fullmatch(body.cuit):
		raise HTTPException(
			status_code=422,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='INVALID_CUIT', cause='El CUIT debe ser exactamente 11 dígitos, sin guiones'),
			).model_dump(),
		)

	tenant_id = _require_tenant_uuid(req)
	repo: ClientRepository = req.app.state.client_repository  # type: ignore[attr-defined]

	try:
		client = await repo.create_client(
			tenant_id,
			cuit=body.cuit,
			name=body.name,
			email=body.email,
			config=body.config,
		)
	except ClientAlreadyExistsError:
		raise HTTPException(
			status_code=409,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='CLIENT_CUIT_EXISTS', cause='Ya existe un cliente con ese CUIT en este tenant'),
			).model_dump(),
		)

	return UnifiedResponse(status='success', result=client)


@router.get('/v1/clients', summary='Listar clientes (CUIT) del tenant')
async def list_clients(req: Request):
	"""Lista todos los clientes del tenant autenticado, más recientes primero."""
	tenant_id = _require_tenant_uuid(req)
	repo: ClientRepository = req.app.state.client_repository  # type: ignore[attr-defined]
	clients = await repo.list_clients(tenant_id)
	return UnifiedResponse(status='success', result=clients)


@router.get(
	'/v1/clients/{client_id}',
	summary='Obtener un cliente por ID',
	responses={404: {'description': 'No encontrado', 'model': UnifiedResponse[ApiError]}},
)
async def get_client(client_id: uuid.UUID, req: Request):
	"""Obtiene un cliente por ID, verificando que pertenezca al tenant autenticado."""
	tenant_id = _require_tenant_uuid(req)
	repo: ClientRepository = req.app.state.client_repository  # type: ignore[attr-defined]
	client = await repo.get_client(tenant_id, client_id)
	if client is None:
		raise HTTPException(
			status_code=404,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='CLIENT_NOT_FOUND', cause='No existe un cliente con ese ID para tu tenant'),
			).model_dump(),
		)
	return UnifiedResponse(status='success', result=client)


@router.delete(
	'/v1/clients/{client_id}',
	status_code=204,
	summary='Eliminar un cliente',
	responses={404: {'description': 'No encontrado', 'model': UnifiedResponse[ApiError]}},
)
async def delete_client(client_id: uuid.UUID, req: Request):
	"""Elimina un cliente, verificando que pertenezca al tenant autenticado."""
	tenant_id = _require_tenant_uuid(req)
	repo: ClientRepository = req.app.state.client_repository  # type: ignore[attr-defined]
	deleted = await repo.delete_client(tenant_id, client_id)
	if not deleted:
		raise HTTPException(
			status_code=404,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='CLIENT_NOT_FOUND', cause='No existe un cliente con ese ID para tu tenant'),
			).model_dump(),
		)
	return Response(status_code=204)
