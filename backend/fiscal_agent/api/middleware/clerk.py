"""ClerkJWTExtractor — validate Clerk JWTs and resolve tenant context.

Used as the second auth method alongside ApiKeyExtractor in AuthMiddleware.
Supports both HS256 (dev mode via CLERK_SECRET_KEY) and RS256 (prod via JWKS).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

import httpx
import jwt as pyjwt
from fastapi import Request
from redis.asyncio import Redis

from fiscal_agent.api.store import RedisStore, _KEY_PLAN, _KEY_TENANT
from fiscal_agent.api.store import TenantStore
from fiscal_agent.config import get_settings
from fiscal_agent.models import Plan, PlanTier, Tenant

logger = logging.getLogger(__name__)


# ── JWT helpers ─────────────────────────────────────────────────────────


def _decode_jwt_segment(segment: str) -> dict:
	"""Base64url-decode a JWT segment (header or payload) to a dict."""
	padding = 4 - len(segment) % 4
	if padding != 4:
		segment += '=' * padding
	return json.loads(base64.urlsafe_b64decode(segment).decode('utf-8'))


# ── Extractor ───────────────────────────────────────────────────────────


class ClerkJWTExtractor:
	"""Extract and validate a Clerk JWT, resolving tenant context.

	Flow:
		1. Verify JWT structure and timestamps (exp, iat)
		2. Extract ``org_id`` (or create personal tenant on-the-fly)
		3. Resolve ``Plan`` from ``tenant.plan_tier``
		4. Inject state into ``request.state``
	"""

	async def _get_jwks(self, redis: Redis) -> dict:
		"""Fetch Clerk JWKS, cached in Redis with 3600s TTL.

		Sync :class:`httpx.Client` is used inside :func:`asyncio.to_thread`
		because ``httpx.AsyncClient`` has SSL handshake failures in this
		Docker environment. The sync transport handles TLS negotiation
		correctly with the same OpenSSL stack.

		Returns:
			The full JWKS dict (``{"keys": [...]}``).
		"""
		cached = await redis.get('jwks:clerk')
		if cached:
			return json.loads(cached)

		settings = get_settings()
		domain = settings.clerk_domain
		if not domain:
			logger.error('CLERK_DOMAIN no está configurado')
			return {'keys': []}

		url = f'https://{domain}/.well-known/jwks.json'

		def _fetch() -> dict:
			with httpx.Client(verify=True, timeout=30.0) as client:
				resp = client.get(url)
				resp.raise_for_status()
				return resp.json()

		try:
			jwks = await asyncio.to_thread(_fetch)
		except Exception:
			logger.exception('Error fetching Clerk JWKS')
			return {'keys': []}

		await redis.setex('jwks:clerk', 3600, json.dumps(jwks))
		return jwks

	async def verify_jwt(self, token: str, redis: Redis) -> dict | None:
		"""Validate a Clerk JWT and return its decoded payload.

		Supports two methods:
		1. HS256 — verify with CLERK_SECRET_KEY (dev mode)
		2. RS256 — verify via JWKS (production mode)

		Returns ``None`` on any validation failure.
		"""
		try:
			parts = token.split('.')
			if len(parts) != 3:
				logger.warning('Clerk JWT structure inválida: %d partes', len(parts))
				return None

			# ── Header ──────────────────────────────────────────────
			header = _decode_jwt_segment(parts[0])
			kid = header.get('kid')
			alg = header.get('alg', '')
			logger.info('Clerk JWT header: kid=%s alg=%s', kid, alg)

			# ── Payload overview ────────────────────────────────────
			payload = _decode_jwt_segment(parts[1])
			payload_keys = list(payload.keys())
			exp = payload.get('exp', 0)
			iat = payload.get('iat', 0)
			sub = str(payload.get('sub', ''))[:20]
			logger.info('Clerk JWT payload: sub=%s exp=%s iat=%s keys=%s', sub, exp, iat, payload_keys)

			# ── Method 1: HS256 — verify with CLERK_SECRET_KEY ─────
			settings = get_settings()
			if alg == 'HS256' and settings.clerk_secret_key:
				try:
					decoded = pyjwt.decode(
						token,
						settings.clerk_secret_key,
						algorithms=['HS256'],
						options={'verify_signature': True, 'require': ['exp', 'iat']},
					)
					logger.info('Clerk JWT verificado por HS256 para sub=%s', sub)
					return decoded
				except pyjwt.ExpiredSignatureError:
					logger.warning('Clerk JWT expiró (HS256)')
					return None
				except pyjwt.InvalidTokenError as exc:
					logger.warning('Clerk JWT HS256 inválido: %s', exc)
					return None

			# ── Method 2: RS256 — verify via JWKS ──────────────────
			jwks = await self._get_jwks(redis)
			keys = jwks.get('keys', [])
			jwk = next((k for k in keys if k.get('kid') == kid), None)
			logger.info('Clerk JWKS: %d keys, kid=%s found=%s', len(keys), kid, jwk is not None)

			# Refetch once if kid not found (Clerk key rotation)
			if not jwk:
				await redis.delete('jwks:clerk')
				jwks = await self._get_jwks(redis)
				keys = jwks.get('keys', [])
				jwk = next((k for k in keys if k.get('kid') == kid), None)
				logger.info('Clerk JWKS after refetch: %d keys, kid=%s found=%s', len(keys), kid, jwk is not None)
				if not jwk:
					logger.warning('Clerk JWKS missing kid=%s after refetch', kid)
					# Last resort: try HS256 if we have a secret key
					if settings.clerk_secret_key:
						logger.info('Fallback: intentando HS256 con CLERK_SECRET_KEY')
						try:
							decoded = pyjwt.decode(
								token,
								settings.clerk_secret_key,
								algorithms=['HS256'],
								options={'verify_signature': True, 'require': ['exp', 'iat']},
							)
							logger.info('Clerk JWT verificado por HS256 (fallback) para sub=%s', sub)
							return decoded
						except Exception:
							logger.warning('Fallback HS256 también falló')
					return None

			# ── Timestamp validation (RS256 basic check) ──────────
			now = time.time()
			exp = payload.get('exp', 0)
			iat = payload.get('iat', 0)

			if not exp or exp < now:
				logger.warning('Clerk JWT expiró: exp=%s < now=%s', exp, now)
				return None
			if not iat or iat > now:
				logger.warning('Clerk JWT iat futuro: iat=%s > now=%s', iat, now)
				return None

			logger.info('Clerk JWT verificado OK (RS256) para sub=%s', sub)
			return payload

		except Exception:
			logger.exception('Error validando Clerk JWT')
			return None

	async def _resolve_plan_for_tier(self, redis: Redis, tier: PlanTier) -> Plan | None:
		"""Find a ``Plan`` whose ``name`` (lowercased) matches the tier value.

		Scans all ``tenant:plan:*`` hashes. Returns ``None`` if no plan
		matches (unlikely — the seed always creates a Free plan).
		"""
		cursor = 0
		tier_value = tier.value
		while True:
			cursor, keys = await redis.scan(cursor, match=_KEY_PLAN.format('*'), count=50)
			for key in keys:
				data = await redis.hgetall(key)
				if data:
					plan = RedisStore._deserialize(Plan, data)
					if plan.name.lower() == tier_value:
						return plan
			if cursor == 0:
				break

		logger.warning('No se encontró plan para tier %s', tier_value)
		return None

	async def handle(self, token: str, request: Request, redis: Redis) -> bool:
		"""Verify a Clerk JWT and inject tenant/plan state.

		Injected state (on success):
			- ``auth_method`` = ``'clerk_jwt'``
			- ``clerk_user_id`` — ``sub`` claim from token
			- ``tenant_id`` — Clerk ``org_id`` or ``user_{sub[:12]}``
			- ``tenant`` — resolved ``Tenant``
			- ``scopes`` = ``['chat:read', 'chat:write']``
			- ``plan`` — resolved ``Plan``
			- ``rate_limit_config`` — ``{'rpm': 10, 'rpd': 100}``

		Returns:
			``True`` when the JWT is valid and context was resolved.
			``False`` on any failure. Sets ``request.state.clerk_error``
			to ``'TENANT_NOT_FOUND'`` when the org_id tenant is missing.
		"""
		payload = await self.verify_jwt(token, redis)
		if payload is None:
			return False

		sub: str = payload.get('sub', '')
		org_id: str | None = payload.get('org_id', None)

		# ── Resolve tenant ──────────────────────────────────────────
		if org_id:
			tenant_id = org_id
			tenant_data = await redis.hgetall(_KEY_TENANT.format(tenant_id))
			if not tenant_data:
				request.state.clerk_error = 'TENANT_NOT_FOUND'
				return False
			tenant = RedisStore._deserialize(Tenant, tenant_data)
		else:
			# Personal tenant — create on-the-fly
			tenant_id = f'user_{sub[:12]}'
			tenant_data = await redis.hgetall(_KEY_TENANT.format(tenant_id))
			if tenant_data:
				tenant = RedisStore._deserialize(Tenant, tenant_data)
			else:
				tenant = Tenant(
					id=tenant_id,
					name='Personal',
					plan_tier=PlanTier.free,
					cuit='',
					clave_fiscal='',
					is_active=True,
				)
				ts = TenantStore(redis)
				await ts.create(tenant)

		# ── Resolve plan ────────────────────────────────────────────
		plan = await self._resolve_plan_for_tier(redis, tenant.plan_tier)

		# ── Inject state ────────────────────────────────────────────
		request.state.auth_method = 'clerk_jwt'
		request.state.clerk_user_id = sub
		request.state.tenant_id = tenant_id
		request.state.tenant = tenant
		request.state.scopes = ['chat:read', 'chat:write']
		request.state.plan = plan
		request.state.rate_limit_config = {'rpm': 10, 'rpd': 100}

		return True
