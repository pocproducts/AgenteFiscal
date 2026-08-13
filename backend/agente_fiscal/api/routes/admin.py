"""Admin endpoints for developer self-service.

Endpoints use ``request.state`` populated by the auth middleware. The
dev/app/key CRUD is Postgres-backed through the hexagonal ``ApiKeyRepository``
port. Legacy tenant admin CRUD (``/v1/admin/tenants``, Redis ``TenantStore``)
was removed in cutover Phase 5 — see ``routes/clients.py`` for its real
equivalent (per-tenant CUIT client CRUD).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from agente_fiscal.domain.models import ApiError, App, Developer, UnifiedResponse
from agente_fiscal.ports.api_keys import ApiKeyRepository

router = APIRouter()


# ── Auth helpers ─────────────────────────────────────────────────────


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


def _require_developer(req: Request) -> Developer:
	"""Resolve ``request.state.developer`` (developer self-service surface), or raise 401."""
	developer = getattr(req.state, 'developer', None)
	if developer is None or not getattr(developer, 'id', None):
		raise HTTPException(
			status_code=401,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='UNAUTHENTICATED', cause='No se pudo resolver el desarrollador autenticado'),
			).model_dump(),
		)
	try:
		uuid.UUID(str(developer.id))
	except (ValueError, TypeError):
		raise HTTPException(
			status_code=401,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='UNAUTHENTICATED', cause='El desarrollador autenticado no es un UUID válido'),
			).model_dump(),
		)
	return developer


# ── Request / Response models ───────────────────────────────────────


class RegisterRequest(BaseModel):
	"""Solicitud de registro de nuevo desarrollador."""

	name: str = Field(
		description='Nombre completo del desarrollador o estudio',
		examples=['Estudio Contable Pérez'],
	)
	email: str = Field(
		description='Correo electrónico del desarrollador',
		examples=['contacto@estudioperez.com'],
	)


class CreateAppRequest(BaseModel):
	"""Solicitud de creación de nueva aplicación (developer_id from auth)."""

	name: str = Field(
		description='Nombre de la aplicación',
		examples=['Sistema de Gestión Pérez'],
	)
	environment: str = Field(
		default='sandbox',
		description='Entorno: "sandbox" para pruebas, "production" para producción',
		examples=['sandbox', 'production'],
	)


class CreateKeyRequest(BaseModel):
	"""Solicitud de generación de API key."""

	app_id: str = Field(
		description='ID de la aplicación',
		examples=['a1b2c3d4e5f6'],
	)


class CreateApiKeyRequest(BaseModel):
	"""Solicitud de generación de API key desde Clerk (tenant-scoped)."""

	scopes: list[str] | None = Field(
		default=None,
		description='Scopes opcionales para la key (deben ser subset del plan)',
		examples=[['chat:read', 'chat:write']],
	)
	expires_at: datetime | None = Field(
		default=None,
		description='Fecha de expiración opcional (ISO-8601). Si queda en el pasado, la key deja de resolver.',
		examples=['2026-12-31T23:59:59Z'],
	)


class UpdateApiKeyRequest(BaseModel):
	"""Solicitud de actualización parcial de una API key del tenant.

	Todos los campos son opcionales; al menos uno debe enviarse.
	"""

	name: str | None = Field(
		default=None,
		description='Nuevo nombre descriptivo para la key',
		examples=['Integración producción'],
	)
	scopes: list[str] | None = Field(
		default=None,
		description='Scopes actualizados (deben ser subset del plan)',
		examples=[['chat:read']],
	)
	is_active: bool | None = Field(
		default=None,
		description='Reactivar (true) o desactivar (false) la key',
		examples=[True],
	)
	expires_at: datetime | None = Field(
		default=None,
		description='Nueva fecha de expiración; enviar null para limpiar',
		examples=['2026-12-31T23:59:59Z'],
	)


# ── Endpoints ───────────────────────────────────────────────────────


@router.post(
	'/v1/admin/register',
	status_code=201,
	summary='Registrar nuevo desarrollador con app y API key',
	responses={
		409: {'description': 'Email ya registrado', 'model': UnifiedResponse[ApiError]},
	},
)
async def register(body: RegisterRequest, req: Request):
	"""Registra un nuevo desarrollador con una app por defecto y una API key."""
	repo: ApiKeyRepository = req.app.state.api_key_port  # type: ignore[attr-defined]

	# Check duplicate email
	existing = await repo.get_developer_by_email(body.email)
	if existing:
		raise HTTPException(
			status_code=409,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='EMAIL_ALREADY_EXISTS', cause='El email ya está registrado'),
			).model_dump(),
		)

	dev = await repo.register_developer(name=body.name, email=body.email)

	# Create default app
	app = await repo.create_app(dev.id, 'Default App', 'sandbox')
	if app is None:
		raise HTTPException(
			status_code=400,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(
					code='APP_CREATION_FAILED', cause='No se pudo crear la aplicación. Verificá que el desarrollador exista.'
				),
			).model_dump(),
		)

	# Create API key for the default app
	key_result = await repo.create_api_key(app.id)
	if key_result is None:
		raise HTTPException(
			status_code=400,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(
					code='KEY_CREATION_FAILED', cause='No se pudo generar la API key para la aplicación creada.'
				),
			).model_dump(),
		)

	return UnifiedResponse(
		status='success',
		result={
			'developer': dev,
			'app': app,
			'api_key': key_result['api_key'],
			'full_key': key_result['full_key'],
		},
	)


@router.post(
	'/v1/admin/apps',
	response_model=UnifiedResponse[App],
	summary='Crear nueva aplicación (para el desarrollador autenticado)',
	responses={
		400: {'description': 'Error de creación', 'model': UnifiedResponse[ApiError]},
	},
)
async def create_app_endpoint(body: CreateAppRequest, req: Request):
	"""Crea una nueva aplicación para el desarrollador autenticado."""
	repo: ApiKeyRepository = req.app.state.api_key_port  # type: ignore[attr-defined]
	developer = _require_developer(req)

	app = await repo.create_app(developer.id, body.name, body.environment)
	if app is None:
		raise HTTPException(
			status_code=400,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(
					code='APP_CREATION_FAILED', cause='No se pudo crear la aplicación. Verificá que el desarrollador exista.'
				),
			).model_dump(),
		)

	return UnifiedResponse(status='success', result=app)


@router.post(
	'/v1/admin/keys',
	response_model=UnifiedResponse[dict],
	summary='Generar nueva API key',
	responses={
		404: {'description': 'App no encontrada', 'model': UnifiedResponse[ApiError]},
	},
)
async def create_key(body: CreateKeyRequest, req: Request):
	"""Genera una nueva API key para una app del desarrollador autenticado."""
	repo: ApiKeyRepository = req.app.state.api_key_port  # type: ignore[attr-defined]
	developer = _require_developer(req)

	# Check app ownership
	app = await repo.get_app(body.app_id)
	if app is None:
		raise HTTPException(
			status_code=404,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='APP_NOT_FOUND', cause='App no encontrada'),
			).model_dump(),
		)
	if app.developer_id != developer.id:
		raise HTTPException(
			status_code=404,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='APP_NOT_FOUND', cause='App no encontrada'),
			).model_dump(),
		)

	result = await repo.create_api_key(body.app_id)
	if result is None:
		raise HTTPException(
			status_code=404,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='APP_NOT_FOUND', cause='App no encontrada'),
			).model_dump(),
		)

	return UnifiedResponse(
		status='success',
		result={
			'api_key': result['api_key'],
			'full_key': result['full_key'],
			'warning': 'Guardá esta key — no se mostrará nuevamente',
		},
	)


@router.get(
	'/v1/admin/apps',
	response_model=UnifiedResponse[list[App]],
	summary='Listar aplicaciones del desarrollador autenticado',
)
async def list_apps(req: Request):
	"""Lista todas las aplicaciones del desarrollador autenticado."""
	repo: ApiKeyRepository = req.app.state.api_key_port  # type: ignore[attr-defined]
	developer = _require_developer(req)
	apps = await repo.list_apps(developer.id)
	return UnifiedResponse(status='success', result=apps)


@router.get(
	'/v1/admin/keys',
	summary='Listar API keys del desarrollador autenticado',
)
async def list_keys(req: Request):
	"""Lista todas las API keys del desarrollador autenticado (todos los apps)."""
	repo: ApiKeyRepository = req.app.state.api_key_port  # type: ignore[attr-defined]
	developer = _require_developer(req)

	keys = await repo.list_developer_keys(developer.id)
	return UnifiedResponse(status='success', result=keys)


@router.get(
	'/v1/admin/me',
	response_model=UnifiedResponse[Developer],
	summary='Perfil del desarrollador autenticado',
)
async def me(req: Request):
	"""Obtiene el perfil del desarrollador autenticado desde request.state."""
	return UnifiedResponse(status='success', result=_require_developer(req))


# ── Clerk API key management ────────────────────────────────────────


@router.post(
	'/v1/admin/api-keys',
	status_code=201,
	summary='Crear API key para el tenant autenticado (Clerk)',
	responses={
		403: {'description': 'Solo usuarios Clerk', 'model': UnifiedResponse[ApiError]},
		422: {'description': 'Scopes inválidos', 'model': UnifiedResponse[ApiError]},
	},
)
async def create_tenant_api_key(req: Request, body: CreateApiKeyRequest | None = None):
	"""Crea una nueva API key scoped al tenant autenticado vía Clerk.

	Solo accesible cuando ``auth_method == 'clerk_jwt'``.
	El cuerpo es opcional — si se omite, la key se crea sin scopes.
	Los scopes solicitados deben ser un subset de los scopes del plan.
	"""
	repo: ApiKeyRepository = req.app.state.api_key_port  # type: ignore[attr-defined]
	tenant_id = _require_tenant_uuid(req)
	auth_method = getattr(req.state, 'auth_method', None)

	# Solo Clerk users pueden crear keys via este endpoint
	if auth_method != 'clerk_jwt':
		raise HTTPException(
			status_code=403,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(
					code='CLERK_ONLY',
					cause='Solo usuarios autenticados con Clerk pueden crear API keys via este endpoint',
				),
			).model_dump(),
		)

	# Validate scopes against plan
	plan = getattr(req.state, 'plan', None)
	scopes = body.scopes if body else None
	if scopes:
		if not plan or not set(scopes).issubset(set(plan.scopes)):
			raise HTTPException(
				status_code=422,
				detail=UnifiedResponse(
					status='error',
					error=ApiError(
						code='INVALID_SCOPES',
						cause=f'Los scopes solicitados no son válidos para el plan actual. '
						f'Scopes disponibles: {plan.scopes if plan else "N/A"}',
					),
				).model_dump(),
			)

	# Keys are tenant-scoped — no virtual app container needed anymore.
	result = await repo.create_api_key(
		app_id='',
		tenant_id=str(tenant_id),
		scopes=scopes,
		expires_at=body.expires_at if body else None,
	)
	if not result:
		raise HTTPException(
			status_code=500,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='SERVICE_UNAVAILABLE', cause='No se pudo crear la API key'),
			).model_dump(),
		)

	return UnifiedResponse(
		status='success',
		result={
			'key_preview': result['api_key'].key_preview,
			'full_key': result['full_key'],
			'warning': 'Guardá esta key — no se mostrará nuevamente',
		},
	)


@router.get(
	'/v1/admin/api-keys',
	summary='Listar API keys del tenant autenticado (Clerk)',
)
async def list_tenant_api_keys(
	req: Request,
	limit: int = Query(default=50, ge=1, le=200, description='Cantidad máxima de resultados'),
	offset: int = Query(default=0, ge=0, description='Desplazamiento para paginar'),
):
	"""Lista las API keys del tenant (activas e inactivas), paginado.

	NUNCA devuelve la full key — solo ``id``, ``key_preview``, ``created_at``,
	``scopes``, ``is_active`` y ``expires_at``. ``X-Total-Count`` expone el
	total para paginación.
	"""
	tenant_id = _require_tenant_uuid(req)
	repo: ApiKeyRepository = req.app.state.api_key_port  # type: ignore[attr-defined]

	total = await repo.count_keys(str(tenant_id))
	keys = await repo.list_keys(str(tenant_id), limit=limit, offset=offset)
	result = [
		{
			'id': k.id,
			'key_preview': k.key_preview,
			'created_at': k.created_at,
			'scopes': k.scopes,
			'is_active': k.is_active,
			'expires_at': k.expires_at,
		}
		for k in keys
	]
	resp = Response(
		content=UnifiedResponse(status='success', result=result).model_dump_json(),
		media_type='application/json',
	)
	resp.headers['X-Total-Count'] = str(total)
	return resp


@router.get(
	'/v1/admin/api-keys/{key_id}',
	summary='Obtener una API key del tenant por ID',
	responses={404: {'description': 'No encontrada', 'model': UnifiedResponse[ApiError]}},
)
async def get_tenant_api_key(key_id: str, req: Request):
	"""Obtiene una key del tenant por ID — preview, scopes, estado y expiración.

	NUNCA devuelve la raw key.
	"""
	tenant_id = _require_tenant_uuid(req)
	repo: ApiKeyRepository = req.app.state.api_key_port  # type: ignore[attr-defined]
	key = await repo.get_key(key_id, str(tenant_id))
	if key is None:
		raise HTTPException(
			status_code=404,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='KEY_NOT_FOUND', cause='No existe una API key con ese ID para tu tenant'),
			).model_dump(),
		)
	return UnifiedResponse(status='success', result=key)


@router.patch(
	'/v1/admin/api-keys/{key_id}',
	summary='Actualizar parcialmente una API key del tenant',
	responses={
		404: {'description': 'No encontrada', 'model': UnifiedResponse[ApiError]},
		422: {'description': 'Payload vacío o scopes inválidos', 'model': UnifiedResponse[ApiError]},
	},
)
async def update_tenant_api_key(key_id: str, body: UpdateApiKeyRequest, req: Request):
	"""Actualiza parcialmente una key del tenant: name, scopes, is_active (reactiva), expires_at."""
	tenant_id = _require_tenant_uuid(req)

	fields = body.model_dump(exclude_unset=True)
	if not fields:
		raise HTTPException(
			status_code=422,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(
					code='EMPTY_UPDATE',
					cause='Debés enviar al menos un campo a actualizar (name, scopes, is_active o expires_at)',
				),
			).model_dump(),
		)
	if 'name' in fields and (body.name is None or not body.name.strip()):
		raise HTTPException(
			status_code=422,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='INVALID_NAME', cause='El nombre no puede ser vacío'),
			).model_dump(),
		)
	if 'scopes' in fields and body.scopes is not None:
		plan = getattr(req.state, 'plan', None)
		if not plan or not set(body.scopes).issubset(set(plan.scopes)):
			raise HTTPException(
				status_code=422,
				detail=UnifiedResponse(
					status='error',
					error=ApiError(
						code='INVALID_SCOPES',
						cause=f'Los scopes solicitados no son válidos para el plan actual. '
						f'Scopes disponibles: {plan.scopes if plan else "N/A"}',
					),
				).model_dump(),
			)

	repo: ApiKeyRepository = req.app.state.api_key_port  # type: ignore[attr-defined]
	key = await repo.update_key(key_id, str(tenant_id), **fields)
	if key is None:
		raise HTTPException(
			status_code=404,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='KEY_NOT_FOUND', cause='No existe una API key con ese ID para tu tenant'),
			).model_dump(),
		)
	return UnifiedResponse(status='success', result=key)


@router.delete(
	'/v1/admin/api-keys/{key_id}',
	status_code=204,
	summary='Desactivar API key del tenant',
)
async def deactivate_tenant_api_key(key_id: str, req: Request):
	"""Desactiva una API key (``is_active=False``).

	Idempotente — retorna 204 incluso si la key no existe o ya
	estaba desactivada. Verifica que la key pertenezca al tenant
	autenticado antes de desactivarla.
	"""
	tenant_id = _require_tenant_uuid(req)
	repo: ApiKeyRepository = req.app.state.api_key_port  # type: ignore[attr-defined]

	await repo.deactivate_key(key_id, str(tenant_id))
	return Response(status_code=204)
