"""Tests for memory models — MemoryObservation, MemoryQueryRequest, MemoryObserveRequest, TenantContext."""

from __future__ import annotations

from datetime import datetime

import pydantic
import pytest

from fiscal_agent.memory.models import (
	MemoryObservation,
	MemoryObserveRequest,
	MemoryQueryRequest,
	MemoryQueryResponse,
	TenantContext,
)


class TestMemoryObservation:
	"""Task 4.1: MemoryObservation field defaults and construction."""

	def test_minimal_construction(self) -> None:
		"""Can create with only required fields."""
		obs = MemoryObservation(cuit='20324837796', title='Test', type='padron', content='some content')
		assert obs.cuit == '20324837796'
		assert obs.title == 'Test'
		assert obs.type == 'padron'
		assert obs.content == 'some content'
		assert obs.id is None
		assert obs.created_at is None

	def test_with_all_fields(self) -> None:
		"""All fields populated."""
		now = datetime.now()
		obs = MemoryObservation(
			id=42,
			cuit='20324837796',
			title='Padrón A5',
			type='padron',
			content='**Status**: success',
			created_at=now,
		)
		assert obs.id == 42
		assert obs.created_at == now


class TestMemoryQueryRequest:
	"""Task 4.1: MemoryQueryRequest validation."""

	def test_default_limit(self) -> None:
		"""Default limit is 10."""
		req = MemoryQueryRequest(cuit='20324837796')
		assert req.limit == 10
		assert req.obs_type is None

	def test_with_obs_type(self) -> None:
		"""Optional obs_type is set."""
		req = MemoryQueryRequest(cuit='20324837796', obs_type='padron')
		assert req.obs_type == 'padron'

	def test_limit_ge_1(self) -> None:
		"""Limit must be >= 1."""
		with pytest.raises(pydantic.ValidationError):
			MemoryQueryRequest(cuit='20324837796', limit=0)

	def test_limit_le_100(self) -> None:
		"""Limit must be <= 100."""
		with pytest.raises(pydantic.ValidationError):
			MemoryQueryRequest(cuit='20324837796', limit=101)


class TestMemoryObserveRequest:
	"""Task 4.1: MemoryObserveRequest validation — content max 10 KB, CUIT min_length."""

	def test_minimal_valid(self) -> None:
		"""Valid request with minimum fields."""
		req = MemoryObserveRequest(cuit='20324837796', title='Test', content='some content')
		assert req.cuit == '20324837796'
		assert req.type == 'generic'  # default

	def test_cuit_min_length(self) -> None:
		"""CUIT must be exactly 11 chars."""
		with pytest.raises(pydantic.ValidationError):
			MemoryObserveRequest(cuit='2032483779', title='Test', content='x')

	def test_cuit_max_length(self) -> None:
		"""CUIT must be exactly 11 chars (not more)."""
		with pytest.raises(pydantic.ValidationError):
			MemoryObserveRequest(cuit='203248377961', title='Test', content='x')

	def test_title_min_length(self) -> None:
		"""Title must not be empty."""
		with pytest.raises(pydantic.ValidationError):
			MemoryObserveRequest(cuit='20324837796', title='', content='x')

	def test_content_max_10kb(self) -> None:
		"""Content must not exceed 10_240 bytes."""
		with pytest.raises(pydantic.ValidationError):
			MemoryObserveRequest(cuit='20324837796', title='Test', content='x' * 10_241)

	def test_content_10kb_boundary(self) -> None:
		"""Content at exactly 10_240 bytes is valid."""
		req = MemoryObserveRequest(cuit='20324837796', title='Test', content='x' * 10_240)
		assert len(req.content) == 10_240

	def test_type_default(self) -> None:
		"""Default type is 'generic'."""
		req = MemoryObserveRequest(cuit='20324837796', title='Test', content='x')
		assert req.type == 'generic'

	def test_type_explicit(self) -> None:
		"""Type can be explicitly set."""
		req = MemoryObserveRequest(cuit='20324837796', title='Test', type='padron', content='x')
		assert req.type == 'padron'


class TestMemoryQueryResponse:
	"""Task 4.1: MemoryQueryResponse defaults."""

	def test_defaults(self) -> None:
		"""All fields have sensible defaults."""
		resp = MemoryQueryResponse()
		assert resp.observations == []
		assert resp.total == 0
		assert resp.cuit == ''

	def test_with_data(self) -> None:
		"""Can construct with data."""
		resp = MemoryQueryResponse(
			observations=[{'id': 1, 'type': 'padron'}],
			total=1,
			cuit='20324837796',
		)
		assert len(resp.observations) == 1
		assert resp.total == 1


class TestTenantContext:
	"""Task 4.1: TenantContext defaults — all optional fields are None/empty."""

	def test_defaults(self) -> None:
		"""All fields default to None/empty."""
		ctx = TenantContext()
		assert ctx.padron is None
		assert ctx.deuda == []
		assert ctx.facilidades == []
		assert ctx.registro is None
		assert ctx.calendario is None
		assert ctx.rentas_matching is None
		assert ctx.memoria_historica == []
		assert ctx.ultimo_error is None
		assert ctx.resumen_ejecutivo == ''

	def test_with_partial_data(self) -> None:
		"""Partial data is representable."""
		ctx = TenantContext(
			deuda=[{'impuesto': 'IVA'}],
			resumen_ejecutivo='Resumen activo',
		)
		assert ctx.deuda == [{'impuesto': 'IVA'}]
		assert ctx.padron is None  # not set
		assert ctx.resumen_ejecutivo == 'Resumen activo'

	def test_with_all_data(self) -> None:
		"""All fields can be populated."""
		ctx = TenantContext(
			padron={'nombre': 'Test'},
			deuda=[{'impuesto': 'IVA'}],
			facilidades=[{'plan': 'facilidad'}],
			registro={'impuestos': []},
			calendario={'vencimientos': []},
			rentas_matching={'requiere_integracion': False},
			memoria_historica=[{'evento': 'padron_ok'}],
			ultimo_error={'source': 'deuda', 'error': 'timeout'},
			resumen_ejecutivo='Todo OK',
		)
		assert ctx.padron == {'nombre': 'Test'}
		assert ctx.ultimo_error == {'source': 'deuda', 'error': 'timeout'}
