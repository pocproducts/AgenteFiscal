"""Tests del registro ToolSpec (domain/tool_spec.py).

Cubre el contrato del design D2/D3: 6 tools registradas, biyección
INTENT_TO_KEY ↔ TOOL_SPECS, keywords disjuntas y formatters resolubles.
"""

from __future__ import annotations

import re

import pytest

from agente_fiscal.domain.intent_router import Intent
from agente_fiscal.domain.tool_spec import INTENT_TO_KEY, TOOL_SPECS, ToolSpec


TOOL_KEYS = [
	'sistemaregistral',
	'deudavencimientos',
	'misfacilidades',
	'rentascordoba',
	'reportecompleto',
	'consultaarca',
	'calendariovencimientosarca',
]

FORMATTER_NAMES = {
	'format_registro_response',
	'format_deuda_response',
	'format_facilidades_response',
	'format_rentas_response',
	'format_reporte_response',
	'format_consultaarca_response',
	'format_calendario_response',
}

TOOL_INTENTS = {
	Intent.SISTEMA_REGISTRAL,
	Intent.DEUDA_VENCIMIENTOS,
	Intent.MIS_FACILIDADES,
	Intent.RENTAS_CORDOBA,
	Intent.REPORTE_COMPLETO,
	Intent.CONSULTA_ARCA,
	Intent.CALENDARIO_VENCIMIENTOS_ARCA,
}


def test_six_tools_registered():
	assert set(TOOL_SPECS) == set(TOOL_KEYS)


@pytest.mark.parametrize('key', TOOL_KEYS)
def test_each_spec_is_well_formed(key):
	spec = TOOL_SPECS[key]
	assert isinstance(spec, ToolSpec)
	assert spec.tool_key == key
	assert spec.intent in TOOL_INTENTS
	assert isinstance(spec.keywords, tuple) and spec.keywords
	assert isinstance(spec.task_flags, dict)
	# Formatter name: formato format_<tool>_response (resolución en API layer).
	assert re.fullmatch(r'format_[a-z_]+_response', spec.formatter_name)
	assert isinstance(spec.needs_browser, bool)
	assert spec.tool_name  # PascalCase display (BFF)


def test_specs_are_frozen():
	from dataclasses import FrozenInstanceError

	spec = TOOL_SPECS['misfacilidades']
	with pytest.raises(FrozenInstanceError):
		# Mutar un atributo de un dataclass frozen debe fallar.
		spec.tool_key = 'otro'
	assert spec.tool_key == 'misfacilidades'


def test_intent_to_key_bijection():
	# 1:1 entre TOOL_SPECS e INTENT_TO_KEY (completo en ambas direcciones).
	assert set(INTENT_TO_KEY) == TOOL_INTENTS
	assert set(INTENT_TO_KEY.values()) == set(TOOL_SPECS)
	for key, spec in TOOL_SPECS.items():
		assert INTENT_TO_KEY[spec.intent] == key
		# Valor inverso: todo intent del mapa resuelve a su spec.
		assert TOOL_SPECS[INTENT_TO_KEY[spec.intent]] is spec


@pytest.mark.parametrize(
	('key', 'expected_flags'),
	[
		('sistemaregistral', {'with_registro': True}),
		('deudavencimientos', {'with_deuda': True}),
		('misfacilidades', {'with_facilidades': True}),
		('rentascordoba', {'with_iibb': True, 'provincia': 'CORDOBA'}),
		('reportecompleto', {'with_deuda': True, 'with_facilidades': True, 'with_registro': True, 'with_iibb': True}),
		('consultaarca', {}),
		('calendariovencimientosarca', {}),
	],
)
def test_task_flags_per_tool(key, expected_flags):
	assert TOOL_SPECS[key].task_flags == expected_flags


@pytest.mark.parametrize(
	('key', 'needs_browser'),
	[
		('sistemaregistral', True),
		('deudavencimientos', True),
		('misfacilidades', True),
		('rentascordoba', True),
		('reportecompleto', True),
		('consultaarca', False),
		('calendariovencimientosarca', False),
	],
)
def test_needs_browser_flag(key, needs_browser):
	assert TOOL_SPECS[key].needs_browser is needs_browser


@pytest.mark.parametrize(
	('key', 'is_pipeline'),
	[
		('reportecompleto', True),
		('sistemaregistral', False),
		('deudavencimientos', False),
		('misfacilidades', False),
		('rentascordoba', False),
		('consultaarca', False),
		('calendariovencimientosarca', False),
	],
)
def test_is_pipeline_flag(key, is_pipeline):
	assert TOOL_SPECS[key].is_pipeline is is_pipeline


def test_keyword_sets_are_disjoint():
	"""Las keyword sets de cada tool deben ser disjuntas entre sí."""
	keyword_sets = [set(spec.keywords) for spec in TOOL_SPECS.values()]
	for i, set_a in enumerate(keyword_sets):
		for j, set_b in enumerate(keyword_sets):
			if i < j:
				assert not (set_a & set_b), f'keywords solapadas entre tools {i} y {j}'


def test_formatter_names_are_known():
	"""Cada formatter_name del registro pertenece al set de formatters del dispatch."""
	names = {spec.formatter_name for spec in TOOL_SPECS.values()}
	assert names == FORMATTER_NAMES
	assert len(names) == 7  # un formatter por tool, sin duplicados