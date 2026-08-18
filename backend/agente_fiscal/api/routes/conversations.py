"""Conversations CRUD router — persists chat conversations in Postgres.

Endpoints match the paths expected by ``api-client.js`` (frontend):
  - ``POST   /v1/conversations``        — save (create or update)
  - ``GET    /v1/conversations``         — list summaries
  - ``GET    /v1/conversations/{id}``    — get full conversation
  - ``DELETE /v1/conversations/{id}``    — delete

Response keys use camelCase (``updatedAt``, ``messageCount``) to match the
``useChat.js`` frontend expectations without a transform layer.

Storage is Postgres via ``db/conversation_repo.py`` (previously Redis). The
session factory comes from ``request.app.state.session_factory``; when absent
every endpoint degrades to 503 ``SERVICE_UNAVAILABLE`` so the frontend never
sees a misleading empty list.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from agente_fiscal.db.conversation_repo import (
	delete_all as repo_delete_all,
	delete_conversation as repo_delete_conversation,
	get_conversation as repo_get_conversation,
	list_conversations as repo_list_conversations,
	upsert_conversation as repo_upsert_conversation,
)
from agente_fiscal.db.models import User
from agente_fiscal.domain.models import ApiError, UnifiedResponse

router = APIRouter(tags=['chat'])

# ── Helpers ───────────────────────────────────────────────────────────────


def _tenant_uuid(request: Request) -> uuid.UUID:
	"""Resolve ``request.state.tenant_id`` as UUID, or raise 401."""
	tid = getattr(request.state, 'tenant_id', None)
	if not tid:
		raise HTTPException(
			status_code=401,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='UNAUTHORIZED', cause='Authentication required'),
			).model_dump(),
		)
	try:
		return uuid.UUID(str(tid))
	except (ValueError, TypeError):
		raise HTTPException(
			status_code=401,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='UNAUTHORIZED', cause='Tenant id inválido'),
			).model_dump(),
		)


def _not_found(code: str = 'CONVERSATION_NOT_FOUND', message: str = 'Conversation not found'):
	"""Shortcut for 404 with UnifiedResponse."""
	return HTTPException(
		status_code=404,
		detail=UnifiedResponse(
			status='error',
			error=ApiError(code=code, cause=message),
		).model_dump(),
	)


def _store_unavailable() -> HTTPException:
	"""Shortcut for the 503 returned when the Postgres session factory is missing.

	Applied consistently to every endpoint in this router (POST/GET/DELETE):
	returning an empty list on GET would lie — conversations live in Postgres
	and may exist once the store is back. A 503 keeps the frontend from
	silently showing an empty state.
	"""
	return HTTPException(
		status_code=503,
		detail=UnifiedResponse(
			status='error',
			error=ApiError(
				code='SERVICE_UNAVAILABLE',
				cause='Conversation store unavailable (Postgres offline)',
			),
		).model_dump(),
	)


def _get_session_factory(request: Request):
	"""Return the app session factory or raise a degraded 503."""
	factory = getattr(request.app.state, 'session_factory', None)
	if factory is None:
		raise _store_unavailable()
	return factory


def _caller_role(request: Request) -> str:
	"""Rol del caller para ownership.

	Sesiones Clerk exponen ``request.state.user_role`` (owner/admin/member).
	API keys no tienen clerk_user_id: se asumen admin (visibilidad completa).
	"""
	clerk_user_id = getattr(request.state, 'clerk_user_id', None)
	if clerk_user_id:
		return getattr(request.state, 'user_role', 'member')
	return getattr(request.state, 'user_role', 'admin')


async def _resolve_user_id(request: Request, session) -> uuid.UUID | None:
	"""Resuelve el ORM user id desde ``clerk_user_id`` (None si es API key)."""
	clerk_user_id = getattr(request.state, 'clerk_user_id', None)
	if not clerk_user_id:
		return None
	return await session.scalar(
		select(User.id).where(User.clerk_user_id == clerk_user_id).limit(1)
	)


def _body_profile_id(body: dict) -> uuid.UUID | None:
	"""Perfil opcional enviado por el frontend en el body del POST."""
	raw = body.get('profile_id')
	if not raw:
		return None
	try:
		return uuid.UUID(str(raw))
	except (ValueError, TypeError):
		return None


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.post(
	'/v1/conversations',
	status_code=200,
	summary='Save or update a conversation',
)
async def save_conversation(request: Request, body: dict):
	"""Create or update a conversation in Postgres.

	The frontend sends the full conversation object:

	.. code-block:: json

	    {
	      "id": "abc123",
	      "title": "New Chat",
	      "messages": [{"role": "user", "content": "hi", ...}],
	      ...
	    }

	If ``id`` does not exist in Postgres a new conversation is **created**
	(UUID estable derivado del id opaco). If it does exist the fields are
	**updated** and new messages appended (idempotente por contenido).
	"""
	tenant_id = _tenant_uuid(request)
	factory = _get_session_factory(request)

	conv_id = body.get('id') or body.get('conversation_id')
	if not conv_id:
		raise _not_found(code='MISSING_ID', message='Field "id" is required')

	async with factory() as session:
		user_id = await _resolve_user_id(request, session)
		await repo_upsert_conversation(
			session,
			tenant_id=tenant_id,
			user_id=user_id,
			profile_id=_body_profile_id(body),
			conversation_id=str(conv_id),
			title=body.get('title') or '',
			messages=body.get('messages', []),
		)
	return JSONResponse(content={'conversation_id': str(conv_id)})


@router.get(
	'/v1/conversations',
	status_code=200,
	summary='List all conversations for the authenticated tenant',
)
async def list_conversations(request: Request):
	"""Return summaries for all conversations, newest first.

	Returns a **JSON array** (not wrapped) so the frontend can use
	``Array.isArray()`` directly. Keys are camelCase, ready for the UI.
	"""
	tenant_id = _tenant_uuid(request)
	factory = _get_session_factory(request)

	async with factory() as session:
		user_id = await _resolve_user_id(request, session)
		conversations = await repo_list_conversations(
			session,
			tenant_id=tenant_id,
			user_id=user_id,
			role=_caller_role(request),
		)
	return JSONResponse(content=conversations)


@router.get(
	'/v1/conversations/{conversation_id}',
	status_code=200,
	summary='Get a full conversation by ID',
)
async def get_conversation(request: Request, conversation_id: str):
	"""Return the full conversation object including ``messages``."""
	tenant_id = _tenant_uuid(request)
	factory = _get_session_factory(request)

	async with factory() as session:
		conv = await repo_get_conversation(session, tenant_id, conversation_id)
	if not conv:
		raise _not_found()
	return JSONResponse(content=conv)


@router.delete(
	'/v1/conversations/{conversation_id}',
	status_code=204,
	summary='Delete a conversation',
)
async def delete_conversation(request: Request, conversation_id: str):
	"""Remove a conversation and its messages (CASCADE).

	404 both when the conversation does not exist and when the caller lacks
	permission — existence and permission are not distinguished to the client.
	"""
	tenant_id = _tenant_uuid(request)
	factory = _get_session_factory(request)

	async with factory() as session:
		user_id = await _resolve_user_id(request, session)
		deleted = await repo_delete_conversation(
			session,
			tenant_id=tenant_id,
			conversation_id=conversation_id,
			user_id=user_id,
			role=_caller_role(request),
		)
	if not deleted:
		raise _not_found()
	return JSONResponse(status_code=204, content=None)


@router.delete(
	'/v1/conversations',
	status_code=200,
	summary='Delete all conversations for the tenant/user',
)
async def delete_all_conversations(request: Request):
	"""Borra todas las conversaciones del tenant (owner/admin) o solo las
	propias (member), devolviendo el count de filas eliminadas.

	Ownership y tenant se resuelven del JWT (``request.state``), igual que
	los demás endpoints del router. No delinee con
	``DELETE /v1/conversations/{conversation_id}``: el path literal solo
	coincide cuando no hay segmento de id.
	"""
	tenant_id = _tenant_uuid(request)
	factory = _get_session_factory(request)

	async with factory() as session:
		user_id = await _resolve_user_id(request, session)
		deleted = await repo_delete_all(
			session,
			tenant_id=tenant_id,
			user_id=user_id,
			role=_caller_role(request),
		)
	return JSONResponse(content={'deleted': deleted})
