"""Active-profile invariant gate (shared across report-generation entry points).

Invariant enforced at the API boundary: NO report generation without an ACTIVE
profile belonging to the current tenant.

``validate_active_profile`` resolves the caller's tenant from
``request.state.tenant_id``, loads the ``profiles`` row, verifies ownership and
``status == 'active'``, and resolves the ORM ``user_id`` for the Clerk session
(``None`` when there is no session or the user row is missing). Returns a
:class:`ActiveProfileContext` used to stamp ``report_runs`` rows.

Used by ``report_runs.py`` (POST /v1/report-runs), ``chat.py``
(/v1/chat/message, /v1/chat/message/stream, /v1/chat/wizard) and ``report.py``
(POST /v1/report). Status codes are parameterizable because the entry points
use different conventions (chat: 400 missing; report-runs/report: 422 missing;
missing/foreign/inactive -> 404/409 everywhere).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agente_fiscal.db.models import Profile, User
from agente_fiscal.domain.models import ApiError, UnifiedResponse


def _exc(status_code: int, code: str, cause: str, remediation: str = '') -> HTTPException:
	"""Build a UnifiedResponse-wrapped HTTPException for the invariant errors."""
	return HTTPException(
		status_code=status_code,
		detail=UnifiedResponse(
			status='error',
			error=ApiError(code=code, cause=cause, remediation=remediation),
		).model_dump(),
	)


def profile_required_error(missing_code: int = 422) -> HTTPException:
	return _exc(
		missing_code,
		'PROFILE_REQUIRED',
		'Debés enviar profile_id: no se puede generar un reporte sin un perfil activo del tenant',
		'Creá un perfil primero (POST /v1/profiles) y enviá su profile_id en el request',
	)


def profile_not_found_error(not_found_code: int = 404) -> HTTPException:
	return _exc(
		not_found_code,
		'PROFILE_NOT_FOUND',
		'No existe un perfil activo con ese profile_id para tu tenant',
		'Verifica el profile_id e intenta de nuevo',
	)


def profile_inactive_error(inactive_code: int = 409) -> HTTPException:
	return _exc(
		inactive_code,
		'PROFILE_INACTIVE',
		'El perfil está inactivo — no se pueden generar reportes con él',
		'Cambiá el estado del perfil a "active" (PATCH /v1/profiles/{id})',
	)


@dataclass
class ActiveProfileContext:
	"""Resolved tenant + profile + user used to stamp a ``report_runs`` row."""

	tenant_id: uuid.UUID
	profile_id: uuid.UUID
	user_id: uuid.UUID | None


async def validate_active_profile(
	request: Request,
	profile_id: Optional[uuid.UUID],
	session: AsyncSession,
	*,
	missing_code: int = 422,
	not_found_code: int = 404,
	inactive_code: int = 409,
) -> ActiveProfileContext:
	"""Validate the active-profile invariant and resolve identity context.

	Raises 401 when the tenant can't be resolved, the entry-point status code
	(``missing_code``, default 422) when *profile_id* is absent, 404 when the
	profile is missing or belongs to another tenant, and 409 when it's inactive.
	"""
	tenant_id = getattr(request.state, 'tenant_id', None)
	if tenant_id is None:
		raise _exc(
			401,
			'UNAUTHENTICATED',
			'No se pudo resolver el tenant autenticado',
			'Autentícate con un Clerk JWT o API key válida',
		)
	try:
		tenant_uuid = uuid.UUID(str(tenant_id))
	except (TypeError, ValueError):
		raise _exc(
			401,
			'UNAUTHENTICATED',
			'El tenant autenticado no es un UUID válido',
			'Revisa la sesión / API key utilizada',
		)

	if profile_id is None:
		raise profile_required_error(missing_code)

	profile = await session.get(Profile, profile_id)
	if profile is None or profile.tenant_id != tenant_uuid:
		raise profile_not_found_error(not_found_code)
	if profile.status != 'active':
		raise profile_inactive_error(inactive_code)

	user_id: Optional[uuid.UUID] = None
	clerk_user_id = getattr(request.state, 'clerk_user_id', None)
	if clerk_user_id:
		user_id = await session.scalar(
			select(User.id).where(User.clerk_user_id == clerk_user_id).limit(1)
		)

	return ActiveProfileContext(
		tenant_id=tenant_uuid,
		profile_id=profile_id,
		user_id=user_id,
	)


__all__ = [
	'ActiveProfileContext',
	'profile_inactive_error',
	'profile_not_found_error',
	'profile_required_error',
	'validate_active_profile',
]