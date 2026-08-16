"""Registro declarativo de tools de browser (ToolSpec).

Fuente única del dispatch declarativo para las 6 tools fiscales de browser
(4 Phase-1 con ComposioBrowser + 2 Phase-2 deterministas por motor):

- ``ToolSpec``: dataclass frozen con la identidad, keywords, flags de tarea,
  formatter y si requiere (o no) sesión de browser viva.
- ``TOOL_SPECS``: mapa ``tool_key → ToolSpec`` (6 filas).
- ``INTENT_TO_KEY``: biyección ``Intent → tool_key`` (solo tool intents).

Los consumidores son el intent router, el dispatch de ``api/routes/chat.py``
y la BFF (que deriva toolName/windowMs en ``frontend/lib/agent-window.ts``;
el backend NO lleva ``window_ms`` — ver design D3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agente_fiscal.domain.intent_router import Intent


@dataclass(frozen=True)
class ToolSpec:
	"""Especificación declarativa de una tool fiscal de browser.

	Attributes:
		tool_key: Identificador de la tool (slash-command, lowercase).
		intent: Intent del router asociado a la tool.
		keywords: Tupla de keywords (substring sobre el mensaje lowercase)
			que disparan la tool en el intent router (mismas que el router).
		task_flags: Flags para ``build_browser_tasks(**task_flags)``; vacío
			``{}`` para las tools deterministas (sin browser).
		formatter_name: Nombre del formatter ``format_<tool>_response``
			resoluble en el dispatch (API layer).
		needs_browser: ``True`` → sesión Composio viva (live_url/agent_step);
			``False`` → motor determinista (padrón A5 / rules_engine).
		tool_name: Nombre display PascalCase (usado por la BFF).
	"""

	tool_key: str
	intent: Intent
	keywords: tuple[str, ...]
	task_flags: dict[str, Any] = field(default_factory=dict)
	formatter_name: str = ''
	needs_browser: bool = True
	tool_name: str = ''


TOOL_SPECS: dict[str, ToolSpec] = {
	'sistemaregistral': ToolSpec(
		tool_key='sistemaregistral',
		intent=Intent.SISTEMA_REGISTRAL,
		keywords=('sistemaregistral', 'sistema registral', 'registro registral'),
		task_flags={'with_registro': True},
		formatter_name='format_registro_response',
		needs_browser=True,
		tool_name='SistemaRegistral',
	),
	'deudavencimientos': ToolSpec(
		tool_key='deudavencimientos',
		intent=Intent.DEUDA_VENCIMIENTOS,
		keywords=('deudavencimientos', 'deuda y vencimientos', 'deuda'),
		task_flags={'with_deuda': True},
		formatter_name='format_deuda_response',
		needs_browser=True,
		tool_name='DeudaVencimientos',
	),
	'misfacilidades': ToolSpec(
		tool_key='misfacilidades',
		intent=Intent.MIS_FACILIDADES,
		keywords=('misfacilidades', 'mis facilidades', 'plan de pago', 'plan de pagos'),
		task_flags={'with_facilidades': True},
		formatter_name='format_facilidades_response',
		needs_browser=True,
		tool_name='MisFacilidades',
	),
	'rentascordoba': ToolSpec(
		tool_key='rentascordoba',
		intent=Intent.RENTAS_CORDOBA,
		keywords=('rentascordoba', 'rentas cordoba', 'iibb', 'ingresos brutos'),
		task_flags={'with_iibb': True, 'provincia': 'CORDOBA'},
		formatter_name='format_rentas_response',
		needs_browser=True,
		tool_name='RentasCordoba',
	),
	'consultaarca': ToolSpec(
		tool_key='consultaarca',
		intent=Intent.CONSULTA_ARCA,
		keywords=('consultaarca', 'obligaciones'),
		task_flags={},
		formatter_name='format_consultaarca_response',
		needs_browser=False,
		tool_name='ConsultaArca',
	),
	'calendariovencimientosarca': ToolSpec(
		tool_key='calendariovencimientosarca',
		intent=Intent.CALENDARIO_VENCIMIENTOS_ARCA,
		keywords=('calendariovencimientosarca', 'calendario', 'vencimientos'),
		task_flags={},
		formatter_name='format_calendario_response',
		needs_browser=False,
		tool_name='CalendarioVencimientosArca',
	),
}


# Biyección Intent → tool_key (solo tool intents; excluye TAXPAYER_QUERY / REPORTE_COMPLETO).
INTENT_TO_KEY: dict[Intent, str] = {spec.intent: key for key, spec in TOOL_SPECS.items()}


def get_tool_spec(intent: Intent) -> ToolSpec | None:
	"""Resuelve el ToolSpec del intent, o ``None`` si no es un tool intent."""
	key = INTENT_TO_KEY.get(intent)
	return TOOL_SPECS.get(key) if key else None