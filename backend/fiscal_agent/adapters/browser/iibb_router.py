"""Mapea nombre de provincia → template NL para extracción IIBB.

El router centraliza la selección del template en un solo punto.
Agregar una provincia nueva = agregar entrada al dict + crear el módulo template.
No requiere modificar el código cliente.
"""

from __future__ import annotations

from typing import ClassVar

from fiscal_agent.adapters.browser.workflows.iibb.cordoba import TEMPLATE_IIBB_CORDOBA
from fiscal_agent.adapters.browser.workflows.iibb.jujuy import TEMPLATE_IIBB_JUJUY


class IIBBRouter:
	"""Selecciona template NL de IIBB según provincia.

	Uso:
		>>> IIBBRouter.get('CORDOBA')  # → TEMPLATE_IIBB_CORDOBA
		>>> IIBBRouter.get(None)  # → TEMPLATE_IIBB_CORDOBA (fallback)
		>>> IIBBRouter.get('DESCONOCIDA')  # → TEMPLATE_IIBB_CORDOBA (fallback)
	"""

	_templates: ClassVar[dict[str, str]] = {
		'CORDOBA': TEMPLATE_IIBB_CORDOBA,
		# JUJUY: inhabilitado hasta tener el template real del portal DGR Jujuy
		# 'JUJUY': TEMPLATE_IIBB_JUJUY,
	}

	@classmethod
	def get(cls, provincia: str | None = None) -> str:
		"""Retorna el template NL para la provincia indicada.

		Args:
			provincia: Nombre de provincia (case-insensitive).
			           None o vacío → Córdoba (fallback).

		Returns:
			Template string listo para Composio Browser Tool.
		"""
		if not provincia:
			return cls._templates['CORDOBA']
		provincia_upper = provincia.upper().strip()
		return cls._templates.get(provincia_upper, cls._templates['CORDOBA'])
