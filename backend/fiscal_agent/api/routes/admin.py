"""Admin endpoints for developer self-service + tenant management.

Endpoints use ``request.state`` populated by the auth middleware.
New tenant CRUD endpoints require admin scopes.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from fiscal_agent.api.store import RedisStore, TenantStore
from fiscal_agent.domain.models import ApiError, App, Developer, PlanTier, Tenant, UnifiedResponse

router = APIRouter()


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


class CreateTenantRequest(BaseModel):
	"""Solicitud de creación de nuevo tenant."""

	name: str = Field(description='Nombre del tenant/estudio', examples=['Estudio Pérez'])
	cuit: str = Field(description='CUIT del tenant', examples=['20324837796'])
	clave_fiscal: str = Field(description='Clave fiscal ARCA')
	plan_tier: str = Field(default='free', description='Plan tier: free, pro, pro max, enterprise')


# ── Scope dependency ────────────────────────────────────────────────


def require_scope(scope: str):
	"""FastAPI dependency: check that the API key has the required scope."""

	async def _check(request: Request) -> None:
		api_key = getattr(request.state, 'api_key', None)
		if api_key is None or scope not in api_key.scopes:
			raise HTTPException(
				status_code=403,
				detail=UnifiedResponse(
					status='error',
					error=ApiError(code='INSUFFICIENT_SCOPE', cause=f'Se requiere scope {scope}'),
				).model_dump(),
			)

	return _check


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
	store: RedisStore = req.app.state.store  # type: ignore[attr-defined]

	# Check duplicate email
	existing = await store.get_developer_by_email(body.email)
	if existing:
		raise HTTPException(
			status_code=409,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='EMAIL_ALREADY_EXISTS', cause='El email ya está registrado'),
			).model_dump(),
		)

	dev = await store.register_developer(name=body.name, email=body.email)

	# Create default app
	app = await store.create_app(dev.id, 'Default App', 'sandbox')

	# Create API key for the default app
	key_result = await store.create_api_key(app.id)

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
	store: RedisStore = req.app.state.store  # type: ignore[attr-defined]
	developer: Developer = req.state.developer  # type: ignore[attr-defined]

	app = await store.create_app(developer.id, body.name, body.environment)
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
	store: RedisStore = req.app.state.store  # type: ignore[attr-defined]
	developer: Developer = req.state.developer  # type: ignore[attr-defined]

	# Check app ownership
	app_key = 'tenant:app:{}'.format(body.app_id)
	app_data = await store.redis.hgetall(app_key)
	if not app_data:
		raise HTTPException(
			status_code=404,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='APP_NOT_FOUND', cause='App no encontrada'),
			).model_dump(),
		)
	app = RedisStore._deserialize(App, app_data)
	if app.developer_id != developer.id:
		raise HTTPException(
			status_code=404,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='APP_NOT_FOUND', cause='App no encontrada'),
			).model_dump(),
		)

	result = await store.create_api_key(body.app_id)
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
	'/v1/admin/keys',
	summary='Listar API keys del desarrollador autenticado',
)
async def list_keys(req: Request):
	"""Lista todas las API keys del desarrollador autenticado (todos los apps)."""
	store: RedisStore = req.app.state.store  # type: ignore[attr-defined]
	developer: Developer = req.state.developer  # type: ignore[attr-defined]

	keys = await store.list_developer_keys(developer.id)
	return UnifiedResponse(status='success', result=keys)


@router.get(
	'/v1/admin/me',
	response_model=UnifiedResponse[Developer],
	summary='Perfil del desarrollador autenticado',
)
async def me(req: Request):
	"""Obtiene el perfil del desarrollador autenticado desde request.state."""
	return UnifiedResponse(status='success', result=req.state.developer)


# ── Tenant management (admin scopes required) ───────────────────────


@router.get(
	'/v1/admin/tenants',
	summary='Listar todos los tenants',
	dependencies=[Depends(require_scope('admin:read'))],
)
async def list_tenants(req: Request):
	"""Lista todos los tenants. Requiere scope admin:read."""
	tenant_store: TenantStore = req.app.state.tenant_store  # type: ignore[attr-defined]
	tenants = await tenant_store.list_all()
	return UnifiedResponse(status='success', result=tenants)


@router.post(
	'/v1/admin/tenants',
	status_code=201,
	summary='Crear nuevo tenant',
	dependencies=[Depends(require_scope('admin:write'))],
	responses={
		409: {'description': 'CUIT duplicado', 'model': UnifiedResponse[ApiError]},
	},
)
async def create_tenant(body: CreateTenantRequest, req: Request):
	"""Crea un nuevo tenant. Requiere scope admin:write."""
	tenant_store: TenantStore = req.app.state.tenant_store  # type: ignore[attr-defined]

	# Check duplicate CUIT
	existing = await tenant_store.get_by_cuit(body.cuit)
	if existing:
		raise HTTPException(
			status_code=409,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='TENANT_CUIT_EXISTS', cause='Ya existe un tenant con ese CUIT'),
			).model_dump(),
		)

	# Parse plan_tier
	try:
		plan_tier = PlanTier(body.plan_tier)
	except ValueError:
		raise HTTPException(
			status_code=422,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='INVALID_PLAN_TIER', cause=f'Plan tier inválido: {body.plan_tier}'),
			).model_dump(),
		)

	tenant = Tenant(
		id=RedisStore._generate_id(),
		name=body.name,
		plan_tier=plan_tier,
		cuit=body.cuit,
		clave_fiscal=body.clave_fiscal,
		is_active=True,
	)
	created = await tenant_store.create(tenant)
	return UnifiedResponse(status='success', result=created)


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
	store: RedisStore = req.app.state.store  # type: ignore[attr-defined]
	tenant_id = req.state.tenant_id
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

	# Create or reuse tenant app (virtual container for grouping keys)
	app_id = f'tapp_{tenant_id[:12]}'
	app_key = f'tenant:app:{app_id}'
	app_exists = await store.redis.hexists(app_key, 'id')
	if not app_exists:
		app = App(
			id=app_id,
			developer_id='sys_tenant',
			name=f'Tenant {tenant_id[:8]}',
			environment='production',
			status='active',
		)
		await store.redis.hset(
			app_key,
			mapping=RedisStore._serialize_for_redis(app.model_dump(mode='json')),
		)

	# Create the API key
	result = await store.create_api_key(app_id, tenant_id=tenant_id, scopes=scopes)

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
async def list_tenant_api_keys(req: Request):
	"""Lista todas las API keys activas e inactivas del tenant.

	NUNCA devuelve la full key — solo ``key_preview``, ``created_at``,
	``scopes`` e ``is_active``.
	"""
	store: RedisStore = req.app.state.store  # type: ignore[attr-defined]
	tenant_id = req.state.tenant_id

	keys = await store.list_tenant_keys(tenant_id)
	result = [
		{
			'key_preview': k.key_preview,
			'created_at': k.created_at,
			'scopes': k.scopes,
			'is_active': k.is_active,
		}
		for k in keys
	]
	return UnifiedResponse(status='success', result=result)


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
	store: RedisStore = req.app.state.store  # type: ignore[attr-defined]
	tenant_id = req.state.tenant_id

	await store.deactivate_key(key_id, tenant_id)
	return Response(status_code=204)
