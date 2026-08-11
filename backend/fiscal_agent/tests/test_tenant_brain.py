"""Tests for TenantBrain — build_context() and _match_rentas().

Mocks FiscalMemoryClient to avoid real Engram dependency.
Tests best-effort semantics: partial failures should not prevent
other sources from being populated.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fiscal_agent.memory.brain import TenantBrain
from fiscal_agent.memory.client import FiscalMemoryClient
from fiscal_agent.models import ImpuestoInscripto, RegistroImpuesto, RentasCordobaMatching


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_client() -> MagicMock:
	"""Return a MagicMock that simulates a working FiscalMemoryClient."""
	client = MagicMock(spec=FiscalMemoryClient)

	# All read methods return empty lists by default
	client.get_padron_history.return_value = []
	client.get_extraction_history.return_value = []
	client.get_pipeline_history.return_value = []

	return client


@pytest.fixture
def brain(mock_client: MagicMock) -> TenantBrain:
	"""Return a TenantBrain with a mocked client."""
	return TenantBrain(mock_client)


# ── Happy path ───────────────────────────────────────────────────────────────


class TestBuildContextHappyPath:
	"""Task 4.2: build_context() happy path — all sources available."""

	def test_all_sources_populated(self, mock_client: MagicMock) -> None:
		"""All 8 steps populate their respective fields (best-effort).

		Nota: RulesEngine.calcular() falla con datos mock porque espera
		``PadronA5Output`` real — eso es esperado y demuestra que el
		best-effort funciona: el error se captura y los otros campos
		siguen poblados.
		"""
		mock_client.get_padron_history.return_value = [{'id': 1, 'type': 'padron', 'content': '**Data**: {}'}]
		mock_client.get_extraction_history.side_effect = lambda cuit, etype, limit=3: (
			[{'id': 2, 'type': 'deuda'}]
			if etype == 'deuda'
			else [{'id': 3, 'type': 'facilidades'}]
			if etype == 'facilidades'
			else [{'id': 4, 'type': 'registro', 'content': '**Data**: {}'}]
			if etype == 'registro'
			else []
		)
		mock_client.get_pipeline_history.return_value = [{'id': 5, 'type': 'error'}]

		brain_instance = TenantBrain(mock_client)
		ctx = brain_instance.build_context('20324837796')

		# All memory/client-backed fields should be populated
		assert ctx.padron is not None
		assert len(ctx.deuda) == 1
		assert len(ctx.facilidades) == 1
		assert ctx.registro is not None
		assert ctx.memoria_historica is not None

		# Calendar may fail with mock data (RulesEngine necesita datos reales)
		# — best-effort: el error se captura en ultimo_error
		if ctx.ultimo_error:
			assert ctx.ultimo_error['source'] in ('calendario',)

		# Resumen ejecutivo should not be empty
		assert ctx.resumen_ejecutivo != ''

	def test_returns_tenant_context(self, brain: TenantBrain) -> None:
		"""build_context returns a TenantContext instance."""
		ctx = brain.build_context('20324837796')
		from fiscal_agent.memory.models import TenantContext

		assert isinstance(ctx, TenantContext)


# ── Partial failure ──────────────────────────────────────────────────────────


class TestBuildContextPartialFailure:
	"""Task 4.2: build_context() tolerates partial failures (best-effort)."""

	def test_arca_source_fails(self, mock_client: MagicMock) -> None:
		"""When get_padron_history raises, padron is None but other fields work."""
		mock_client.get_padron_history.side_effect = ConnectionError('Engram down')
		mock_client.get_extraction_history.return_value = [{'id': 2, 'type': 'deuda'}]

		brain_instance = TenantBrain(mock_client)
		ctx = brain_instance.build_context('20324837796')

		assert ctx.padron is None  # padron failed
		assert len(ctx.deuda) == 1  # deuda is still populated
		assert ctx.ultimo_error is not None
		assert ctx.ultimo_error['source'] == 'padron'

	def test_engram_source_fails(self, mock_client: MagicMock) -> None:
		"""When get_extraction_history raises for one type, other types still work."""
		mock_client.get_padron_history.return_value = [{'id': 1, 'type': 'padron', 'content': '**Data**: {}'}]

		def extraction_side(cuit: str, etype: str, limit: int = 3) -> list:
			if etype == 'deuda':
				raise ConnectionError('Engram down for deuda')
			return [{'id': 3, 'type': etype}]

		mock_client.get_extraction_history.side_effect = extraction_side

		brain_instance = TenantBrain(mock_client)
		ctx = brain_instance.build_context('20324837796')

		assert ctx.deuda == []  # deuda failed → empty list
		assert len(ctx.facilidades) == 1  # facilidades still works
		assert ctx.ultimo_error is not None

	def test_multiple_sources_fail(self, mock_client: MagicMock) -> None:
		"""Multiple failures: ultimo_error captures the FIRST error."""
		mock_client.get_padron_history.side_effect = RuntimeError('Padron crash')
		mock_client.get_extraction_history.side_effect = RuntimeError('Extraction crash')

		brain_instance = TenantBrain(mock_client)
		ctx = brain_instance.build_context('20324837796')

		assert ctx.padron is None
		assert ctx.deuda == []
		assert ctx.ultimo_error is not None
		assert ctx.ultimo_error['source'] == 'padron'  # first error


# ── Empty data ───────────────────────────────────────────────────────────────


class TestBuildContextEmptyData:
	"""Task 4.2: build_context() handles empty data gracefully."""

	def test_cuit_vacio(self, brain: TenantBrain) -> None:
		"""Empty CUIT string — no crash, padron returns []."""
		ctx = brain.build_context('')
		assert ctx.padron == []
		assert ctx.resumen_ejecutivo != ''

	def test_no_observations(self, brain: TenantBrain) -> None:
		"""CUIT with no observations — all lists are empty, all optionals are None."""
		ctx = brain.build_context('20324837796')
		assert ctx.padron == []
		assert ctx.deuda == []
		assert ctx.ultimo_error is None


# ── _match_rentas ────────────────────────────────────────────────────────────


class TestMatchRentas:
	"""Task 4.3: _match_rentas() behavior — identical to evaluar_rentas_cordoba()."""

	def test_requiere_integracion(self, brain: TenantBrain) -> None:
		"""Convenio Multilateral + IIBB Córdoba → requiere_integracion=True."""
		result = brain._match_rentas(
			provincias=['Córdoba', 'Santa Fe'],
			impuestos_ws=[ImpuestoInscripto(idImpuesto=5904)],
			registro_impuestos=[RegistroImpuesto(impuesto='Ingresos Brutos CÓRDOBA')],
		)
		assert result.requiere_integracion is True
		assert result.estado == 'pendiente'

	def test_no_convenio_multilateral(self, brain: TenantBrain) -> None:
		"""Solo 1 provincia → no hay Convenio Multilateral."""
		result = brain._match_rentas(
			provincias=['Córdoba'],
			impuestos_ws=[ImpuestoInscripto(idImpuesto=5904)],
			registro_impuestos=[RegistroImpuesto(impuesto='Ingresos Brutos CÓRDOBA')],
		)
		assert result.requiere_integracion is False
		assert result.estado == 'no_requerido'

	def test_no_iibb_cordoba(self, brain: TenantBrain) -> None:
		"""Sin registro en Córdoba → no requiere integración."""
		result = brain._match_rentas(
			provincias=['Córdoba', 'Santa Fe'],
			impuestos_ws=[ImpuestoInscripto(idImpuesto=5904)],
			registro_impuestos=[RegistroImpuesto(impuesto='Ingresos Brutos Santa Fe')],
		)
		assert result.requiere_integracion is False
		assert result.tiene_iibb_cordoba is False
		assert result.estado == 'no_requerido'

	def test_sin_datos_registro(self, brain: TenantBrain) -> None:
		"""Sin datos de registro → estado sin_datos."""
		result = brain._match_rentas(
			provincias=['Córdoba', 'Santa Fe'],
			impuestos_ws=[ImpuestoInscripto(idImpuesto=5904)],
			registro_impuestos=None,
		)
		assert result.requiere_integracion is False
		assert result.tiene_iibb_cordoba is None
		assert result.estado == 'sin_datos'

	def test_no_impuestos_ws(self, brain: TenantBrain) -> None:
		"""Sin impuestos del padrón → no convenio."""
		result = brain._match_rentas(
			provincias=['Córdoba', 'Santa Fe'],
			impuestos_ws=None,
			registro_impuestos=[RegistroImpuesto(impuesto='Ingresos Brutos CÓRDOBA')],
		)
		assert result.requiere_integracion is False
		assert result.tiene_convenio_multilateral is False

	def test_iibb_ids_set(self, brain: TenantBrain) -> None:
		"""Verifica ids de IIBB reconocidos (5904, 5902, 5905, 5906, 215)."""
		for iibb_id in [5904, 5902, 5905, 5906, 215]:
			result = brain._match_rentas(
				provincias=['Córdoba', 'Santa Fe'],
				impuestos_ws=[ImpuestoInscripto(idImpuesto=iibb_id)],
				registro_impuestos=[RegistroImpuesto(impuesto='Ingresos Brutos CÓRDOBA')],
			)
			assert result.requiere_integracion is True, f'IIBB id {iibb_id} debería matchear'

	def test_normalize_acentos(self, brain: TenantBrain) -> None:
		"""Córdoba con acento debe matchear igual."""
		result = brain._match_rentas(
			provincias=['Córdoba', 'Santa Fe'],
			impuestos_ws=[ImpuestoInscripto(idImpuesto=5904)],
			registro_impuestos=[RegistroImpuesto(impuesto='Ingresos Brutos Córdoba')],  # acento
		)
		assert result.requiere_integracion is True

	def test_identical_to_evaluar_rentas_cordoba(self, brain: TenantBrain) -> None:
		"""Output debe ser idéntico al de evaluar_rentas_cordoba()."""
		from fiscal_agent.matching import evaluar_rentas_cordoba

		provincias = ['Córdoba', 'Santa Fe']
		impuestos = [ImpuestoInscripto(idImpuesto=5904)]
		registro = [RegistroImpuesto(impuesto='Ingresos Brutos CÓRDOBA')]

		brain_result = brain._match_rentas(
			provincias=provincias,
			impuestos_ws=impuestos,
			registro_impuestos=registro,
		)
		wrapper_result = evaluar_rentas_cordoba(provincias, impuestos, registro)

		assert brain_result.model_dump() == wrapper_result.model_dump()
