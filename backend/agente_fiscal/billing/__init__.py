"""Módulo de billing — modelos de negocio, planes y cálculo de costos.

Jerarquía de planes y reglas de pricing para la plataforma Fiscal-Agent.
Cada tenant/cliente pertenece a un plan que define límites, precios y
nivel de soporte.

Uso:
    from agente_fiscal.billing import PlanTier, calcular_costo

    costo = calcular_costo(PlanTier.free, duration_s=120.5, steps=15)
    # → { plan: "estudio", duration_s: 120.5, steps: 15, costo_browser: 0.0, ... }
"""

from agente_fiscal.domain.tiers import PlanTier, PLAN_RULES, calcular_costo

__all__ = ['PlanTier', 'PLAN_RULES', 'calcular_costo']
