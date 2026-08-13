"""HTTP-level tests for ``agente_fiscal.api.routes.clients``.

Builds a minimal FastAPI app that mounts ONLY the clients router, registers the
same UnifiedResponse HTTPException handler the production server uses, and a
stub middleware that sets ``request.state.tenant_id`` from the ``X-Tenant-Id``
header (replicating the exact state contract ``AuthMiddleware`` leaves for the
route layer). ``app.state.client_repository`` is a real Postgres-backed repo
over the test session factory, so the full HTTP + adapter path is exercised.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from agente_fiscal.adapters.db_clients import PostgresClientRepository
from agente_fiscal.api.routes.clients import router as clients_router
from agente_fiscal.db.models import ReportRun
from agente_fiscal.domain.models import ApiError, UnifiedResponse

pytestmark = pytest.mark.usefixtures('db_reset')

CUIT_VALID_A = '20000000001'
CUIT_VALID_B = '23000000000'
CUIT_VALID_C = '24000000007'
CUIT_VALID_D = '27000000006'
CUIT_INVALID_CHECKSUM = '20301234561'
CUIT_INVALID_FORMAT = '123'


def _build_app(test_session_factory) -> FastAPI:
	"""Minimal app: clients router + UnifiedResponse handler + tenant stub."""

	class TenantStubMiddleware(BaseHTTPMiddleware):
		async def dispatch(self, request: Request, call_next):
			request.state.tenant_id = request.headers.get('X-Tenant-Id')
			return await call_next(request)

	app = FastAPI()
	app.add_middleware(TenantStubMiddleware)

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

	app.state.client_repository = PostgresClientRepository(test_session_factory)
	app.include_router(clients_router)
	return app


@pytest.fixture
def app(test_session_factory) -> FastAPI:
	return _build_app(test_session_factory)


@pytest.fixture
def client(app) -> AsyncClient:
	transport = ASGITransport(app=app)
	return AsyncClient(transport=transport, base_url='http://test')


async def _create_via_api(client, *, tenant_id, cuit, name='Acme', email=None, config=None):
	resp = await client.post(
		'/v1/clients',
		headers={'X-Tenant-Id': str(tenant_id)},
		json={'cuit': cuit, 'name': name, 'email': email, 'config': config or {}},
	)
	assert resp.status_code == 201, resp.text
	return resp.json()['result']


# ─── POST ───────────────────────────────────────────────────────────────────


async def test_create_client_success(app, client, make_tenant) -> None:
	async with app.state.client_repository._session_factory() as session:
		tenant = await make_tenant(session)

	resp = await client.post(
		'/v1/clients',
		headers={'X-Tenant-Id': str(tenant.id)},
		json={'cuit': CUIT_VALID_A, 'name': 'Pérez SRL', 'email': 'ana@acme.io', 'config': {'notas': 'x'}},
	)
	assert resp.status_code == 201
	body = resp.json()
	assert body['status'] == 'success'
	assert body['result']['cuit'] == CUIT_VALID_A
	assert body['result']['name'] == 'Pérez SRL'
	assert body['result']['email'] == 'ana@acme.io'
	assert body['result']['config'] == {'notas': 'x'}


async def test_create_client_401_without_tenant(client) -> None:
	resp = await client.post(
		'/v1/clients',
		json={'cuit': CUIT_VALID_A, 'name': 'Acme'},
	)
	assert resp.status_code == 401
	assert resp.json()['error']['code'] == 'UNAUTHENTICATED'


async def test_create_client_422_invalid_cuit(app, client, make_tenant) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant = await make_tenant(session)

	for bad in (CUIT_INVALID_CHECKSUM, CUIT_INVALID_FORMAT):
		resp = await client.post(
			'/v1/clients',
			headers={'X-Tenant-Id': str(tenant.id)},
			json={'cuit': bad, 'name': 'Acme'},
		)
		assert resp.status_code == 422
		assert resp.json()['error']['code'] == 'INVALID_CUIT'


async def test_create_client_422_invalid_email(app, client, make_tenant) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant = await make_tenant(session)

	resp = await client.post(
		'/v1/clients',
		headers={'X-Tenant-Id': str(tenant.id)},
		json={'cuit': CUIT_VALID_A, 'name': 'Acme', 'email': 'not-an-email'},
	)
	assert resp.status_code == 422
	assert resp.json()['error']['code'] == 'INVALID_EMAIL'


async def test_create_client_duplicate_cuit_409(
	app, client, make_tenant
) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant = await make_tenant(session)
	await _create_via_api(client, tenant_id=tenant.id, cuit=CUIT_VALID_A)

	resp = await client.post(
		'/v1/clients',
		headers={'X-Tenant-Id': str(tenant.id)},
		json={'cuit': CUIT_VALID_A, 'name': 'Dupe'},
	)
	assert resp.status_code == 409
	assert resp.json()['error']['code'] == 'CLIENT_CUIT_EXISTS'


# ─── GET (list) ─────────────────────────────────────────────────────────────


async def test_list_clients_pagination_and_total(
	app, client, make_tenant
) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant = await make_tenant(session)
	for cuit in (CUIT_VALID_A, CUIT_VALID_B, CUIT_VALID_C, CUIT_VALID_D):
		await _create_via_api(client, tenant_id=tenant.id, cuit=cuit)

	resp = await client.get(
		'/v1/clients', headers={'X-Tenant-Id': str(tenant.id)}, params={'limit': 2, 'offset': 1}
	)
	assert resp.status_code == 200
	assert resp.headers['X-Total-Count'] == '4'
	body = resp.json()
	assert len(body['result']) == 2
	assert [c['cuit'] for c in body['result']] == [CUIT_VALID_C, CUIT_VALID_B]


async def test_list_clients_filters(app, client, make_tenant) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant = await make_tenant(session)
	await _create_via_api(client, tenant_id=tenant.id, cuit=CUIT_VALID_A, name='Alfa SA')
	await _create_via_api(client, tenant_id=tenant.id, cuit=CUIT_VALID_B, name='Beta SRL')

	resp = await client.get(
		'/v1/clients', headers={'X-Tenant-Id': str(tenant.id)}, params={'q': 'alfa'}
	)
	assert resp.headers['X-Total-Count'] == '1'
	assert [c['cuit'] for c in resp.json()['result']] == [CUIT_VALID_A]

	resp = await client.get(
		'/v1/clients', headers={'X-Tenant-Id': str(tenant.id)}, params={'cuit': CUIT_VALID_B}
	)
	assert resp.headers['X-Total-Count'] == '1'
	assert [c['cuit'] for c in resp.json()['result']] == [CUIT_VALID_B]


async def test_list_clients_401_without_tenant(client) -> None:
	resp = await client.get('/v1/clients')
	assert resp.status_code == 401


# ─── GET by id ──────────────────────────────────────────────────────────────


async def test_get_client_success(app, client, make_tenant) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant = await make_tenant(session)
	created = await _create_via_api(client, tenant_id=tenant.id, cuit=CUIT_VALID_A)

	resp = await client.get(
		f"/v1/clients/{created['id']}", headers={'X-Tenant-Id': str(tenant.id)}
	)
	assert resp.status_code == 200
	assert resp.json()['result']['cuit'] == CUIT_VALID_A


async def test_get_client_404_missing(app, client, make_tenant) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant = await make_tenant(session)

	resp = await client.get(
		f'/v1/clients/{uuid.uuid4()}', headers={'X-Tenant-Id': str(tenant.id)}
	)
	assert resp.status_code == 404
	assert resp.json()['error']['code'] == 'CLIENT_NOT_FOUND'


# ─── PATCH ──────────────────────────────────────────────────────────────────


async def test_patch_client_success(app, client, make_tenant) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant = await make_tenant(session)
	created = await _create_via_api(client, tenant_id=tenant.id, cuit=CUIT_VALID_A, name='Antes SA')

	resp = await client.patch(
		f"/v1/clients/{created['id']}",
		headers={'X-Tenant-Id': str(tenant.id)},
		json={'name': 'Después SA', 'email': 'nuevo@acme.io', 'config': {'a': 1}},
	)
	assert resp.status_code == 200
	result = resp.json()['result']
	assert result['name'] == 'Después SA'
	assert result['email'] == 'nuevo@acme.io'
	assert result['config'] == {'a': 1}
	assert result['cuit'] == CUIT_VALID_A  # untouched fields preserved


async def test_patch_client_change_cuit(app, client, make_tenant) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant = await make_tenant(session)
	created = await _create_via_api(client, tenant_id=tenant.id, cuit=CUIT_VALID_A)

	resp = await client.patch(
		f"/v1/clients/{created['id']}",
		headers={'X-Tenant-Id': str(tenant.id)},
		json={'cuit': CUIT_VALID_B},
	)
	assert resp.status_code == 200
	assert resp.json()['result']['cuit'] == CUIT_VALID_B


async def test_patch_client_duplicate_cuit_409(app, client, make_tenant) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant = await make_tenant(session)
	created = await _create_via_api(client, tenant_id=tenant.id, cuit=CUIT_VALID_A)
	await _create_via_api(client, tenant_id=tenant.id, cuit=CUIT_VALID_B)

	resp = await client.patch(
		f"/v1/clients/{created['id']}",
		headers={'X-Tenant-Id': str(tenant.id)},
		json={'cuit': CUIT_VALID_B},
	)
	assert resp.status_code == 409
	assert resp.json()['error']['code'] == 'CLIENT_CUIT_EXISTS'


async def test_patch_client_404_missing(app, client, make_tenant) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant = await make_tenant(session)

	resp = await client.patch(
		f'/v1/clients/{uuid.uuid4()}',
		headers={'X-Tenant-Id': str(tenant.id)},
		json={'name': 'X'},
	)
	assert resp.status_code == 404


async def test_patch_client_422_empty_body(app, client, make_tenant) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant = await make_tenant(session)
	created = await _create_via_api(client, tenant_id=tenant.id, cuit=CUIT_VALID_A)

	resp = await client.patch(
		f"/v1/clients/{created['id']}",
		headers={'X-Tenant-Id': str(tenant.id)},
		json={},
	)
	assert resp.status_code == 422
	assert resp.json()['error']['code'] == 'EMPTY_UPDATE'


async def test_patch_client_422_invalid_cuit(app, client, make_tenant) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant = await make_tenant(session)
	created = await _create_via_api(client, tenant_id=tenant.id, cuit=CUIT_VALID_A)

	for bad in (CUIT_INVALID_CHECKSUM, CUIT_INVALID_FORMAT):
		resp = await client.patch(
			f"/v1/clients/{created['id']}",
			headers={'X-Tenant-Id': str(tenant.id)},
			json={'cuit': bad},
		)
		assert resp.status_code == 422
		assert resp.json()['error']['code'] == 'INVALID_CUIT'


async def test_patch_client_422_invalid_email(app, client, make_tenant) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant = await make_tenant(session)
	created = await _create_via_api(client, tenant_id=tenant.id, cuit=CUIT_VALID_A)

	resp = await client.patch(
		f"/v1/clients/{created['id']}",
		headers={'X-Tenant-Id': str(tenant.id)},
		json={'email': 'not-an-email'},
	)
	assert resp.status_code == 422
	assert resp.json()['error']['code'] == 'INVALID_EMAIL'


# ─── DELETE ─────────────────────────────────────────────────────────────────


async def test_delete_client_success(app, client, make_tenant) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant = await make_tenant(session)
	created = await _create_via_api(client, tenant_id=tenant.id, cuit=CUIT_VALID_A)

	resp = await client.delete(
		f"/v1/clients/{created['id']}", headers={'X-Tenant-Id': str(tenant.id)}
	)
	assert resp.status_code == 204

	resp = await client.get(
		f"/v1/clients/{created['id']}", headers={'X-Tenant-Id': str(tenant.id)}
	)
	assert resp.status_code == 404


async def test_delete_client_404(app, client, make_tenant) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant = await make_tenant(session)

	resp = await client.delete(
		f'/v1/clients/{uuid.uuid4()}', headers={'X-Tenant-Id': str(tenant.id)}
	)
	assert resp.status_code == 404


# ─── Multi-tenant isolation at HTTP level ──────────────────────────────────


async def test_tenant_isolation_matrix(app, client, make_tenant) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant_a = await make_tenant(session, name='Tenant A')
		tenant_b = await make_tenant(session, name='Tenant B')
	created = await _create_via_api(client, tenant_id=tenant_a.id, cuit=CUIT_VALID_A)
	client_id = created['id']

	# B cannot see A's client
	resp = await client.get(
		f'/v1/clients/{client_id}', headers={'X-Tenant-Id': str(tenant_b.id)}
	)
	assert resp.status_code == 404

	# B cannot list A's clients
	resp = await client.get(
		'/v1/clients', headers={'X-Tenant-Id': str(tenant_b.id)}
	)
	assert resp.headers['X-Total-Count'] == '0'
	assert resp.json()['result'] == []

	# B cannot patch A's client
	resp = await client.patch(
		f'/v1/clients/{client_id}',
		headers={'X-Tenant-Id': str(tenant_b.id)},
		json={'name': 'Hijacked'},
	)
	assert resp.status_code == 404

	# A's client name unchanged after B's attempted patch
	resp = await client.get(
		f'/v1/clients/{client_id}', headers={'X-Tenant-Id': str(tenant_a.id)}
	)
	assert resp.json()['result']['name'] == 'Acme'

	# B cannot delete A's client
	resp = await client.delete(
		f'/v1/clients/{client_id}', headers={'X-Tenant-Id': str(tenant_b.id)}
	)
	assert resp.status_code == 404

	resp = await client.get(
		f'/v1/clients/{client_id}', headers={'X-Tenant-Id': str(tenant_a.id)}
	)
	assert resp.status_code == 200


# ─── DELETE preserves report_runs history ──────────────────────────────────


async def test_delete_client_preserves_report_runs(app, client, make_tenant) -> None:
	repo = app.state.client_repository
	async with repo._session_factory() as session:
		tenant = await make_tenant(session)
	created = await _create_via_api(client, tenant_id=tenant.id, cuit=CUIT_VALID_A)
	client_uuid = uuid.UUID(created['id'])

	async with repo._session_factory() as session:
		run = ReportRun(
			tenant_id=tenant.id, client_id=client_uuid, cuit=CUIT_VALID_A, status='done'
		)
		session.add(run)
		await session.commit()
		run_id = run.id

	resp = await client.delete(
		f"/v1/clients/{client_uuid}", headers={'X-Tenant-Id': str(tenant.id)}
	)
	assert resp.status_code == 204

	async with repo._session_factory() as session:
		rows = (await session.execute(select(ReportRun))).scalars().all()
	assert len(rows) == 1
	assert rows[0].id == run_id
	assert rows[0].client_id is None  # FK SET NULL, history preserved
	assert rows[0].status == 'done'
