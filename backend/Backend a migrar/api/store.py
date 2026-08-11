"""Redis-backed data store for tenant management.

Replaces the in-memory store with Redis for data persistence
across server restarts. All entity data is stored via Redis Hashes
and round-trips through ``model_dump(mode='json')`` /
``model_validate()``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone

from redis.asyncio import Redis

from fiscal_agent.models import ApiKey, App, Developer, Plan, PlanTier, Tenant
from fiscal_agent.config import get_settings

logger = logging.getLogger(__name__)

# ── Redis key schema prefixes ───────────────────────────────────────

_KEY_DEVELOPER = 'tenant:developer:{}'  # Hash -> Developer fields
_KEY_APP = 'tenant:app:{}'  # Hash -> App fields
_KEY_APIKEY = 'tenant:apikey:{}'  # Hash -> ApiKey fields
_KEY_PLAN = 'tenant:plan:{}'  # Hash -> Plan fields
_KEY_KEYHASH = 'tenant:keyhash:{}'  # String -> api_key_id
_KEY_DEV_BY_EMAIL = 'tenant:developer:by_email:{}'  # String -> developer_id

_KEY_DEV_APPS = 'tenant:developer:apps:{}'  # Set    -> app_ids
_KEY_APP_KEYS = 'tenant:app:keys:{}'  # Set    -> api_key_ids

_KEY_TENANT = 'tenant:tenant:{}'  # Hash -> Tenant fields
_KEY_TENANT_BY_CUIT = 'tenant:tenant:by_cuit:{}'  # String -> tenant_id
_KEY_TENANT_ALL = 'tenant:tenant:all'  # Set -> tenant_ids
_KEY_TENANT_KEYS = 'tenant:tenant:keys:{}'  # Set -> api_key_ids (Clerk flow)

# ── Conversation key schema ────────────────────────────────────────

_KEY_CONV = 'tenant:{tid}:conv:{cid}'  # Hash -> conversation fields
_KEY_CONV_ALL = 'tenant:{tid}:conv:all'  # Set -> conversation_ids
_CONV_TTL = 7776000  # 90 days in seconds


class StoreError(Exception):
	"""Base exception for store operations."""


class NotFoundError(StoreError):
	"""Raised when a resource is not found."""

	def __init__(self, code: str, message: str) -> None:
		self.code = code
		super().__init__(message)


class RedisStore:
	"""Redis-backed store for tenant entities.

	Wraps all Redis operations with typed methods that accept and return
	Pydantic models. Uses ``model_dump(mode='json')`` for serialization
	and ``model_validate()`` for deserialization.
	"""

	def __init__(self, redis_client: Redis) -> None:
		self.redis = redis_client

	# ── Helpers ────────────────────────────────────────────────────

	@staticmethod
	def _generate_id() -> str:
		"""Generate a short unique ID (12 hex chars)."""
		return uuid.uuid4().hex[:12]

	@staticmethod
	def _hash_key(key: str) -> str:
		"""SHA-256 hash for API key lookup."""
		return hashlib.sha256(key.encode()).hexdigest()

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

	# ── Developer CRUD ─────────────────────────────────────────────

	async def register_developer(self, name: str, email: str) -> Developer:
		"""Register a new developer account."""
		dev_id = self._generate_id()
		dev = Developer(
			id=dev_id,
			name=name,
			email=email,
			created_at=datetime.now(timezone.utc),
			is_active=True,
		)
		await self.redis.hset(
			_KEY_DEVELOPER.format(dev_id),
			mapping=self._serialize_for_redis(dev.model_dump(mode='json')),
		)
		await self.redis.set(_KEY_DEV_BY_EMAIL.format(email), dev_id)
		return dev

	async def get_developer_by_email(self, email: str) -> Developer | None:
		"""Look up a developer by email."""
		dev_id = await self.redis.get(_KEY_DEV_BY_EMAIL.format(email))
		if dev_id is None:
			return None
		data = await self.redis.hgetall(_KEY_DEVELOPER.format(dev_id))
		if not data:
			return None
		return self._deserialize(Developer, data)

	# ── App CRUD ───────────────────────────────────────────────────

	async def create_app(self, developer_id: str, name: str, environment: str) -> App | None:
		"""Create a new app for a developer.

		Returns ``None`` if the developer doesn't exist.
		"""
		dev_exists = await self.redis.hexists(_KEY_DEVELOPER.format(developer_id), 'id')
		if not dev_exists:
			return None

		app_id = self._generate_id()
		app = App(
			id=app_id,
			developer_id=developer_id,
			name=name,
			environment=environment,
			status='active',
		)
		await self.redis.hset(
			_KEY_APP.format(app_id),
			mapping=self._serialize_for_redis(app.model_dump(mode='json')),
		)
		# Maintain developer -> apps index
		await self.redis.sadd(_KEY_DEV_APPS.format(developer_id), app_id)
		return app

	# ── API Key CRUD ───────────────────────────────────────────────

	async def create_api_key(
		self,
		app_id: str,
		*,
		tenant_id: str | None = None,
		scopes: list[str] | None = None,
	) -> dict | None:
		"""Generate a new API key for an app.

		Keyword args:
			tenant_id: Optional tenant to scope the key to (Clerk flow).
			scopes: Optional list of scopes for the key.

		Returns ``{'api_key': ApiKey, 'full_key': str}`` or ``None``
		if the app doesn't exist. The full key is only returned once.
		"""
		app_exists = await self.redis.hexists(_KEY_APP.format(app_id), 'id')
		if not app_exists:
			return None

		full_key = f'fa_{secrets.token_hex(16)}'
		api_key = ApiKey(
			id=self._generate_id(),
			app_id=app_id,
			key_preview=full_key[-4:],
			is_active=True,
			scopes=scopes or [],
			tenant_id=tenant_id,
			created_at=datetime.now(timezone.utc),
		)
		await self.redis.hset(
			_KEY_APIKEY.format(api_key.id),
			mapping=self._serialize_for_redis(api_key.model_dump(mode='json')),
		)
		await self.redis.set(_KEY_KEYHASH.format(self._hash_key(full_key)), api_key.id)
		# Maintain app -> keys index
		await self.redis.sadd(_KEY_APP_KEYS.format(app_id), api_key.id)
		# Maintain tenant -> keys index (Clerk flow)
		if tenant_id:
			await self.redis.sadd(_KEY_TENANT_KEYS.format(tenant_id), api_key.id)
		return {'api_key': api_key, 'full_key': full_key}

	async def list_developer_keys(self, developer_id: str) -> list[ApiKey]:
		"""List all API keys across all apps owned by a developer."""
		dev_exists = await self.redis.hexists(_KEY_DEVELOPER.format(developer_id), 'id')
		if not dev_exists:
			return []

		# Get all app IDs for this developer
		app_ids = await self.redis.smembers(_KEY_DEV_APPS.format(developer_id))
		if not app_ids:
			return []

		# Collect all key IDs for those apps
		key_ids: list[str] = []
		for app_id in app_ids:
			app_key_ids = await self.redis.smembers(_KEY_APP_KEYS.format(app_id))
			key_ids.extend(app_key_ids)

		# Fetch and deserialize each key
		keys: list[ApiKey] = []
		for kid in key_ids:
			data = await self.redis.hgetall(_KEY_APIKEY.format(kid))
			if data:
				keys.append(self._deserialize(ApiKey, data))
		return keys

	async def list_tenant_keys(self, tenant_id: str) -> list[ApiKey]:
		"""List all API keys belonging to a tenant (Clerk flow)."""
		key_ids = await self.redis.smembers(_KEY_TENANT_KEYS.format(tenant_id))
		if not key_ids:
			return []

		keys: list[ApiKey] = []
		for kid in key_ids:
			data = await self.redis.hgetall(_KEY_APIKEY.format(kid))
			if data:
				keys.append(self._deserialize(ApiKey, data))
		return keys

	async def deactivate_key(self, key_id: str, tenant_id: str) -> bool:
		"""Set ``is_active=False`` for a key, verifying tenant ownership.

		Returns ``True`` if the key existed and was deactivated.
		``False`` if the key doesn't exist or doesn't belong to the tenant.
		"""
		data = await self.redis.hgetall(_KEY_APIKEY.format(key_id))
		if not data:
			return False
		api_key = self._deserialize(ApiKey, data)
		if api_key.tenant_id != tenant_id:
			return False
		await self.redis.hset(
			_KEY_APIKEY.format(key_id),
			mapping={'is_active': json.dumps(False)},
		)
		return True

	# ── Plan helpers ───────────────────────────────────────────────

	async def _resolve_plan(self, scopes: list[str]) -> Plan | None:
		"""Find a plan whose scopes cover the given scopes."""
		cursor = 0
		plans: list[Plan] = []
		while True:
			cursor, keys = await self.redis.scan(cursor, match=_KEY_PLAN.format('*'), count=50)
			for key in keys:
				data = await self.redis.hgetall(key)
				if data:
					plans.append(self._deserialize(Plan, data))
			if cursor == 0:
				break

		if not plans:
			return None

		# Try exact match first: plan covers ALL key scopes
		plan_scope_sets = {p.id: set(p.scopes) for p in plans}
		key_scope_set = set(scopes)

		for plan in plans:
			if key_scope_set.issubset(plan_scope_sets[plan.id]):
				return plan

		# Fallback: any plan with at least one matching scope
		for plan in plans:
			if key_scope_set & plan_scope_sets[plan.id]:
				return plan

		# Absolute fallback: first plan
		return plans[0]

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

	# ── Seed ───────────────────────────────────────────────────────

	async def seed_defaults(self) -> None:
		"""Seed default plans and admin developer if Redis is empty.

		Checks if any ``tenant:*`` keys exist. If data is present,
		returns immediately (idempotent). Otherwise creates:
		- Free plan with basic scopes
		- Admin developer with a default app and API key
		"""
		# Check if plans already exist (not just any tenant:* key,
		# which also matches TenantStore's tenant:tenant:* keys).
		cursor = 0
		has_data = False
		while True:
			cursor, keys = await self.redis.scan(cursor, match=_KEY_PLAN.format('*'), count=10)
			if keys:
				has_data = True
				break
			if cursor == 0:
				break

		if has_data:
			logger.info('Planes ya existen — se omite seed')
			return

		logger.info('Redis vacío — sembrando datos por defecto')

		# ── Free plan ──────────────────────────────────────────────
		free_plan = Plan(
			id=self._generate_id(),
			name='Free',
			scopes=['calendar:read', 'taxpayer:read', 'report:read'],
			rate_limit_rpm=10,
			rate_limit_rpd=100,
		)
		await self.redis.hset(
			_KEY_PLAN.format(free_plan.id),
			mapping=self._serialize_for_redis(free_plan.model_dump(mode='json')),
		)

		# ── Admin developer ────────────────────────────────────────
		admin_dev = Developer(
			id=self._generate_id(),
			name='Admin',
			email='admin@fiscal-agent.local',
			created_at=datetime.now(timezone.utc),
			is_active=True,
		)
		await self.redis.hset(
			_KEY_DEVELOPER.format(admin_dev.id),
			mapping=self._serialize_for_redis(admin_dev.model_dump(mode='json')),
		)
		await self.redis.set(_KEY_DEV_BY_EMAIL.format(admin_dev.email), admin_dev.id)

		# ── Admin app ──────────────────────────────────────────────
		admin_app = App(
			id=self._generate_id(),
			developer_id=admin_dev.id,
			name='Admin App',
			environment='production',
			status='active',
		)
		await self.redis.hset(
			_KEY_APP.format(admin_app.id),
			mapping=self._serialize_for_redis(admin_app.model_dump(mode='json')),
		)
		await self.redis.sadd(_KEY_DEV_APPS.format(admin_dev.id), admin_app.id)

		# ── Admin API key (full scopes) ────────────────────────────
		full_key = f'fa_{secrets.token_hex(16)}'
		admin_key = ApiKey(
			id=self._generate_id(),
			app_id=admin_app.id,
			key_preview=full_key[-4:],
			is_active=True,
			scopes=[
				'admin:read',
				'admin:write',
				'calendar:read',
				'calendar:write',
				'taxpayer:read',
				'report:read',
				'report:write',
			],
			created_at=datetime.now(timezone.utc),
		)
		await self.redis.hset(
			_KEY_APIKEY.format(admin_key.id),
			mapping=self._serialize_for_redis(admin_key.model_dump(mode='json')),
		)
		await self.redis.set(_KEY_KEYHASH.format(self._hash_key(full_key)), admin_key.id)
		await self.redis.sadd(_KEY_APP_KEYS.format(admin_app.id), admin_key.id)

		logger.info('Admin API key creada: %s', full_key)

		# ── Dev API key (opcional, desde env) ──────────────────────────
		dev_key = os.getenv('DEV_API_KEY', '').strip()
		if dev_key:
			dev_api_key = ApiKey(
				id=self._generate_id(),
				app_id=admin_app.id,
				key_preview=dev_key[-4:],
				is_active=True,
				scopes=[
					'admin:read',
					'admin:write',
					'calendar:read',
					'calendar:write',
					'taxpayer:read',
					'report:read',
					'report:write',
				],
				created_at=datetime.now(timezone.utc),
			)
			await self.redis.hset(
				_KEY_APIKEY.format(dev_api_key.id),
				mapping=self._serialize_for_redis(dev_api_key.model_dump(mode='json')),
			)
			await self.redis.set(_KEY_KEYHASH.format(self._hash_key(dev_key)), dev_api_key.id)
			await self.redis.sadd(_KEY_APP_KEYS.format(admin_app.id), dev_api_key.id)
			logger.info('Dev API key creada desde env: %s', dev_key)


class TenantStore:
	"""Redis-backed store for Tenant entities.

	Shares the same Redis client and serialization helpers as ``RedisStore``.
	Uses its own key prefix space: ``tenant:tenant:*``.
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

	# ── Seed ──────────────────────────────────────────────────────────

	async def seed_defaults(self) -> None:
		"""Create Tenant 1 (Estudio Contable) from .env + clients.yaml.

		Idempotent — checks ``SMEMBERS tenant:tenant:all`` first.
		After creating Tenant 1, links the admin developer's API keys.
		"""
		existing = await self.redis.scard(_KEY_TENANT_ALL)
		if existing > 0:
			logger.info('Redis ya tiene tenants — se omite seed de tenant')
			return

		settings = get_settings()
		cuit = settings.cuit
		clave_fiscal = settings.clave_fiscal

		# ── Load clients.yaml (best-effort) ──────────────────────────
		clientes: list[dict] = []
		provincias: list[str] = []
		try:
			import yaml
			from pathlib import Path

			yaml_path = Path('clients.yaml')
			if yaml_path.exists():
				with open(yaml_path) as f:
					config = yaml.safe_load(f)
				clientes = config.get('clientes', [])
				seen: set[str] = set()
				for c in clientes:
					for p in c.get('provincias', []):
						if p not in seen:
							seen.add(p)
							provincias.append(p)
		except Exception:
			logger.warning('No se pudo cargar clients.yaml para seed de tenant', exc_info=True)

		tenant = Tenant(
			id=RedisStore._generate_id(),
			name='Estudio Contable',
			plan_tier=PlanTier.free,
			cuit=cuit,
			clave_fiscal=clave_fiscal,
			clientes=clientes,
			provincias=provincias,
			is_active=True,
		)
		await self.create(tenant)

		# ── Link admin developer's keys to this tenant ────────────────
		admin_dev_id = await self.redis.get('tenant:developer:by_email:admin@fiscal-agent.local')
		if admin_dev_id:
			app_ids = await self.redis.smembers('tenant:developer:apps:{}'.format(admin_dev_id))
			for app_id in app_ids:
				key_ids = await self.redis.smembers('tenant:app:keys:{}'.format(app_id))
				for kid in key_ids:
					await self.redis.hset(
						'tenant:apikey:{}'.format(kid),
						mapping={'tenant_id': json.dumps(tenant.id)},
					)
			logger.info('API keys del admin vinculadas al tenant %s', tenant.id)

		logger.info('Tenant 1 creado: %s (%s)', tenant.id, tenant.name)
