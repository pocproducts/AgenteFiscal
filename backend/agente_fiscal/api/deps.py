"""Dependency injection and shared resources for API routes.

Initializes cached instances of RulesEngine, PdfGenerator, and
manages the WSAA Ticket de Acceso lifecycle for all endpoints.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from agente_fiscal.adapters.arca_ws import get_ta as _get_ta_arca
from agente_fiscal.config import CERT_DIR, CERT_PATH, KEY_PATH, REPRESENTANTE_CUIT, get_settings
from agente_fiscal.adapters.memory import FiscalMemoryClient
from agente_fiscal.adapters.pdf_generator import PdfGenerator
from agente_fiscal.domain.rules_engine import RulesEngine
from agente_fiscal.features import IntegrationDisabledError, arca_enabled, pdf_enabled

logger = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────────────────────

# Imported from agente_fiscal.config: CERT_DIR, CERT_PATH, KEY_PATH, REPRESENTANTE_CUIT

# ── Cached services ─────────────────────────────────────────────────────

_engine: Optional[RulesEngine] = None
_pdf_gen: Optional[PdfGenerator] = None
_memory: Optional[FiscalMemoryClient] = None


def get_engine() -> RulesEngine:
	"""Return cached RulesEngine instance."""
	global _engine
	if _engine is None:
		_engine = RulesEngine()
	return _engine


class _DisabledPdfGenerator:
	"""Guarded PDF generator: raises ``IntegrationDisabledError`` when used.

	Returned by ``get_pdf_gen()`` while ``PDF_ENABLED=false`` so the worker and
	routes keep working; the failure surfaces only when an actual PDF is
	requested, as a clean ``INTEGRATION_DISABLED`` error instead of a crash.
	"""

	def __init__(self, integration: str = 'pdf') -> None:
		self._integration = integration

	def __getattr__(self, _name: str):
		def _raise(*_args, **_kwargs):
			raise IntegrationDisabledError(self._integration)

		return _raise


def get_pdf_gen() -> PdfGenerator | _DisabledPdfGenerator:
	"""Return cached PdfGenerator instance.

	While ``PDF_ENABLED=false`` returns a guarded stub that raises
	``IntegrationDisabledError`` on first use (the pipeline catches it and
	reports a clean ``INTEGRATION_DISABLED`` error).
	"""
	global _pdf_gen
	if _pdf_gen is None:
		_pdf_gen = PdfGenerator() if pdf_enabled() else _DisabledPdfGenerator()
	return _pdf_gen


def get_memory() -> FiscalMemoryClient:
	"""Return cached FiscalMemoryClient instance (no-op if MEMORY_ENABLED=false)."""
	global _memory
	if _memory is None:
		_memory = FiscalMemoryClient(enabled=get_settings().memory_enabled)
	return _memory


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a scoped Postgres session from the app lifecycle session factory.

    Uses ``app.state.session_factory`` (wired in ``server.lifespan``) so the
    session shares the same engine the app owns. The session is closed when the
    request ends, mirroring the dependency in ``agente_fiscal.db.session``.
    """
    factory = getattr(request.app.state, 'session_factory', None)
    if factory is None:
        raise RuntimeError('app.state.session_factory is not set — lifespan not run')
    async with factory() as session:
        yield session


# get_ta wrapped from agente_fiscal.adapters.arca_ws — shared cache for CLI,
# API and MCP. Gated so a disabled ARCA integration never touches the network.


def get_ta(service: str = 'ws_sr_constancia_inscripcion') -> tuple[Optional[str], Optional[str]]:
	"""Return the cached Ticket de Acceso, or ``(None, None)`` when ARCA is disabled.

	While ``ARCA_ENABLED=false`` the underlying WSAA network calls are never
	performed — callers see ``(None, None)`` (same as a missing TA) and map it
	to their existing TA_UNAVAILABLE / error flow.
	"""
	if not arca_enabled():
		return None, None
	return _get_ta_arca(service)
