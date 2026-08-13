"""Conversations CRUD router — stores chat conversations in Redis.

Endpoints match the paths expected by ``api-client.js`` (frontend):
  - ``POST   /v1/conversations``        — save (create or update)
  - ``GET    /v1/conversations``         — list summaries
  - ``GET    /v1/conversations/{id}``    — get full conversation
  - ``DELETE /v1/conversations/{id}``    — delete

Response keys use camelCase (``updatedAt``, ``messageCount``) to match the
``useChat.js`` frontend expectations without a transform layer.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from agente_fiscal.api.store import RedisStore
from agente_fiscal.domain.models import ApiError, UnifiedResponse

router = APIRouter(tags=['chat'])

# ── Helpers ───────────────────────────────────────────────────────────────


def _tenant_id(request: Request) -> str:
	"""Extract tenant_id from auth middleware state, or raise 401."""
	tid = getattr(request.state, 'tenant_id', None)
	if not tid:
		raise HTTPException(
			status_code=401,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(code='UNAUTHORIZED', cause='Authentication required'),
			).model_dump(),
		)
	return tid


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
	"""Shortcut for the 503 returned when the Redis store is unavailable.

	Applied consistently to every endpoint in this router (POST/GET/DELETE):
	returning an empty list on GET would lie — conversations live in Redis and
	may exist on another instance once Redis is back. A 503 keeps the frontend
	from silently showing an empty state.
	"""
	return HTTPException(
		status_code=503,
		detail=UnifiedResponse(
			status='error',
			error=ApiError(
				code='SERVICE_UNAVAILABLE',
				cause='Conversation store unavailable (Redis offline)',
			),
		).model_dump(),
	)


def _get_store(request: Request) -> RedisStore:
	"""Return the Redis store or raise a degraded 503 when Redis is down."""
	store = getattr(request.app.state, 'store', None)
	if store is None:
		raise _store_unavailable()
	return store


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.post(
	'/v1/conversations',
	status_code=200,
	summary='Save or update a conversation',
)
async def save_conversation(request: Request, body: dict):
	"""Create or update a conversation.

	The frontend sends the full conversation object:

	.. code-block:: json

	    {
	      "id": "abc123",
	      "title": "New Chat",
	      "messages": [{"role": "user", "content": "hi", ...}],
	      ...
	    }

	If ``id`` does not exist in Redis a new conversation is **created**.
	If it does exist the fields are **updated**.
	"""
	tenant_id = _tenant_id(request)
	store = _get_store(request)

	conv_id = body.get('id') or body.get('conversation_id')
	if not conv_id:
		raise _not_found(code='MISSING_ID', message='Field "id" is required')

	messages = body.get('messages', [])
	title = body.get('title', '')

	result = await store.save_conversation(tenant_id, conv_id, messages, title)
	return JSONResponse(content={'conversation_id': result})


@router.get(
	'/v1/conversations',
	status_code=200,
	summary='List all conversations for the authenticated tenant',
)
async def list_conversations(request: Request):
	"""Return summaries for all conversations, newest first.

	Returns a **JSON array** (not wrapped) so the frontend can use
	``Array.isArray()`` directly.
	"""
	tenant_id = _tenant_id(request)
	store = _get_store(request)

	raw = await store.list_conversations(tenant_id)
	# Convert snake_case → camelCase for the frontend
	conversations = []
	for c in raw:
		conversations.append(
			{
				'id': c['id'],
				'title': c['title'],
				'messageCount': c['message_count'],
				'updatedAt': c['updated_at'],
				'preview': c.get('preview', ''),
				'pinned': False,
				'folder': 'Work Projects',
			}
		)
	return JSONResponse(content=conversations)


@router.get(
	'/v1/conversations/{conversation_id}',
	status_code=200,
	summary='Get a full conversation by ID',
)
async def get_conversation(request: Request, conversation_id: str):
	"""Return the full conversation object including ``messages``."""
	tenant_id = _tenant_id(request)
	store = _get_store(request)

	conv = await store.get_conversation(tenant_id, conversation_id)
	if not conv:
		raise _not_found()
	return JSONResponse(content=conv)


@router.delete(
	'/v1/conversations/{conversation_id}',
	status_code=204,
	summary='Delete a conversation',
)
async def delete_conversation(request: Request, conversation_id: str):
	"""Remove a conversation and its index entry."""
	tenant_id = _tenant_id(request)
	store = _get_store(request)

	await store.delete_conversation(tenant_id, conversation_id)
	return JSONResponse(status_code=204, content=None)
