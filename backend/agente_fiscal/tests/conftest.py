"""Shared fixtures for the agente_fiscal test suite.

The ONLY real external dependency is the local test Postgres (``af_test``).
This module NEVER imports ``agente_fiscal.db.session`` and no code path here
reads the production ``DATABASE_URL`` from ``.env`` — every engine is built
from ``TEST_DATABASE_URL`` with a ``NullPool`` so no pooled connection leaks
across tests.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import agente_fiscal.db.models  # noqa: F401  — registers every table on Base.metadata
from agente_fiscal.db.base import Base
from agente_fiscal.db.models import (
    Client as ClientRow,
    Plan as PlanRow,
    Tenant as TenantRow,
    User as UserRow,
)
from agente_fiscal.domain.models import (
    CategoriaContribuyente,
    DatosGenerales,
    DatosMonotributo,
    DatosRegimenGeneral,
    ImpuestoInscripto,
    PadronA5Output,
    RegimenInscripto,
)

TEST_DATABASE_URL = 'postgresql+asyncpg://postgres:test@localhost:54329/af_test'


@pytest.fixture(scope='session')
async def test_engine():
    # ``ssl=False`` avoids asyncpg's TLS-preconnect attempt, which segfaults
    # under coverage tracing (local test Postgres needs no TLS anyway).
    engine = create_async_engine(
        TEST_DATABASE_URL,
        poolclass=NullPool,
        connect_args={'ssl': False},
    )
    yield engine
    await engine.dispose()


@pytest.fixture
async def test_session_factory(test_engine):
    yield async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture
async def db_reset(test_engine):
    """Drop and recreate every table from ``Base.metadata``.

    Function-scoped, NOT autouse: pure-unit test files (rules_engine) never
    touch the database. DB-backed files opt in via ``usefixtures`` on their
    module-level ``pytestmark``.
    """
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


# ─── Padrón A5 builders (rules_engine) ──────────────────────────────────────


@pytest.fixture
def make_padron():
    """Build a ``PadronA5Output`` with fine-grained control.

    Defaults to a responsible-inscripto pay-taxpayer with IVA (impuesto 30).
    ``impuestos``/``regimenes`` are lists of ids; ``monotributo`` and
    ``autonomo`` toggle the corresponding sections; ``**overrides`` are
    shallow-merges over the assembled ``PadronA5Output``.
    """
    def _make(
        cuit: str = '20301234561',
        impuestos: tuple = (30,),
        regimenes: tuple = (),
        monotributo: bool = False,
        autonomo: bool = False,
        **overrides,
    ) -> PadronA5Output:
        pregion_general = DatosRegimenGeneral(
            impuestos=[ImpuestoInscripto(idImpuesto=i) for i in impuestos],
            regimenes=[RegimenInscripto(idRegimen=r) for r in regimenes],
            categoriasAutonomo=[CategoriaContribuyente(idCategoria=1)] if autonomo else [],
        )
        padron = PadronA5Output(
            datosGenerales=DatosGenerales(idPersona=cuit),
            regimenGeneral=pregion_general,
            monotributo=DatosMonotributo() if monotributo else None,
        )
        if overrides:
            padron = padron.model_copy(update=overrides)
        return padron

    return _make


# ─── Multi-tenant DB row builders ──────────────────────────────────────────


@pytest.fixture
def make_tenant():
    """Insert (flush, no commit) a ``tenants`` row via ``session``."""
    async def _make(
        session,
        *,
        name: str = 'Acme SA',
        clerk_org_id: str | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> TenantRow:
        row = TenantRow(
            id=tenant_id or uuid.uuid4(),
            name=name,
            clerk_org_id=clerk_org_id,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    return _make


@pytest.fixture
def make_user():
    """Insert (flush, no commit) a ``users`` row via ``session``."""
    async def _make(
        session,
        *,
        clerk_user_id: str,
        email: str = '',
        display_name: str | None = None,
    ) -> UserRow:
        row = UserRow(
            clerk_user_id=clerk_user_id,
            email=email,
            display_name=display_name,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    return _make


@pytest.fixture
def make_client():
    """Insert (flush, no commit) a ``clients`` row via ``session``."""
    async def _make(
        session,
        *,
        tenant_id: uuid.UUID,
        cuit: str,
        name: str,
        email: str | None = None,
        config: dict | None = None,
    ) -> ClientRow:
        row = ClientRow(
            tenant_id=tenant_id,
            cuit=cuit,
            name=name,
            email=email,
            config=config or {},
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    return _make


@pytest.fixture
def make_plan():
    """Insert (flush, no commit) a catalog ``plans`` row via ``session``."""
    async def _make(
        session,
        *,
        slug: str = 'free',
        name: str = 'Free',
        tier: str = 'free',
        is_active: bool = True,
        limits: dict | None = None,
        features: dict | None = None,
    ) -> PlanRow:
        row = PlanRow(
            slug=slug,
            name=name,
            tier=tier,
            is_active=is_active,
            limits=limits or {},
            features=features or {},
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    return _make