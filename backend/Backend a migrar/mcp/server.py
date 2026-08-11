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

from fiscal_agent.api.deps import get_ta
from fiscal_agent.config import get_settings
from fiscal_agent.memory import FiscalMemoryClient
from fiscal_agent.pdf_generator import PdfGenerator
from fiscal_agent.rules_engine import RulesEngine

logger = logging.getLogger(__name__)

load_dotenv()


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
	"""Lifespan context: init services once, share with all tools.

	Yields a dict with:
	  - engine:      RulesEngine instance
	  - pdf_gen:     PdfGenerator instance
	  - ta_cache:    (token, sign) tuple from get_ta()
	  - browser:     ComposioBrowser or None (if COMPOSIO_API_KEY not set)
	  - memory:      FiscalMemoryClient instance (best-effort, never raises)
	"""
	logger.info('[mcp] Initializing services ...')
	engine = RulesEngine()
	pdf_gen = PdfGenerator()
	ta_cache = get_ta()
	memory = FiscalMemoryClient()

	# Browser: lazy init, only if env is configured
	browser = None
	creds = get_settings().credentials
	composio_key = creds.composio_api_key
	if composio_key:
		try:
			from fiscal_agent.browser import ComposioBrowser

			estudio_cuit = creds.cuit
			estudio_clave = creds.clave_fiscal
			browser = ComposioBrowser(
				composio_api_key=composio_key,
				estudio_cuit=estudio_cuit,
				estudio_clave=estudio_clave,
				headed=False,
			)
			logger.info('[mcp] ComposioBrowser initialized')
		except Exception as exc:
			logger.warning('[mcp] Failed to init ComposioBrowser: %s', exc)

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

mcp = FastMCP('fiscal-agent', lifespan=lifespan)


# ── Tool registration (import triggers @mcp.tool() decorator) ──────────────

# Phase 2: Simple tools (no browser needed)
from fiscal_agent.mcp.tools import calendar  # noqa: F401, E402
from fiscal_agent.mcp.tools import health  # noqa: F401, E402
from fiscal_agent.mcp.tools import taxpayer  # noqa: F401, E402

# Phase 3: Browser tools
from fiscal_agent.mcp.tools import deuda  # noqa: F401, E402
from fiscal_agent.mcp.tools import facilidades  # noqa: F401, E402
from fiscal_agent.mcp.tools import registro  # noqa: F401, E402

# Phase 4: Complex tools
from fiscal_agent.mcp.tools import pipeline  # noqa: F401, E402
from fiscal_agent.mcp.tools import rentas  # noqa: F401, E402
from fiscal_agent.mcp.tools import report  # noqa: F401, E402

# Phase 5: Memory tools
from fiscal_agent.mcp.tools import memory  # noqa: F401, E402
