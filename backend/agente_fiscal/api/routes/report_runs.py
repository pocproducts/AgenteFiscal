"""Lightweight report-run lifecycle — queue a run now, execute in Fase 3.

This module does NOT run the heavy pipeline. It only persists a ``report_runs``
row in Postgres as ``queued`` and returns its ID, so callers (the Next.js BFF
from Bloque 2) can kick off async work and track it by ID later.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agente_fiscal.api.deps import get_db_session
from agente_fiscal.db.models import ReportRun
from agente_fiscal.domain.approvals import validate_actions
from agente_fiscal.domain.models import ApiError, UnifiedResponse

router = APIRouter()

_CUIT_RE = re.compile(r'^\d{11}$')

#: Roles allowed to approve/reject a ``waiting_approval`` run.
_ADMIN_ROLES = frozenset({'owner', 'admin'})


class ApproveRequest(BaseModel):
	"""Payload to approve a ``waiting_approval`` run's pending actions."""

	actions: list[str] | None = Field(
		default=None,
		description='Acciones a aprobar. Omitido: aprueba TODAS las pendientes.',
		examples=[['send_email']],
	)


class RejectRequest(BaseModel):
	"""Payload to reject a ``waiting_approval`` run."""

	reason: str | None = Field(
		default=None,
		description='Motivo del rechazo (queda como audit trail)',
		examples=['El cliente pidió no enviar aún'],
	)


def _require_tenant_uuid(request: Request) -> uuid.UUID:
	"""Resolve ``request.state.tenant_id`` as a UUID, or raise 401."""
	tenant_id = getattr(request.state, 'tenant_id', None)
	if tenant_id is None:
		raise HTTPException(
			status_code=401,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(
					code='UNAUTHENTICATED',
					cause='No se pudo resolver el tenant autenticado',
					remediation='Autentícate con un Clerk JWT o API key válida',
				),
			).model_dump(),
		)
	try:
		return uuid.UUID(str(tenant_id))
	except (ValueError, TypeError):
		raise HTTPException(
			status_code=401,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(
					code='UNAUTHENTICATED',
					cause='El tenant autenticado no es un UUID válido',
					remediation='Revisa la sesión / API key utilizada',
				),
			).model_dump(),
		)


def _require_admin(request: Request) -> None:
	"""Raise 403 unless the caller holds ``owner``/``admin`` on the tenant.

	``request.state.user_role`` is populated by ``ClerkJWTExtractor`` for
	Clerk sessions. API-key auth never sets it, so machine keys can NEVER
	approve — approval is reserved for humans.
	"""
	role = getattr(request.state, 'user_role', 'member')
	if role not in _ADMIN_ROLES:
		raise HTTPException(
			status_code=403,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(
					code='FORBIDDEN',
					cause='Se requiere rol owner/admin del tenant para aprobar o rechazar',
					remediation='Usa una sesión de un administrador del tenant',
				),
			).model_dump(),
		)


def _not_found() -> HTTPException:
	return HTTPException(
		status_code=404,
		detail=UnifiedResponse(
			status='error',
			error=ApiError(
				code='REPORT_RUN_NOT_FOUND',
				cause='No existe una corrida de reporte con ese ID para tu tenant',
				remediation='Verifica el report_run_id e intenta de nuevo',
			),
		).model_dump(),
	)


def _wrong_status() -> HTTPException:
	return HTTPException(
		status_code=409,
		detail=UnifiedResponse(
			status='error',
			error=ApiError(
				code='WRONG_STATUS',
				cause='La corrida no está esperando aprobación',
				remediation='Solo se pueden aprobar/rechazar corridas en estado waiting_approval',
			),
		).model_dump(),
	)


def _invalid_approval(cause: str) -> HTTPException:
	return HTTPException(
		status_code=422,
		detail=UnifiedResponse(
			status='error',
			error=ApiError(
				code='INVALID_APPROVAL',
				cause=cause,
				remediation='Aprueba solo acciones del catálogo que estén pendientes',
			),
		).model_dump(),
	)


class CreateReportRunRequest(BaseModel):
	"""Payload to enqueue a fiscal report run (execution happens later)."""

	cuit: str = Field(
		description='CUIT del contribuyente sin guiones (11 dígitos)',
		examples=['20301234561'],
	)
	client_id: uuid.UUID | None = Field(
		default=None,
		description='Opcional: ID del cliente asociado al reporte',
	)
	period: dict[str, Any] | None = Field(
		default=None,
		description='Período fiscal flexible, p.ej. {"mes": 6, "anio": 2026}',
		examples=[{'mes': 6, 'anio': 2026}],
	)
	flags: dict[str, Any] | None = Field(
		default=None,
		description='Flags de ejecución flexibles, p.ej. {"with_deuda": true}',
		examples=[{'with_deuda': True}],
	)


