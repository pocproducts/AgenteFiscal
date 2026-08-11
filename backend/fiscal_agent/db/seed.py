"""Idempotent seed for Phase 1.

Seeds ONLY:
  - one default ``Tenant`` ("Estudio Contable")

No plans (the ``plans`` table is a global catalog, seeded by migration
0002), no subscriptions / invoices / payments — those arrive with Clerk
and payment providers in Phase 2.
Safe to run repeatedly: existence is checked via plain ``select()``.
"""

from __future__ import annotations

from sqlalchemy import select

from fiscal_agent.db.models import Tenant
from fiscal_agent.db.session import run_sync

DEFAULT_TENANT_NAME = 'Estudio Contable'


async def _seed(session) -> None:
    tenant = await session.scalar(select(Tenant).where(Tenant.name == DEFAULT_TENANT_NAME))
    if tenant is None:
        tenant = Tenant(name=DEFAULT_TENANT_NAME)
        session.add(tenant)
        await session.flush()
        print(f'[seed] created tenant: {tenant.id} ({DEFAULT_TENANT_NAME})')
    else:
        print(f'[seed] tenant already present: {tenant.id} ({tenant.name})')


def main() -> None:
    run_sync(_seed)


if __name__ == '__main__':
    main()