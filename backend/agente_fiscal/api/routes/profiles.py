"""Per-tenant profile CRUD — first-class system identity.

A profile aggregates reports, token spend and activity for a tenant (future
per-profile storage). NOT a fiscal ``Client`` and NOT a browser mock. Auth
follows the same pattern as ``clients.py``: scoped by ``request.state.tenant_id``
(Clerk JWT or API key) — a profile is tenant-private data.

Invariant enforced at the API boundary (all report-generation paths):
NO report generation without an ACTIVE profile belonging to the tenant.
``DELETE`` is blocked with ``409 PROFILE_HAS_RUNS`` while any ``report_runs``
row references the profile (their FK is ``RESTRICT``).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agente_fiscal.api.deps import get_db_session
from agente_fiscal.db.models import User
from agente_fiscal.domain.cuit import is_valid_cuit
from agente_fiscal.domain.models import ApiError, UnifiedResponse
from agente_fiscal.ports.profiles import ProfileAlreadyExistsError, ProfileHasRunsError, ProfileRepository

router = APIRouter()

_VALID_STATUSES = frozenset({'active', 'inactive'})


class CreateProfileRequest(BaseModel):
	"""Payload to register a profile under the authenticated tenant."""

	name: str = Field(description='Nombre del perfil', examples=['Estudio Pérez — Principal'])
	cuit: str | None = Field(
		default=None,
		description='CUIT asociado al perfil sin guiones (11 dígitos, checksum válido)',
		examples=['20301234561'],
	)
	config: dict = Field(
		default_factory=dict,
		description='Configuración flexible del perfil (futuro storage por perfil)',
	)


class UpdateProfileRequest(BaseModel):
	"""Partial-update payload — every field optional, at least one required."""

	name: str | None = Field(default=None, description='Nombre del perfil')
	cuit: str | None = Field(
		default=None,
		description='CUIT asociado al perfil sin guiones (11 dígitos, checksum válido)',
	)
	status: str | None = Field(
		default=None,
		description="Estado del perfil: 'active' o 'inactive' (inactive bloquea reportes)",
	)
	config: dict | None = Field(default=None, description='Configuración flexible del perfil')


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


async def _resolve_created_by(req: Request, session: AsyncSession) -> uuid.UUID | None:
	"""Resolve the ORM user id for ``request.state.clerk_user_id`` (``None`` if absent)."""
	clerk_user_id = getattr(req.state, 'clerk_user_id', None)
	if not clerk_user_id:
		return None
	user_id = await session.scalar(
		select(User.id).where(User.clerk_user_id == clerk_user_id).limit(1)
	)
	return user_id


def _not_found() -> HTTPException:
	return HTTPException(
		status_code=404,
		detail=UnifiedResponse(
			status='error',
			error=ApiError(
				code='PROFILE_NOT_FOUND',
				cause='No existe un perfil con ese ID para tu tenant',
			),
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


def _invalid_status() -> HTTPException:
	"""Build the canonical 422 for a malformed status."""
	return HTTPException(
		status_code=422,
		detail=UnifiedResponse(
			status='error',
			error=ApiError(
				code='INVALID_PROFILE_STATUS',
				cause="El estado debe ser 'active' o 'inactive'",
			),
		).model_dump(),
	)


@router.post(
	'/v1/profiles',
	status_code=201,
	summary='Crear un perfil del tenant',
	responses={
		409: {'description': 'CUIT duplicado', 'model': UnifiedResponse[ApiError]},
		422: {'description': 'CUIT inválido', 'model': UnifiedResponse[ApiError]},
	},
)
async def create_profile(
	body: CreateProfileRequest,
	req: Request,
	session: AsyncSession = Depends(get_db_session),
):
	"""Crea un perfil bajo el tenant autenticado (siempre estado ``active``)."""
	if body.cuit is not None and not is_valid_cuit(body.cuit):
		raise _invalid_cuit()

	tenant_id = _require_tenant_uuid(req)
	repo: ProfileRepository = req.app.state.profile_repository  # type: ignore[attr-defined]
	created_by = await _resolve_created_by(req, session)

	try:
		profile = await repo.create_profile(
			tenant_id,
			name=body.name,
			cuit=body.cuit,
			config=body.config,
			created_by=created_by,
		)
	except ProfileAlreadyExistsError:
		raise HTTPException(
			status_code=409,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='PROFILE_CUIT_EXISTS', cause='Ya existe un perfil con ese CUIT en este tenant'),
			).model_dump(),
		)

	return UnifiedResponse(status='success', result=profile)


@router.get('/v1/profiles', summary='Listar perfiles del tenant')
async def list_profiles(
	req: Request,
	limit: int = Query(default=50, ge=1, le=200, description='Cantidad máxima de resultados'),
	offset: int = Query(default=0, ge=0, description='Desplazamiento para paginar'),
	status: str | None = Query(default=None, description="Filtro por estado: 'active' o 'inactive'"),
):
	"""Lista los perfiles del tenant autenticado, más recientes primero."""
	tenant_id = _require_tenant_uuid(req)
	repo: ProfileRepository = req.app.state.profile_repository  # type: ignore[attr-defined]
	total = await repo.count_profiles(tenant_id, status=status)
	profiles = await repo.list_profiles(tenant_id, limit=limit, offset=offset, status=status)
	resp = Response(
		content=UnifiedResponse(status='success', result=profiles).model_dump_json(),
		media_type='application/json',
	)
	resp.headers['X-Total-Count'] = str(total)
	return resp


@router.get(
	'/v1/profiles/{profile_id}',
	summary='Obtener un perfil por ID',
	responses={404: {'description': 'No encontrado', 'model': UnifiedResponse[ApiError]}},
)
async def get_profile(profile_id: uuid.UUID, req: Request):
	"""Obtiene un perfil por ID, verificando que pertenezca al tenant autenticado."""
	tenant_id = _require_tenant_uuid(req)
	repo: ProfileRepository = req.app.state.profile_repository  # type: ignore[attr-defined]
	profile = await repo.get_profile(tenant_id, profile_id)
	if profile is None:
		raise _not_found()
	return UnifiedResponse(status='success', result=profile)


@router.patch(
	'/v1/profiles/{profile_id}',
	summary='Actualizar parcialmente un perfil',
	responses={
		404: {'description': 'No encontrado', 'model': UnifiedResponse[ApiError]},
		409: {'description': 'CUIT duplicado', 'model': UnifiedResponse[ApiError]},
		422: {'description': 'Payload vacío o validación fallida', 'model': UnifiedResponse[ApiError]},
	},
)
async def update_profile(profile_id: uuid.UUID, body: UpdateProfileRequest, req: Request):
	"""Actualiza parcialmente un perfil del tenant autenticado."""
	fields = body.model_dump(exclude_unset=True)
	if not fields:
		raise HTTPException(
			status_code=422,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(
					code='EMPTY_UPDATE',
					cause='Debés enviar al menos un campo a actualizar (name, cuit, status o config)',
				),
			).model_dump(),
		)
	if 'cuit' in fields and body.cuit is not None and not is_valid_cuit(body.cuit):
		raise _invalid_cuit()
	if 'status' in fields and (not body.status or body.status.strip().lower() not in _VALID_STATUSES):
		raise _invalid_status()

	tenant_id = _require_tenant_uuid(req)
	repo: ProfileRepository = req.app.state.profile_repository  # type: ignore[attr-defined]

	try:
		profile = await repo.update_profile(
			tenant_id,
			profile_id,
			name=body.name,
			cuit=body.cuit,
			status=body.status,
			config=body.config,
		)
	except ProfileAlreadyExistsError:
		raise HTTPException(
			status_code=409,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='PROFILE_CUIT_EXISTS', cause='Ya existe un perfil con ese CUIT en este tenant'),
			).model_dump(),
		)
	if profile is None:
		raise _not_found()
	return UnifiedResponse(status='success', result=profile)


@router.delete(
	'/v1/profiles/{profile_id}',
	status_code=204,
	summary='Eliminar un perfil',
	responses={
		404: {'description': 'No encontrado', 'model': UnifiedResponse[ApiError]},
		409: {'description': 'El perfil tiene corridas asociadas', 'model': UnifiedResponse[ApiError]},
	},
)
async def delete_profile(profile_id: uuid.UUID, req: Request):
	"""Elimina un perfil, verificando que pertenezca al tenant autenticado.

	Bloqueado con ``409 PROFILE_HAS_RUNS`` mientras existan ``report_runs`` que
	lo referencien (FK ``RESTRICT``) para conservar su audit trail.
	"""
	tenant_id = _require_tenant_uuid(req)
	repo: ProfileRepository = req.app.state.profile_repository  # type: ignore[attr-defined]
	try:
		deleted = await repo.delete_profile(tenant_id, profile_id)
	except ProfileHasRunsError:
		raise HTTPException(
			status_code=409,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(
					code='PROFILE_HAS_RUNS',
					cause='El perfil tiene corridas de reporte asociadas y no puede eliminarse',
					remediation='Marcalo como "inactive" en lugar de eliminarlo',
				),
			).model_dump(),
		)
	if not deleted:
		raise _not_found()
	return Response(status_code=204)