@router.post(
	'/v1/report-runs',
	response_model=UnifiedResponse[dict],
	summary='Encolar una corrida de reporte fiscal (no ejecuta pipeline)',
)
async def create_report_run(
	request: Request,
	body: CreateReportRunRequest,
	session: AsyncSession = Depends(get_db_session),
) -> UnifiedResponse[dict]:
	"""Create a ``queued`` ``report_runs`` row and return its ID.

	The heavy pipeline is intentionally NOT invoked here; a separate runner
	(Fase 3) will pick the row up, mark it ``running``, and later ``done`` /
	``failed``. This endpoint only persists and returns the ID.
	"""
	tenant_id = getattr(request.state, 'tenant_id', None)
	if tenant_id is None:
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='UNAUTHENTICATED',
				cause='No se pudo resolver el tenant autenticado',
				remediation='Autentícate con un Clerk JWT o API key válida',
			),
		)

	if not _CUIT_RE.fullmatch(body.cuit):
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='INVALID_CUIT',
				cause='El CUIT debe ser exactamente 11 dígitos, sin guiones',
				remediation='Revisa el CUIT e intenta de nuevo',
			),
		)

	try:
		tenant_uuid = uuid.UUID(str(tenant_id))
	except (ValueError, TypeError):
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='UNAUTHENTICATED',
				cause='El tenant autenticado no es un UUID válido',
				remediation='Revisa la sesión / API key utilizada',
			),
		)

	# Stash optional config into the JSONB steps column.
	steps: dict[str, Any] = {}
	if body.period is not None:
		steps['period'] = body.period
	if body.flags is not None:
		steps['flags'] = body.flags

	run = ReportRun(
		tenant_id=tenant_uuid,
		client_id=body.client_id,
		cuit=body.cuit,
		status='queued',
		steps=steps,
	)

	try:
		session.add(run)
		await session.commit()
		await session.refresh(run)
	except Exception as exc:
		await session.rollback()
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='REPORT_RUN_CREATE_FAILED',
				cause=str(exc),
				remediation='Reintenta en unos instantes',
			),
		)

	return UnifiedResponse(
		status='success',
		result={
			'report_run_id': str(run.id),
			'status': run.status,
		},
	)


@router.get(
	'/v1/report-runs/{report_run_id}',
	response_model=UnifiedResponse[dict],
	summary='Estado de una corrida de reporte (para polling desde el frontend)',
)
async def get_report_run(
	report_run_id: uuid.UUID,
	request: Request,
	session: AsyncSession = Depends(get_db_session),
) -> UnifiedResponse[dict]:
	"""Return the current state of a ``report_runs`` row, scoped to the tenant.

	The worker (Fase 3) leaves ``status``, ``steps['progress']``,
	``result_summary`` and ``error`` on the row as it advances; the frontend
	polls this endpoint until ``status`` reaches ``done``/``failed``.
	"""
	tenant_id = getattr(request.state, 'tenant_id', None)
	if tenant_id is None:
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='UNAUTHENTICATED',
				cause='No se pudo resolver el tenant autenticado',
				remediation='Autentícate con un Clerk JWT o API key válida',
			),
		)

	try:
		tenant_uuid = uuid.UUID(str(tenant_id))
	except (ValueError, TypeError):
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='UNAUTHENTICATED',
				cause='El tenant autenticado no es un UUID válido',
				remediation='Revisa la sesión / API key utilizada',
			),
		)

	run = await session.get(ReportRun, report_run_id)

	# Missing rows and other tenants' runs share the same 404-ish error so we
	# don't leak whether a given report_run_id exists.
	if run is None or run.tenant_id != tenant_uuid:
		return UnifiedResponse(
			status='error',
			error=ApiError(
				code='REPORT_RUN_NOT_FOUND',
				cause='No existe una corrida de reporte con ese ID para tu tenant',
				remediation='Verifica el report_run_id e intenta de nuevo',
			),
		)

	return UnifiedResponse(
		status='success',
		result={
			'report_run_id': str(run.id),
			'status': run.status,
			'cuit': run.cuit,
			'started_at': run.started_at.isoformat() if run.started_at else None,
			'finished_at': run.finished_at.isoformat() if run.finished_at else None,
			'steps': run.steps,
			'result_summary': run.result_summary,
			'error': run.error,
			'pending_actions': run.pending_actions,
			'approved_by': run.approved_by,
			'approved_at': run.approved_at.isoformat() if run.approved_at else None,
			'rejection_reason': run.rejection_reason,
		},
	)


