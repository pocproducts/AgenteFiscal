"""FastMCP server with lifespan context for Fiscal-Agent.

Initializes shared services once (RulesEngine, PdfGenerator, TA cache,
ComposioBrowser) and exposes them to all tools via lifespan context.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from agente_fiscal.api.deps import get_ta
from agente_fiscal.adapters.memory import FiscalMemoryClient
from agente_fiscal.adapters.pdf_generator import PdfGenerator
from agente_fiscal.domain.rules_engine import RulesEngine
from agente_fiscal.features import integration_enabled

logger = logging.getLogger(__name__)

load_dotenv()


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
	"""Lifespan context: init services once, share with all tools.

	Yields a dict with:
	  - engine:      RulesEngine instance
	  - pdf_gen:     PdfGenerator instance
	  - ta_cache:    (token, sign) tuple from get_ta()
	  - browser:     browser provider (BrowserPort) or None (si la integración
	    está deshabilitada o faltan credenciales)
	  - memory:      FiscalMemoryClient instance (best-effort, never raises)
	"""
	logger.info('[mcp] Initializing services ...')
	engine = RulesEngine()
	pdf_gen = PdfGenerator()
	ta_cache = get_ta()
	memory = FiscalMemoryClient()

	# Browser: lazy init, only if the integration is enabled
	browser = None
	if integration_enabled('browser'):
		try:
			from agente_fiscal.adapters.browser.provider import build_browser_provider

			browser = build_browser_provider()
			logger.info('[mcp] Browser provider initialized: %s', type(browser).__name__ if browser else 'None')
		except Exception as exc:
			logger.warning('[mcp] Failed to init browser provider: %s', exc)

	ctx = {
		'engine': engine,
		'pdf_gen': pdf_gen,
		'ta_cache': ta_cache,
		'browser': browser,
		'memory': memory,
	}
	logger.info('[mcp] Services ready (browser=%s)', 'yes' if browser else 'no')

	try:
		yield ctx
	finally:
		# Cleanup browser sessions if any
		if browser is not None:
			try:
				import asyncio

				asyncio.run(browser.close())
				logger.info('[mcp] Browser closed')
			except Exception:
				pass


# ── FastMCP app ─────────────────────────────────────────────────────────────

mcp = FastMCP('agente-fiscal', lifespan=lifespan)


# ── Tool registration (import triggers @mcp.tool() decorator) ──────────────

# Phase 2: Simple tools (no browser needed)
from agente_fiscal.mcp.tools import calendar  # noqa: F401, E402
from agente_fiscal.mcp.tools import health  # noqa: F401, E402
from agente_fiscal.mcp.tools import taxpayer  # noqa: F401, E402

# Phase 3: Browser tools
from agente_fiscal.mcp.tools import deuda  # noqa: F401, E402
from agente_fiscal.mcp.tools import facilidades  # noqa: F401, E402
from agente_fiscal.mcp.tools import registro  # noqa: F401, E402

# Phase 4: Complex tools
from agente_fiscal.mcp.tools import pipeline  # noqa: F401, E402
from agente_fiscal.mcp.tools import rentas  # noqa: F401, E402
from agente_fiscal.mcp.tools import report  # noqa: F401, E402

# Phase 5: Memory tools
from agente_fiscal.mcp.tools import memory  # noqa: F401, E402
