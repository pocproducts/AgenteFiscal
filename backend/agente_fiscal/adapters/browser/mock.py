"""MockBrowser — deterministic test/demo browser provider.

Implements the same ``BrowserPort`` contract as ComposioBrowser but returns
fixed ``DeudaOutput`` fixtures instead of driving a real Composio cloud
session (which currently returns HTTP 403 from the provider side). This makes
the provider plug-in mechanism verifiable fully offline.

TEST/DEV ONLY — never use in production: it does NOT touch ARCA and returns
fake data.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Callable, Optional

from agente_fiscal.domain.models import (
	ClientConfig,
	DeudaDetail,
	DeudaOutput,
	FacilidadPlan,
	RegistroIIBBJurisdiccion,
	RegistroOutput,
	VencimientoDeuda,
)

logger = logging.getLogger(__name__)

MOCK_LIVE_URL = 'https://mock.live.example/session'
MOCK_FALLBACK_CUIT = '00000000000'


def _generic_deuda(cuit: str) -> DeudaOutput:
	"""Generic deuda fixture (also backs the default VencimientosDeudasTask)."""
	return DeudaOutput(
		cuit=cuit,
		extraido_el=datetime.utcnow(),
		deuda_actual=12345.6,
		vencimientos=[
			VencimientoDeuda(
				impuesto='IVA',
				concepto='IVA Mensual',
				periodo=202608,
				fecha_vencimiento=date(2026, 8, 20),
			)
		],
		deudas=[
			DeudaDetail(
				impuesto='Ganancias',
				concepto='Anticipo',
				saldo=2500.0,
				vencimiento=date(2026, 9, 15),
			)
		],
		live_url=MOCK_LIVE_URL,
		error=None,
	)


def _facilidades(cuit: str) -> DeudaOutput:
	"""Plan de pagos (Mis Facilidades) fixture."""
	return DeudaOutput(
		cuit=cuit,
		extraido_el=datetime.utcnow(),
		facilidades=[
			FacilidadPlan(
				plan='Plan 1',
				nro_plan='12345',
				estado='ACTIVO',
				cantidad_cuotas=6,
				cuotas_pagas=2,
				cuotas_impagas=4,
				saldo=1500.0,
			)
		],
		live_url=MOCK_LIVE_URL,
		error=None,
	)


def _registro(cuit: str) -> DeudaOutput:
	"""Registro tributario (RUT) fixture."""
	return DeudaOutput(
		cuit=cuit,
		extraido_el=datetime.utcnow(),
		registro=RegistroOutput(
			jurisdiccion='CÓRDOBA',
			domicilios=[],
			actividades=[],
			impuestos=[],
			iibb_jurisdicciones=[
				RegistroIIBBJurisdiccion(
					provincia='CÓRDOBA',
					inscripcion='901-123456-1',
					estado='ACTIVO',
				)
			],
		),
		live_url=MOCK_LIVE_URL,
		error=None,
	)


def _iibb(cuit: str) -> DeudaOutput:
	"""IIBB jurisdicciones (RUT detallado) fixture."""
	return DeudaOutput(
		cuit=cuit,
		extraido_el=datetime.utcnow(),
		registro=RegistroOutput(
			iibb_jurisdicciones=[
				RegistroIIBBJurisdiccion(
					provincia='CÓRDOBA',
					inscripcion='901-123456-1',
					estado='ACTIVO',
				)
			]
		),
		live_url=MOCK_LIVE_URL,
		error=None,
	)


#: BrowserTask.name → fixture builder. Anything unseen falls back to deuda.
_FIXTURES: dict[str, Callable[[str], DeudaOutput]] = {
	'full': _generic_deuda,  # VencimientosDeudasTask
	'facilidades': _facilidades,
	'registro': _registro,
	'iibb': _iibb,
}


def _fixture_for(cuit: str, task_names: list[str]) -> DeudaOutput:
	"""Build the fixture for the first recognizable task, else the generic deuda."""
	for name in task_names:
		builder = _FIXTURES.get(name)
		if builder is not None:
			return builder(cuit)
	return _generic_deuda(cuit)


class MockBrowser:
	"""Deterministic browser provider for local testing/demos.

	Same surface as ComposioBrowser (``run_single``/``run_all``/``close``)
	but returns fixed fixtures keyed by task type. Never raises.
	"""

	def run_single(
		self,
		cliente: Optional[ClientConfig] = None,
		tasks: Optional[list[object]] = None,
		echo_func: Optional[Callable[[str], None]] = None,
		on_live_url: Optional[Callable[[str], None]] = None,
		on_step: Optional[Callable[[int, str, str, str], None]] = None,
		on_task_metrics: Optional[Callable[[dict], None]] = None,
	) -> DeudaOutput:
		"""Return a deterministic fixture for the client, never reaching the cloud.

		``on_task_metrics`` se acepta y se ignora (AST-5): el dispatch lo pasa
		siempre; MockBrowser no tiene telemetría real (la fila ``agent_sessions``
		queda con session_id NULL — ADR-7), solo evita el TypeError.
		"""
		cuit = cliente.cuit if cliente is not None else MOCK_FALLBACK_CUIT
		task_names = [t.name for t in (tasks or []) if getattr(t, 'name', '')]
		if echo_func:
			echo_func(f'  🔍 MockBrowser: {len(task_names) or 1} task(s) deterministas (sin cloud) ...')
		if on_live_url:
			on_live_url(MOCK_LIVE_URL)
		if on_step:
			on_step(1, 'Mock paso 1', MOCK_LIVE_URL, 'running')
			on_step(1, '', '', 'finished')
		return _fixture_for(cuit, task_names)

	async def run_all(self, clientes: list[ClientConfig]) -> list[DeudaOutput]:
		"""Process each client in order, one fixture per client."""
		return [self.run_single(cliente) for cliente in clientes]

	async def close(self) -> None:
		"""Nothing to release — mock provider holds no cloud resources."""
		logger.info('MockBrowser closed')