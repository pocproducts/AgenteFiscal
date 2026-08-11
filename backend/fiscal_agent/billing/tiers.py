"""Planes de negocio y reglas de pricing para Fiscal-Agent.

Define los tiers disponibles y las reglas de cada uno: límites de uso,
costos por recurso, tarifa plana mensual y nivel de soporte.

Los valores actuales son semilla para validar la hipótesis de producto.
"""

from __future__ import annotations

from typing import Any

from fiscal_agent.models import PlanTier


# ── Reglas de pricing por plan ───────────────────────────────────────────

PLAN_RULES: dict[PlanTier, dict[str, Any]] = {
	PlanTier.free: {
		'max_contribuyentes': 50,
		'precio_segundo_browser': 0.0,  # incluido en flat fee
		'flat_fee_mensual': 99,  # USD
		'soporte': 'email',
		'descripcion': 'Para estudios contables con cartera de hasta 50 contribuyentes',
	},
	PlanTier.pro: {
		'max_contribuyentes': 10,
		'precio_segundo_browser': 0.05,  # USD/segundo
		'flat_fee_mensual': 0,
		'soporte': 'comunidad',
		'descripcion': 'Para contadores individuales',
	},
	PlanTier.pro_max: {
		'max_contribuyentes': 200,
		'precio_segundo_browser': 0.03,  # USD/segundo
		'flat_fee_mensual': 199,  # USD
		'soporte': 'prioritario',
		'descripcion': 'Para estudios con demanda intermedia',
	},
	PlanTier.enterprise: {
		'max_contribuyentes': -1,  # ilimitado
		'precio_segundo_browser': 0.02,  # USD/segundo (preferencial)
		'flat_fee_mensual': 299,  # USD
		'soporte': 'dedicado',
		'descripcion': 'Para estudios multi-cliente o empresas',
	},
}


# ── Funciones ────────────────────────────────────────────────────────────


def calcular_costo(
	plan: PlanTier,
	duration_segundos: float,
	steps: int = 0,
) -> dict[str, Any]:
	"""Calcula el costo de una ejecución según el plan del cliente.

	Parameters
	----------
	plan : PlanTier
	    Plan del cliente que ejecutó la tarea.
	duration_segundos : float
	    Duración total de las tasks browser (time.monotonic).
	steps : int
	    Cantidad de steps ejecutados en Composio.

	Returns
	-------
	dict
	    ``plan``, ``duration_s``, ``steps``, ``costo_browser``,
	    ``flat_fee_mensual``, ``moneda``.

	Examples
	--------
	>>> calcular_costo(PlanTier.free, 120.5)
	{'plan': 'free', 'duration_s': 120.5, 'steps': 0,
	 'costo_browser': 0.0, 'flat_fee_mensual': 99, 'moneda': 'USD'}
	"""
	rules = PLAN_RULES[plan]
	costo_browser = rules['precio_segundo_browser'] * duration_segundos

	return {
		'plan': plan.value,
		'duration_s': round(duration_segundos, 2),
		'steps': steps,
		'costo_browser': round(costo_browser, 2),
		'flat_fee_mensual': rules['flat_fee_mensual'],
		'moneda': 'USD',
	}
