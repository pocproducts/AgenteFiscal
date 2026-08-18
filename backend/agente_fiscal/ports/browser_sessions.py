"""Browser session store port — persisted provider contexts + run metrics.

The Browserbase provider reuses a session across tools via CONTEXT
persistence (``browser_settings={'context': {'id': ..., 'persist': True}}`` in
``agents.runs.create``): the ARCA login cookies survive between runs, so the
next tool starts already logged in. The provider SDK does NOT accept
``user_metadata`` on ``agents.runs.create``, so the tenant/profile → context
mapping lives in OUR table, not as provider metadata.

This port owns that table. A single active row per (tenant_id, profile_id,
provider) cycles ``active ↔ in_use``:

- ``acquire`` — atomically claims the active, non-expired row (FOR UPDATE SKIP
  LOCKED) and marks it ``in_use``. Returns ``None`` when there is nothing to
  reuse (the caller then creates a fresh context upstream).
- ``create`` — inserts a row for a brand-new context (already created in
  Browserbase by the caller) as ``in_use``.
- ``release`` — marks the used row back to ``active`` and records the real run
  metrics (proxy bytes, duration, cost, timestamps); also renews ``expires_at``
  and can swap ``context_id`` when the context had to be recreated.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class BrowserSession(BaseModel):
    """Domain contract of a persisted provider session (no ORM leak)."""

    id: str
    tenant_id: str
    profile_id: str | None = None
    provider: str = 'browserbase'
    context_id: str
    status: str = 'active'
    session_id: str | None = None
    proxy_bytes: int | None = None
    duration_ms: int | None = None
    cost_cents: int | None = 0
    started_at: datetime | None = None
    ended_at: datetime | None = None
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.now)


@runtime_checkable
class BrowserSessionsRepository(Protocol):
    """Lifecycle + metrics store for persisted browser provider sessions."""

    async def acquire(
        self,
        tenant_id: uuid.UUID,
        profile_id: uuid.UUID | None,
        *,
        provider: str,
    ) -> BrowserSession | None:
        """Atomically claim the active, non-expired row and mark it ``in_use``.

        Uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so two concurrent tools
        never double-claim the same context. Returns ``None`` when no reusable
        row exists (caller then creates a fresh context in the provider).
        """
        ...

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        profile_id: uuid.UUID | None,
        provider: str,
        context_id: str,
        expires_at: datetime | None,
    ) -> BrowserSession:
        """Insert a row for a NEW context (already created in the provider)."""
        ...

    async def release(
        self,
        *,
        id: uuid.UUID,
        context_id: str | None = None,
        status: str = 'active',
        session_id: str | None = None,
        proxy_bytes: int | None = None,
        duration_ms: int | None = None,
        cost_cents: int | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        last_used_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> BrowserSession | None:
        """Flip the used row back (default ``active``) and record run metrics.

        ``context_id`` may be swapped when the provider context had to be
        recreated. Returns ``None`` when the row no longer exists.
        """
        ...


__all__ = [
    'BrowserSession',
    'BrowserSessionsRepository',
]