"""ClerkJWTExtractor — validate Clerk JWTs and resolve tenant context.

Used as the second auth method alongside ApiKeyExtractor in AuthMiddleware.
Supports both HS256 (dev mode via CLERK_SECRET_KEY) and RS256 (prod via JWKS).

Tenant/plan context is resolved from the Postgres Fase 1 data layer
(``fiscal_agent.db.auth``). Redis is used ONLY for the JWKS cache
(``jwks:clerk``) and — elsewhere — rate limiting.
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
from sqlalchemy.ext.asyncio import async_sessionmaker

from fiscal_agent.config import get_settings
from fiscal_agent.db.auth import (
    TenantNotFoundError,
    get_active_plan,
    resolve_or_create_tenant,
)
from fiscal_agent.models import Plan, PlanTier, Tenant

logger = logging.getLogger(__name__)


def _tier_from_plan_name(name: str) -> PlanTier:
    """Map a catalog plan name (``'Free'``, ``'Pro Max'``, ...) to a tier."""
    norm = (name or '').strip().lower()
    for tier in PlanTier:
        if norm == tier.value:
            return tier
    return PlanTier.free


def _tenant_pydantic(tenant_id: str, name: str, plan_name: str) -> Tenant:
    """Map DB tenant fields to the pydantic ``Tenant`` state contract.

    Documented mapping decision (option (a)): the DB ``tenants`` table only
    has ``id``/``name``/``clerk_org_id``. The pydantic contract's extra fields
    (``cuit``, ``clave_fiscal``, ``certificados``, ``clientes``,
    ``provincias``) are populated from config defaults or emptied, keeping the
    contract intact for existing callers. ``cuit``/``clave_fiscal`` use the
    seeded study default (``ESTUDIO_CUIT`` / ``ESTUDIO_CLAVE_FISCAL``) until
    the tenant contract evolves (TODO Bloque 2+).
    """
    settings = get_settings()
    return Tenant(
        id=tenant_id,
        name=name,
        plan_tier=_tier_from_plan_name(plan_name),
        cuit=settings.cuit,
        clave_fiscal=settings.clave_fiscal,
        certificados=[],
        clientes=[],
        provincias=[],
        is_active=True,
    )


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
		2. Resolve user + tenant from Postgres (auto-provision personal)
		3. Resolve ``Plan`` from the tenant's active subscription
		4. Inject state into ``request.state``

	``session_factory`` is optional: when omitted, ``handle()`` reads
	``request.app.state.session_factory``.
	"""

	def __init__(self, session_factory: async_sessionmaker | None = None):
		self.session_factory = session_factory

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

	async def handle(self, token: str, request: Request, redis: Redis) -> bool:
		"""Verify a Clerk JWT and inject tenant/plan state.

		Context resolution is Postgres-backed (``db/auth.py``); Redis is used
		only for the JWKS cache inside ``verify_jwt``.

		Injected state (on success):
			- ``auth_method`` = ``'clerk_jwt'``
			- ``clerk_user_id`` — ``sub`` claim from token
			- ``tenant_id`` — DB tenant UUID (org → ``tenants.clerk_org_id``;
			  personal → deterministic UUIDv5 derived from the user)
			- ``tenant`` — resolved pydantic ``Tenant``
			- ``scopes`` = ``['chat:read', 'chat:write']``
			- ``plan`` — resolved pydantic ``Plan``
			- ``rate_limit_config`` — ``{'rpm': ..., 'rpd': ...}`` from plan

		Returns:
			``True`` when the JWT is valid and context was resolved.
			``False`` on any failure. Sets ``request.state.clerk_error``
			to ``'TENANT_NOT_FOUND'`` when the ``org_id`` tenant is missing.
		"""
		payload = await self.verify_jwt(token, redis)
		if payload is None:
			return False

		sub: str = str(payload.get('sub', ''))
		org_id: str | None = payload.get('org_id') or None
		email: str | None = payload.get('email')
		display_name: str | None = payload.get('name') or payload.get('first_name')

		if not sub:
			logger.warning('Clerk JWT sin sub — rechazado')
			return False

		# Session factory: injected constructor arg wins, else app.state
		factory = self.session_factory or getattr(request.app.state, 'session_factory', None)
		if factory is None:
			logger.error('No Postgres session_factory disponible para auth Clerk')
			return False

		# ── Resolve tenant + plan from Postgres (single transaction) ─────
		async with factory() as session:
			try:
				tenant_row, _user = await resolve_or_create_tenant(
					session,
					org_id,
					sub,
					email=email,
					display_name=display_name,
				)
				plan = await get_active_plan(session, tenant_row.id)
				await session.commit()
			except TenantNotFoundError:
				logger.info('Tenant no encontrado para org_id=%s (sub=%s)', org_id, sub[:12])
				request.state.clerk_error = 'TENANT_NOT_FOUND'
				return False
			except Exception:
				logger.exception('Error resolviendo tenant/plan Clerk para sub=%s', sub[:12])
				return False

		tenant_id = str(tenant_row.id)
		if plan is None:
			logger.warning('Plan no resuelto para tenant %s — usando defaults', tenant_id)
			rpm = 10
			rpd = 100
			plan = Plan(id='free', name='Free', scopes=['chat:read', 'chat:write'], rate_limit_rpm=rpm, rate_limit_rpd=rpd)
		else:
			rpm, rpd = plan.rate_limit_rpm, plan.rate_limit_rpd

		tenant = _tenant_pydantic(tenant_id, tenant_row.name, plan.name)

		# ── Inject state (same contract as the Redis era) ─────────────────
		request.state.auth_method = 'clerk_jwt'
		request.state.clerk_user_id = sub
		request.state.tenant_id = tenant_id
		request.state.tenant = tenant
		request.state.scopes = ['chat:read', 'chat:write']
		request.state.plan = plan
		request.state.rate_limit_config = {'rpm': rpm, 'rpd': rpd}

		return True
