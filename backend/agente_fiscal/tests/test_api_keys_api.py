"""HTTP-level tests for ``agente_fiscal.api.routes.admin`` (Clerk api-keys CRUD).

Builds a minimal FastAPI app that mounts ONLY the admin router, registers the
same UnifiedResponse HTTPException handler the production server uses, and a
stub middleware that feeds ``request.state`` from headers — replicating the
exact state contract the real auth stack leaves for the route layer:

  - ``X-Tenant-Id``        → ``request.state.tenant_id`` (Clerk flow)
  - ``X-Auth-Method``      → ``request.state.auth_method`` (default clerk_jwt)
  - ``X-Developer-Id``     → ``request.state.developer`` (developer surface)
  - ``X-Plan-Scopes``      → ``request.state.plan.scopes`` (default chat scopes)

``app.state.api_key_port`` is the real Postgres-backed adapter over the test
session factory, so the full HTTP + adapter path (and the new scopes /
expires_at columns) is exercised against the test DB.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from starlette.middleware.base import BaseHTTPMiddleware

from agente_fiscal.adapters.db_api_keys import PostgresApiKeyPort, hash_api_key
from agente_fiscal.api.routes.admin import router as admin_router
from agente_fiscal.db.models import TenantMember
from agente_fiscal.domain.models import Developer, Plan, UnifiedResponse

pytestmark = pytest.mark.usefixtures('db_reset')

DEFAULT_PLAN_SCOPES = ['chat:read', 'chat:write']


def _headers(
	tenant_id=None,
	*,
	auth_method: str = 'clerk_jwt',
	developer_id=None,
	plan_scopes: list[str] | None = None,
) -> dict[str, str]:
	"""Build the header set the stub middleware translates into request.state."""
	headers = {}
	if tenant_id is not None:
		headers['X-Tenant-Id'] = str(tenant_id)
	headers['X-Auth-Method'] = auth_method
	if developer_id is not None:
		headers['X-Developer-Id'] = str(developer_id)
	if plan_scopes is not None:
		headers['X-Plan-Scopes'] = ','.join(plan_scopes)
	return headers


def _build_app(test_session_factory) -> FastAPI:
	"""Minimal app: admin router + UnifiedResponse handler + auth state stub."""

	class AuthStateStub(BaseHTTPMiddleware):
		async def dispatch(self, request: Request, call_next):
			request.state.tenant_id = request.headers.get('X-Tenant-Id')
			request.state.auth_method = request.headers.get('X-Auth-Method', 'clerk_jwt')

			dev_id = request.headers.get('X-Developer-Id')
			request.state.developer = (
				Developer(
					id=dev_id,
					name='Test Dev',
					email='dev@test.io',
					created_at=datetime.now(timezone.utc),
				)
				if dev_id
				else None
			)

			ps = request.headers.get('X-Plan-Scopes')
			plan_scopes = [s for s in ps.split(',') if s] if ps else list(DEFAULT_PLAN_SCOPES)
			request.state.plan = Plan(
				id='pro',
				name='Pro',
				scopes=plan_scopes,
				rate_limit_rpm=100,
				rate_limit_rpd=1000,
			)
			request.state.scopes = list(plan_scopes)
			return await call_next(request)

	app = FastAPI()
	app.add_middleware(AuthStateStub)

	@app.exception_handler(HTTPException)
	async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
		# Wrap exactly like agente_fiscal.api.server.http_exception_handler.
		detail = exc.detail
		return JSONResponse(
			status_code=exc.status_code,
			content=detail
			if isinstance(detail, dict)
			else UnifiedResponse(
				status='error',
				error={'code': 'HTTP_ERROR', 'cause': str(detail)},
			).model_dump(),
		)

	app.state.api_key_port = PostgresApiKeyPort(test_session_factory)
	app.include_router(admin_router)
	return app


@pytest.fixture
def app(test_session_factory) -> FastAPI:
	return _build_app(test_session_factory)


@pytest.fixture
def client(app) -> AsyncClient:
	transport = ASGITransport(app=app)
	return AsyncClient(transport=transport, base_url='http://test')


async def _create_key(client, tenant_id, *, body=None) -> tuple[dict, str]:
	"""POST a tenant API key; returns the result dict (with full_key) and its id."""
	resp = await client.post(
		'/v1/admin/api-keys',
		headers=_headers(tenant_id),
		json=body,
	)
	assert resp.status_code == 201, resp.text
	result = resp.json()['result']
	assert result['full_key'].startswith('fa_')
	key_id = await _key_id_by_preview(client, tenant_id, result['key_preview'])
	return result, key_id


async def _key_id_by_preview(client, tenant_id, preview) -> str:
	resp = await client.get('/v1/admin/api-keys', headers=_headers(tenant_id))
	assert resp.status_code == 200, resp.text
	for key in resp.json()['result']:
		if key['key_preview'] == preview:
			return key['id']
	raise AssertionError(f'key preview {preview!r} not found in list')


async def _make_dev_member(app, tenant_id, *, clerk_user_id='dev_a') -> str:
	"""Create a developer user with admin membership on the tenant."""
	async with app.state.api_key_port._session_factory() as session:
		user = await _make_user(session, clerk_user_id)
		session.add(TenantMember(tenant_id=tenant_id, user_id=user.id, role='admin'))
		await session.commit()
		return str(user.id)


async def _make_user(session, clerk_user_id):
	"""Inline user-row builder (kept local to avoid conftest import plumbing)."""
	from agente_fiscal.db.models import User as UserRow

	row = UserRow(
		clerk_user_id=clerk_user_id,
		email=f'{clerk_user_id}@test.io',
		display_name=clerk_user_id,
	)
	session.add(row)
	await session.commit()
	await session.refresh(row)
	return row


# ─── POST /v1/admin/api-keys ────────────────────────────────────────────────


async def test_create_tenant_api_key_success(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	resp = await client.post(
		'/v1/admin/api-keys',
		headers=_headers(tenant.id),
		json={'scopes': ['chat:read']},
	)
	assert resp.status_code == 201, resp.text
	result = resp.json()['result']
	assert result['key_preview']
	assert result['full_key'].startswith('fa_')
	assert 'Guardá' in result['warning']


async def test_create_tenant_api_key_scopes_persisted(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	_, key_id = await _create_key(client, tenant.id, body={'scopes': ['chat:read']})

	resp = await client.get(f'/v1/admin/api-keys/{key_id}', headers=_headers(tenant.id))
	assert resp.status_code == 200
	assert resp.json()['result']['scopes'] == ['chat:read']


async def test_create_tenant_api_key_default_scopes_from_plan(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	_, key_id = await _create_key(client, tenant.id)
	resp = await client.get(f'/v1/admin/api-keys/{key_id}', headers=_headers(tenant.id))
	assert resp.status_code == 200
	assert resp.json()['result']['scopes'] == DEFAULT_PLAN_SCOPES


async def test_create_tenant_api_key_403_non_clerk(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	resp = await client.post(
		'/v1/admin/api-keys',
		headers=_headers(tenant.id, auth_method='api_key'),
		json={'scopes': ['chat:read']},
	)
	assert resp.status_code == 403
	assert resp.json()['error']['code'] == 'CLERK_ONLY'


async def test_create_tenant_api_key_422_invalid_scopes(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	resp = await client.post(
		'/v1/admin/api-keys',
		headers=_headers(tenant.id),
		json={'scopes': ['chat:read', 'admin:*']},
	)
	assert resp.status_code == 422
	assert resp.json()['error']['code'] == 'INVALID_SCOPES'


async def test_create_tenant_api_key_401_without_tenant(client) -> None:
	resp = await client.post(
		'/v1/admin/api-keys', headers=_headers(None), json={'scopes': ['chat:read']}
	)
	assert resp.status_code == 401
	assert resp.json()['error']['code'] == 'UNAUTHENTICATED'


# ─── GET /v1/admin/api-keys/{key_id} ────────────────────────────────────────


async def test_get_api_key_success_never_exposes_secret(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	_, key_id = await _create_key(client, tenant.id, body={'scopes': ['chat:read']})

	resp = await client.get(f'/v1/admin/api-keys/{key_id}', headers=_headers(tenant.id))
	assert resp.status_code == 200
	result = resp.json()['result']
	assert result['id'] == key_id
	assert result['key_preview']
	assert result['scopes'] == ['chat:read']
	assert result['is_active'] is True
	assert result['created_at'] is not None
	assert 'expires_at' in result
	for forbidden in ('full_key', 'key_hash'):
		assert forbidden not in result


async def test_get_api_key_404_missing(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	resp = await client.get(f'/v1/admin/api-keys/{uuid.uuid4()}', headers=_headers(tenant.id))
	assert resp.status_code == 404
	assert resp.json()['error']['code'] == 'KEY_NOT_FOUND'


async def test_get_api_key_404_foreign_tenant(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant_a = await make_tenant(session, name='Tenant A')
		tenant_b = await make_tenant(session, name='Tenant B')

	_, key_id = await _create_key(client, tenant_a.id)
	resp = await client.get(f'/v1/admin/api-keys/{key_id}', headers=_headers(tenant_b.id))
	assert resp.status_code == 404
	assert resp.json()['error']['code'] == 'KEY_NOT_FOUND'


# ─── PATCH /v1/admin/api-keys/{key_id} ──────────────────────────────────────


async def test_patch_api_key_name_scopes_deactivate_reactivate(
	app, client, make_tenant
) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	_, key_id = await _create_key(client, tenant.id, body={'scopes': ['chat:read', 'chat:write']})

	resp = await client.patch(
		f'/v1/admin/api-keys/{key_id}',
		headers=_headers(tenant.id),
		json={'name': 'Producción', 'scopes': ['chat:read']},
	)
	assert resp.status_code == 200, resp.text
	result = resp.json()['result']
	assert result['name'] == 'Producción'
	assert result['scopes'] == ['chat:read']
	assert result['is_active'] is True

	# Deactivate
	resp = await client.delete(f'/v1/admin/api-keys/{key_id}', headers=_headers(tenant.id))
	assert resp.status_code == 204
	resp = await client.get(f'/v1/admin/api-keys/{key_id}', headers=_headers(tenant.id))
	assert resp.json()['result']['is_active'] is False

	# Reactivate
	resp = await client.patch(
		f'/v1/admin/api-keys/{key_id}',
		headers=_headers(tenant.id),
		json={'is_active': True},
	)
	assert resp.status_code == 200
	assert resp.json()['result']['is_active'] is True


async def test_patch_scopes_persisted_visible_in_get(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	_, key_id = await _create_key(client, tenant.id)

	resp = await client.patch(
		f'/v1/admin/api-keys/{key_id}',
		headers=_headers(tenant.id),
		json={'scopes': ['chat:write']},
	)
	assert resp.status_code == 200
	assert resp.json()['result']['scopes'] == ['chat:write']

	# Persistence: a fresh GET (new request) reflects the new scopes.
	resp = await client.get(f'/v1/admin/api-keys/{key_id}', headers=_headers(tenant.id))
	assert resp.status_code == 200
	assert resp.json()['result']['scopes'] == ['chat:write']


async def test_patch_api_key_422_empty_body(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	_, key_id = await _create_key(client, tenant.id)
	resp = await client.patch(
		f'/v1/admin/api-keys/{key_id}', headers=_headers(tenant.id), json={}
	)
	assert resp.status_code == 422
	assert resp.json()['error']['code'] == 'EMPTY_UPDATE'


async def test_patch_api_key_422_invalid_scopes(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	_, key_id = await _create_key(client, tenant.id)
	resp = await client.patch(
		f'/v1/admin/api-keys/{key_id}',
		headers=_headers(tenant.id),
		json={'scopes': ['chat:read', 'admin:*']},
	)
	assert resp.status_code == 422
	assert resp.json()['error']['code'] == 'INVALID_SCOPES'


async def test_patch_api_key_404_missing(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	resp = await client.patch(
		f'/v1/admin/api-keys/{uuid.uuid4()}', headers=_headers(tenant.id), json={'name': 'X'}
	)
	assert resp.status_code == 404
	assert resp.json()['error']['code'] == 'KEY_NOT_FOUND'


async def test_patch_api_key_404_foreign_tenant(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant_a = await make_tenant(session, name='Tenant A')
		tenant_b = await make_tenant(session, name='Tenant B')

	_, key_id = await _create_key(client, tenant_a.id)
	resp = await client.patch(
		f'/v1/admin/api-keys/{key_id}',
		headers=_headers(tenant_b.id),
		json={'name': 'Hijacked'},
	)
	assert resp.status_code == 404

	# A's key is untouched.
	resp = await client.get(f'/v1/admin/api-keys/{key_id}', headers=_headers(tenant_a.id))
	assert resp.status_code == 200
	assert resp.json()['result']['name'] != 'Hijacked'


# ─── GET /v1/admin/api-keys (list + pagination) ─────────────────────────────


async def test_list_api_keys_pagination_and_total(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	for _ in range(4):
		await _create_key(client, tenant.id)

	# Full ordered list (newest first).
	full = await client.get('/v1/admin/api-keys', headers=_headers(tenant.id))
	assert full.status_code == 200
	assert full.headers['X-Total-Count'] == '4'
	all_ids = [k['id'] for k in full.json()['result']]
	assert len(all_ids) == 4

	page = await client.get(
		'/v1/admin/api-keys',
		headers=_headers(tenant.id),
		params={'limit': 2, 'offset': 1},
	)
	assert page.status_code == 200
	assert page.headers['X-Total-Count'] == '4'
	body = page.json()
	assert len(body['result']) == 2
	assert [k['id'] for k in body['result']] == all_ids[1:3]

	# Every list row exposes preview/scopes/state, never the secret.
	for key in body['result']:
		assert key['key_preview']
		assert key['scopes'] == DEFAULT_PLAN_SCOPES
		assert key['is_active'] is True
		assert 'expires_at' in key
		assert 'full_key' not in key


async def test_list_api_keys_401_without_tenant(client) -> None:
	resp = await client.get('/v1/admin/api-keys', headers=_headers(None))
	assert resp.status_code == 401
	assert resp.json()['error']['code'] == 'UNAUTHENTICATED'


# ─── expires_at ─────────────────────────────────────────────────────────────


async def test_expires_at_persists_on_create(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	future = datetime.now(timezone.utc) + timedelta(days=30)
	_, key_id = await _create_key(client, tenant.id, body={'expires_at': future.isoformat()})

	resp = await client.get(f'/v1/admin/api-keys/{key_id}', headers=_headers(tenant.id))
	assert resp.status_code == 200
	expires = resp.json()['result']['expires_at']
	assert expires is not None
	assert expires.startswith(future.strftime('%Y-%m-%d'))


async def test_patch_sets_expires_at(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	_, key_id = await _create_key(client, tenant.id)
	future = datetime.now(timezone.utc) + timedelta(days=90)
	resp = await client.patch(
		f'/v1/admin/api-keys/{key_id}',
		headers=_headers(tenant.id),
		json={'expires_at': future.isoformat()},
	)
	assert resp.status_code == 200
	assert resp.json()['result']['expires_at'].startswith(future.strftime('%Y-%m-%d'))


async def test_patch_clears_expires_at(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	future = datetime.now(timezone.utc) + timedelta(days=30)
	_, key_id = await _create_key(client, tenant.id, body={'expires_at': future.isoformat()})

	resp = await client.patch(
		f'/v1/admin/api-keys/{key_id}', headers=_headers(tenant.id), json={'expires_at': None}
	)
	assert resp.status_code == 200
	assert resp.json()['result']['expires_at'] is None


async def test_expired_key_does_not_resolve(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	past = datetime.now(timezone.utc) - timedelta(days=1)
	created, _ = await _create_key(client, tenant.id, body={'expires_at': past.isoformat()})

	repo = app.state.api_key_port
	ctx = await repo.resolve(hash_api_key(created['full_key']))
	assert ctx is None  # expired → invalid, same as is_active=False


async def test_future_key_resolves_with_expiry(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)

	future = datetime.now(timezone.utc) + timedelta(days=30)
	created, _ = await _create_key(client, tenant.id, body={'expires_at': future.isoformat()})

	repo = app.state.api_key_port
	ctx = await repo.resolve(hash_api_key(created['full_key']))
	assert ctx is not None
	assert ctx.api_key is not None
	assert ctx.api_key.expires_at is not None


# ─── Multi-tenant isolation at HTTP level ───────────────────────────────────


async def test_tenant_isolation_matrix(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant_a = await make_tenant(session, name='Tenant A')
		tenant_b = await make_tenant(session, name='Tenant B')

	_, key_id = await _create_key(client, tenant_a.id)

	# B cannot get A's key
	resp = await client.get(f'/v1/admin/api-keys/{key_id}', headers=_headers(tenant_b.id))
	assert resp.status_code == 404

	# B cannot list A's keys
	resp = await client.get('/v1/admin/api-keys', headers=_headers(tenant_b.id))
	assert resp.status_code == 200
	assert resp.headers['X-Total-Count'] == '0'
	assert resp.json()['result'] == []

	# B cannot patch A's key
	resp = await client.patch(
		f'/v1/admin/api-keys/{key_id}',
		headers=_headers(tenant_b.id),
		json={'name': 'Hijacked'},
	)
	assert resp.status_code == 404

	# A's key unchanged after B's attempts
	resp = await client.get(f'/v1/admin/api-keys/{key_id}', headers=_headers(tenant_a.id))
	assert resp.status_code == 200
	assert resp.json()['result']['name'] != 'Hijacked'
	assert resp.json()['result']['is_active'] is True

	# B cannot deactivate A's key
	resp = await client.delete(f'/v1/admin/api-keys/{key_id}', headers=_headers(tenant_b.id))
	assert resp.status_code == 204  # idempotent 204 by contract
	resp = await client.get(f'/v1/admin/api-keys/{key_id}', headers=_headers(tenant_a.id))
	assert resp.status_code == 200
	assert resp.json()['result']['is_active'] is True


# ─── Developer surface: GET /v1/admin/apps ──────────────────────────────────


async def test_list_apps_lists_developer_apps(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)
	dev_id = await _make_dev_member(app, tenant.id)

	resp = await client.post(
		'/v1/admin/apps',
		headers=_headers(None, developer_id=dev_id),
		json={'name': 'Gestión Pérez', 'environment': 'sandbox'},
	)
	assert resp.status_code == 200, resp.text
	created = resp.json()['result']

	resp = await client.get('/v1/admin/apps', headers=_headers(None, developer_id=dev_id))
	assert resp.status_code == 200
	apps = resp.json()['result']
	assert len(apps) == 1
	assert apps[0]['id'] == created['id']
	assert apps[0]['name'] == 'Gestión Pérez'


async def test_list_apps_isolated_by_developer(app, client, make_tenant) -> None:
	async with app.state.api_key_port._session_factory() as session:
		tenant = await make_tenant(session)
	dev_a = await _make_dev_member(app, tenant.id, clerk_user_id='dev_a')
	dev_b = await _make_dev_member(app, tenant.id, clerk_user_id='dev_b')

	resp = await client.post(
		'/v1/admin/apps',
		headers=_headers(None, developer_id=dev_a),
		json={'name': 'App de A'},
	)
	assert resp.status_code == 200

	resp = await client.get('/v1/admin/apps', headers=_headers(None, developer_id=dev_b))
	assert resp.status_code == 200
	assert resp.json()['result'] == []


async def test_list_apps_401_without_developer(client) -> None:
	resp = await client.get('/v1/admin/apps', headers=_headers(None, developer_id=None))
	assert resp.status_code == 401
	assert resp.json()['error']['code'] == 'UNAUTHENTICATED'