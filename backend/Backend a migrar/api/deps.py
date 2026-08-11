"""Dependency injection and shared resources for API routes.

Initializes cached instances of RulesEngine, PdfGenerator, and
manages the WSAA Ticket de Acceso lifecycle for all endpoints.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fiscal_agent.arca_ws import get_ta
from fiscal_agent.config import CERT_DIR, CERT_PATH, KEY_PATH, REPRESENTANTE_CUIT, get_settings
from fiscal_agent.memory import FiscalMemoryClient
from fiscal_agent.pdf_generator import PdfGenerator
from fiscal_agent.rules_engine import RulesEngine

logger = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────────────────────

# Imported from fiscal_agent.config: CERT_DIR, CERT_PATH, KEY_PATH, REPRESENTANTE_CUIT

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


def get_pdf_gen() -> PdfGenerator:
	"""Return cached PdfGenerator instance."""
	global _pdf_gen
	if _pdf_gen is None:
		_pdf_gen = PdfGenerator()
	return _pdf_gen


def get_memory() -> FiscalMemoryClient:
	"""Return cached FiscalMemoryClient instance (best-effort, never raises)."""
	global _memory
	if _memory is None:
		_memory = FiscalMemoryClient()
	return _memory


# get_ta imported from fiscal_agent.arca_ws — shared cache for CLI, API, MCP