@router.post(
	'/v1/report-runs/{report_run_id}/approve',
	response_model=UnifiedResponse[dict],
	summary='Aprobar una corrida en espera de aprobación y reencolarla (ejecuta side effects)',
)
async def approve_report_run(
	report_run_id: uuid.UUID,
	request: Request,
	body: ApproveRequest,
	session: AsyncSession = Depends(get_db_session),
) -> UnifiedResponse[dict]:
	"""Approve a ``waiting_approval`` run so the worker resumes it.

	- Only ``owner``/``admin`` members of the run's tenant may approve (403).
	- Only runs in ``waiting_approval`` may be approved (409).
	- ``actions`` omitted → approve ALL pending actions; present → must be a
	  subset of the pending ones and from the known catalog (422 otherwise).
	- On success the run returns to ``queued`` with ``steps['proposal_done']``
	  and ``steps['approved_actions']`` so the worker executes ONLY the
	  approved side effects (proposal phase is skipped).
	"""
	tenant_uuid = _require_tenant_uuid(request)
	run = await session.get(ReportRun, report_run_id)
	if run is None or run.tenant_id != tenant_uuid:
		raise _not_found()
	_require_admin(request)
	if run.status != 'waiting_approval':
		raise _wrong_status()

	pending = list(run.pending_actions or [])
	approved: list[str] = list(pending) if body.actions is None else list(body.actions)
	if body.actions is not None:
		try:
			validate_actions(approved)
		except ValueError as exc:
			raise _invalid_approval(str(exc))
		extra = [a for a in approved if a not in pending]
		if extra:
			raise _invalid_approval(
				f'La corrida no tiene pendientes estas acciones: {", ".join(sorted(set(extra)))}'
			)

	steps = dict(run.steps or {})
	steps['approved_actions'] = approved
	steps['proposal_done'] = True
	run.steps = steps
	run.status = 'queued'
	run.approved_by = getattr(request.state, 'clerk_user_id', None) or 'unknown'
	run.approved_at = datetime.now(timezone.utc)

	try:
		await session.commit()
		await session.refresh(run)
	except Exception as exc:
		await session.rollback()
		raise HTTPException(
			status_code=500,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(
					code='APPROVE_FAILED',
					cause=str(exc),
					remediation='Reintenta en unos instantes',
				),
			).model_dump(),
		)

	return UnifiedResponse(
		status='success',
		result={
			'report_run_id': str(run.id),
			'status': run.status,
			'approved_actions': approved,
		},
	)


@router.post(
	'/v1/report-runs/{report_run_id}/reject',
	response_model=UnifiedResponse[dict],
	summary='Rechazar una corrida en espera de aprobación (termina como failed)',
)
async def reject_report_run(
	report_run_id: uuid.UUID,
	request: Request,
	body: RejectRequest,
	session: AsyncSession = Depends(get_db_session),
) -> UnifiedResponse[dict]:
	"""Reject a ``waiting_approval`` run without executing any side effect.

	Marks the run ``failed`` with error code ``APPROVAL_REJECTED`` and keeps the
	reason in ``rejection_reason``. ``approved_by``/``approved_at`` stay NULL —
	nothing was approved. Same tenant-scoping (404), admin-gate (403) and
	status gate (409) as approve.
	"""
	tenant_uuid = _require_tenant_uuid(request)
	run = await session.get(ReportRun, report_run_id)
	if run is None or run.tenant_id != tenant_uuid:
		raise _not_found()
	_require_admin(request)
	if run.status != 'waiting_approval':
		raise _wrong_status()

	cause = (body.reason or '').strip() or 'La corrida fue rechazada por un administrador'
	run.status = 'failed'
	run.rejection_reason = body.reason
	run.error = {'code': 'APPROVAL_REJECTED', 'cause': cause}

	try:
		await session.commit()
		await session.refresh(run)
	except Exception as exc:
		await session.rollback()
		raise HTTPException(
			status_code=500,
			detail=UnifiedResponse(
				status='error',
				error=ApiError(
					code='REJECT_FAILED',
					cause=str(exc),
					remediation='Reintenta en unos instantes',
				),
			).model_dump(),
		)

	return UnifiedResponse(
		status='success',
		result={
			'report_run_id': str(run.id),
			'status': run.status,
			'rejection_reason': run.rejection_reason,
		},
	)

