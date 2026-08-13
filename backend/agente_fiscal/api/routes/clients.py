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

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from agente_fiscal.domain.cuit import is_valid_cuit
from agente_fiscal.domain.models import ApiError, UnifiedResponse
from agente_fiscal.ports.clients import ClientAlreadyExistsError, ClientRepository

router = APIRouter()

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


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


class UpdateClientRequest(BaseModel):
	"""Partial-update payload — every field optional, at least one required."""

	cuit: str | None = Field(
		default=None,
		description='CUIT del contribuyente sin guiones (11 dígitos, checksum válido)',
	)
	name: str | None = Field(default=None, description='Nombre o razón social del cliente')
	email: str | None = Field(default=None, description='Email de contacto del cliente')
	config: dict | None = Field(default=None, description='Configuración fiscal flexible')


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


def _invalid_cuit() -> HTTPException:
	"""Build the canonical 422 for a malformed CUIT."""
	return HTTPException(
		status_code=422,
		detail=UnifiedResponse(
			status='error',
			error=ApiError(
				code='INVALID_CUIT',
				cause='El CUIT debe ser exactamente 11 dígitos con dígito verificador válido',
			),
		).model_dump(),
	)


def _invalid_email() -> HTTPException:
	"""Build the canonical 422 for a malformed email."""
	return HTTPException(
		status_code=422,
		detail=UnifiedResponse(
			status='error',
			error=ApiError(
				code='INVALID_EMAIL',
				cause='El email debe tener un formato válido (ej: ana@acme.io)',
			),
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
	if not is_valid_cuit(body.cuit):
		raise _invalid_cuit()
	if body.email and not _EMAIL_RE.fullmatch(body.email):
		raise _invalid_email()

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
async def list_clients(
	req: Request,
	limit: int = Query(default=50, ge=1, le=200, description='Cantidad máxima de resultados'),
	offset: int = Query(default=0, ge=0, description='Desplazamiento para paginar'),
	q: str | None = Query(default=None, description='Filtro por nombre (ILIKE contiene)'),
	cuit: str | None = Query(default=None, description='Filtro por CUIT exacto'),
):
	"""Lista los clientes del tenant autenticado, más recientes primero."""
	tenant_id = _require_tenant_uuid(req)
	repo: ClientRepository = req.app.state.client_repository  # type: ignore[attr-defined]
	total = await repo.count_clients(tenant_id, q=q, cuit=cuit)
	clients = await repo.list_clients(tenant_id, limit=limit, offset=offset, q=q, cuit=cuit)
	resp = Response(
		content=UnifiedResponse(status='success', result=clients).model_dump_json(),
		media_type='application/json',
	)
	resp.headers['X-Total-Count'] = str(total)
	return resp


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


@router.patch(
	'/v1/clients/{client_id}',
	summary='Actualizar parcialmente un cliente',
	responses={
		404: {'description': 'No encontrado', 'model': UnifiedResponse[ApiError]},
		409: {'description': 'CUIT duplicado', 'model': UnifiedResponse[ApiError]},
		422: {'description': 'Payload vacío o validación fallida', 'model': UnifiedResponse[ApiError]},
	},
)
async def update_client(client_id: uuid.UUID, body: UpdateClientRequest, req: Request):
	"""Actualiza parcialmente un cliente del tenant autenticado."""
	fields = body.model_dump(exclude_unset=True)
	if not fields:
		raise HTTPException(
			status_code=422,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(
					code='EMPTY_UPDATE',
					cause='Debés enviar al menos un campo a actualizar (cuit, name, email o config)',
				),
			).model_dump(),
		)
	if 'cuit' in fields:
		if not is_valid_cuit(body.cuit):
			raise _invalid_cuit()
	if 'email' in fields and body.email and not _EMAIL_RE.fullmatch(body.email):
		raise _invalid_email()

	tenant_id = _require_tenant_uuid(req)
	repo: ClientRepository = req.app.state.client_repository  # type: ignore[attr-defined]

	try:
		client = await repo.update_client(
			tenant_id,
			client_id,
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
