"""Lightweight report-run lifecycle — queue a run now, execute in Fase 3.

This module does NOT run the heavy pipeline. It only persists a ``report_runs``
row in Postgres as ``queued`` and returns its ID, so callers (the Next.js BFF
from Bloque 2) can kick off async work and track it by ID later.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agente_fiscal.api.deps import get_db_session
from agente_fiscal.db.models import ReportRun
from agente_fiscal.domain.models import ApiError, UnifiedResponse

router = APIRouter()

_CUIT_RE = re.compile(r'^\d{11}$')


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
		},
	)

