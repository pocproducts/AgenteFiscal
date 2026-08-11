"""Async engine, session factory, and FastAPI dependency.

The application engine connects through the POOLER URL (``DATABASE_URL``).
Alembic migrations run against the UNPOOLED URL (``DATABASE_URL_UNPOOLED``);
see ``alembic/env.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Awaitable, Callable, TypeVar

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from fiscal_agent.config import get_settings

T = TypeVar('T')

settings = get_settings()


def async_url(url: str) -> str:
    """Rewire a psycopg-style DSN to the SQLAlchemy asyncpg dialect.

    Neon connection strings use ``postgresql://`` / ``postgres://`` schemes,
    which SQLAlchemy maps to the synchronous psycopg driver. asyncpg requires
    ``postgresql+asyncpg://``.

    Also converts ``?sslmode=require`` (Neon default) to ``?ssl=require``:
    the asyncpg dialect forwards query params as connect() kwargs, and
    asyncpg accepts ``ssl`` but not ``sslmode``.
    """
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql+asyncpg://', 1)
    elif url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+asyncpg://', 1)

    scheme, _, rest = url.partition('://')
    base, _, query = rest.partition('?')
    if query:
        from urllib.parse import parse_qsl, urlencode

        params = dict(parse_qsl(query))
        # asyncpg has no channel_binding support (libpq-only); drop it.
        params.pop('channel_binding', None)
        if 'sslmode' in params and 'ssl' not in params:
            params['ssl'] = params.pop('sslmode')
        url = f'{scheme}://{base}?{urlencode(params)}'
    return url


engine: AsyncEngine = create_async_engine(
    async_url(settings.database.url),
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a scoped async session."""
    async with async_session_factory() as session:
        yield session


def run_sync(coro_fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run an async function that takes a session inside a fresh event loop.

    Intended for scripts/CLI (seed, one-off jobs). Disposes the engine so the
    pooled connections do not outlive the closed loop.
    """

    async def _wrapper() -> T:
        try:
            async with async_session_factory() as session:
                result = await coro_fn(session)
                await session.commit()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(_wrapper())


__all__ = [
    'AsyncSession',
    'async_session_factory',
    'async_url',
    'engine',
    'get_session',
    'run_sync',
]