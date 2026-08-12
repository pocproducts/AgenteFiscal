"""Redis-backed store — conversations + tenant admin (cutover Phase 5).

Business data (API keys, apps, plans, developers) left Redis in the Phase 5
cutover; their source of truth is now Postgres behind the hexagonal
``fiscal_agent.ports.api_keys`` port (see ``adapters/db_api_keys.py``).

What remains here:
  - ``RedisStore`` — best-effort conversation cache (frontend does not consume
    it yet; kept intentionally) and its Redis key schema for conversations.
  - ``TenantStore`` — tenant admin CRUD for the ``/v1/admin/tenants`` routes
    (outside the essential cutover scope; scheduled for migration later).

Rate limiting (``api/rate_limiter.py``) and the Clerk JWKS cache also live in
Redis, unchanged.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from redis.asyncio import Redis

from fiscal_agent.domain.models import Tenant

logger = logging.getLogger(__name__)

# ── Conversation key schema ────────────────────────────────────────

_KEY_CONV = 'tenant:{tid}:conv:{cid}'  # Hash -> conversation fields
_KEY_CONV_ALL = 'tenant:{tid}:conv:all'  # Set -> conversation_ids
_CONV_TTL = 7776000  # 90 days in seconds

# ── Tenant key schema ──────────────────────────────────────────────

_KEY_TENANT = 'tenant:tenant:{}'  # Hash -> Tenant fields
_KEY_TENANT_BY_CUIT = 'tenant:tenant:by_cuit:{}'  # String -> tenant_id
_KEY_TENANT_ALL = 'tenant:tenant:all'  # Set -> tenant_ids


class StoreError(Exception):
	"""Base exception for store operations."""


class NotFoundError(StoreError):
	"""Raised when a resource is not found."""

	def __init__(self, code: str, message: str) -> None:
		self.code = code
		super().__init__(message)


class RedisStore:
	"""Redis-backed store for best-effort conversations.

	Wraps all Redis conversation operations with typed methods. Full entities
	(documents/messages) round-trip through ``model_dump(mode='json')`` /
	``model_validate()`` style JSON (see ``_serialize_for_redis``).
	"""

	def __init__(self, redis_client: Redis) -> None:
		self.redis = redis_client

	# ── Helpers ────────────────────────────────────────────────────

	@staticmethod
	def _generate_id() -> str:
		"""Generate a short unique ID (12 hex chars)."""
		return uuid.uuid4().hex[:12]

	@staticmethod
	def _serialize_for_redis(data: dict) -> dict:
		"""Convert model_dump data to Redis-safe strings preserving types.

		Uses JSON serialization per field so that booleans, lists, None,
		and other non-string types round-trip correctly through Redis
		(which stores all hash values as strings).
		"""
		return {k: json.dumps(v, ensure_ascii=False) for k, v in data.items()}

	@staticmethod
	def _deserialize_from_redis(raw: dict) -> dict:
		"""Convert Redis hash string values back to proper Python types.

		Each value is parsed through JSON to restore booleans, lists,
		None, and enums that were serialized by ``_serialize_for_redis``.
		"""
		result = {}
		for k, v in raw.items():
			try:
				result[k] = json.loads(v)
			except (json.JSONDecodeError, TypeError):
				result[k] = v
		return result

	@staticmethod
	def _deserialize(model_class, data: dict):
		"""Deserialize a Redis hash dict back into a Pydantic model."""
		parsed = RedisStore._deserialize_from_redis(data)
		return model_class.model_validate(parsed)

	# ── Conversation CRUD ────────────────────────────────────────────

	async def save_conversation(
		self,
		tenant_id: str,
		conversation_id: str,
		messages: list,
		title: str = '',
	) -> str:
		"""Create or update a conversation. Returns the conversation_id."""
		key = _KEY_CONV.format(tid=tenant_id, cid=conversation_id)
		now = datetime.now(timezone.utc).isoformat()

		exists = await self.redis.exists(key)
		mapping: dict[str, object] = {
			'id': conversation_id,
			'title': title,
			'messages': messages,
			'updated_at': now,
		}

		if not exists:
			mapping['created_at'] = now

		await self.redis.hset(
			key,
			mapping=self._serialize_for_redis(mapping),
		)
		await self.redis.expire(key, _CONV_TTL)

		if not exists:
			await self.redis.sadd(_KEY_CONV_ALL.format(tid=tenant_id), conversation_id)

		return conversation_id

	async def get_conversation(self, tenant_id: str, conversation_id: str) -> dict | None:
		"""Fetch a full conversation by ID. Returns ``None`` if not found."""
		key = _KEY_CONV.format(tid=tenant_id, cid=conversation_id)
		data = await self.redis.hgetall(key)
		if not data:
			return None
		# Touch TTL on read
		await self.redis.expire(key, _CONV_TTL)
		return self._deserialize_from_redis(data)

	async def list_conversations(self, tenant_id: str) -> list[dict]:
		"""List summary of conversations, ordered by updated_at desc."""
		all_key = _KEY_CONV_ALL.format(tid=tenant_id)
		ids = await self.redis.smembers(all_key)
		conversations: list[dict] = []
		for cid in ids:
			key = _KEY_CONV.format(tid=tenant_id, cid=cid)
			data = await self.redis.hgetall(key)
			if data:
				parsed = self._deserialize_from_redis(data)
				messages = parsed.get('messages', [])
				last_msg = messages[-1]['content'] if messages else ''
				conversations.append(
					{
						'id': parsed.get('id', cid),
						'title': parsed.get('title', ''),
						'message_count': len(messages),
						'updated_at': parsed.get('updated_at', ''),
						'preview': last_msg[:80] if last_msg else '',
					}
				)
		conversations.sort(key=lambda c: c.get('updated_at', ''), reverse=True)
		return conversations

	async def append_messages(
		self,
		tenant_id: str,
		conversation_id: str,
		messages: list[dict],
	) -> str:
		"""Atomically append messages to a conversation. Creates if new.

		Cada mensaje es un dict con al menos ``{role, content}``.
		Desde junio 2026 acepta campos opcionales (Issue 4):
		``pipeline_steps`` (list[str]), ``wizard_data``, ``id``, ``created_at``.

		Title is auto-generated from the first user message content
		on creation. TTL is refreshed on every call.
		"""
		key = _KEY_CONV.format(tid=tenant_id, cid=conversation_id)
		now = datetime.now(timezone.utc).isoformat()

		data = await self.redis.hgetall(key)

		if data:
			# Existing conversation — append messages
			parsed = self._deserialize_from_redis(data)
			existing_messages = parsed.get('messages', [])
			existing_messages.extend(messages)
			await self.redis.hset(
				key,
				mapping=self._serialize_for_redis(
					{
						'messages': existing_messages,
						'updated_at': now,
					}
				),
			)
		else:
			# New conversation — create with title from first user message
			title = ''
			for msg in messages:
				if msg.get('role') == 'user' and msg.get('content'):
					content = msg['content']
					title = (content[:50] + '...') if len(content) > 50 else content
					break

			await self.redis.hset(
				key,
				mapping=self._serialize_for_redis(
					{
						'id': conversation_id,
						'title': title,
						'messages': messages,
						'created_at': now,
						'updated_at': now,
					}
				),
			)
			await self.redis.sadd(_KEY_CONV_ALL.format(tid=tenant_id), conversation_id)

		# ponytail: HSET rewrite; upgrade to JSON.ARRAPPEND if messages exceed 100 per conv
		await self.redis.expire(key, _CONV_TTL)
		return conversation_id

	async def delete_conversation(self, tenant_id: str, conversation_id: str) -> None:
		"""Remove a conversation and its index entry."""
		key = _KEY_CONV.format(tid=tenant_id, cid=conversation_id)
		await self.redis.delete(key)
		await self.redis.srem(_KEY_CONV_ALL.format(tid=tenant_id), conversation_id)


class TenantStore:
	"""Redis-backed store for Tenant entities (admin tenant management).

	Shares the same Redis client and serialization helpers as ``RedisStore``.
	Uses its own key prefix space: ``tenant:tenant:*``. Kept on Redis for the
	essential-scope cutover; scheduled for a Postgres migration later.
	"""

	def __init__(self, redis_client: Redis) -> None:
		self.redis = redis_client

	# ── CRUD ──────────────────────────────────────────────────────────

	async def create(self, tenant: Tenant) -> Tenant:
		"""Store a new tenant. Returns the tenant with its generated ID."""
		await self.redis.hset(
			_KEY_TENANT.format(tenant.id),
			mapping=RedisStore._serialize_for_redis(tenant.model_dump(mode='json')),
		)
		await self.redis.set(_KEY_TENANT_BY_CUIT.format(tenant.cuit), tenant.id)
		await self.redis.sadd(_KEY_TENANT_ALL, tenant.id)
		return tenant

	async def get(self, id: str) -> Tenant | None:
		"""Fetch a tenant by ID. Returns ``None`` if not found."""
		data = await self.redis.hgetall(_KEY_TENANT.format(id))
		if not data:
			return None
		return RedisStore._deserialize(Tenant, data)

	async def get_by_cuit(self, cuit: str) -> Tenant | None:
		"""Fetch a tenant by CUIT. Returns ``None`` if not found."""
		tenant_id = await self.redis.get(_KEY_TENANT_BY_CUIT.format(cuit))
		if not tenant_id:
			return None
		return await self.get(tenant_id)

	async def list_all(self) -> list[Tenant]:
		"""Return all tenants."""
		ids = await self.redis.smembers(_KEY_TENANT_ALL)
		if not ids:
			return []
		tenants: list[Tenant] = []
		for tid in ids:
			data = await self.redis.hgetall(_KEY_TENANT.format(tid))
			if data:
				tenants.append(RedisStore._deserialize(Tenant, data))
		return tenants

	async def update(self, id: str, updates: dict) -> None:
		"""Update specific fields of a tenant. Does NOT touch CUIT index."""
		if not updates:
			return
		serialized = RedisStore._serialize_for_redis(updates)
		await self.redis.hset(_KEY_TENANT.format(id), mapping=serialized)

	async def delete(self, id: str) -> None:
		"""Remove a tenant and its indexes."""
		tenant = await self.get(id)
		if tenant is None:
			return
		await self.redis.delete(_KEY_TENANT.format(id))
		await self.redis.delete(_KEY_TENANT_BY_CUIT.format(tenant.cuit))
		await self.redis.srem(_KEY_TENANT_ALL, id)