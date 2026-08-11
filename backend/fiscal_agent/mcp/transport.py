"""Transport dispatcher for the MCP server.

Reads MCP_TRANSPORT env var:
  - stdio (default): runs via stdin/stdout — local only.
  - http: wraps mcp.sse_app() in Starlette.

Auth status:
    MCP STDIO transport: no auth (local only).
    MCP HTTP transport: auth REMOVED — TODO: re-add bearer/API-key auth
    before exposing over network.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def run_mcp() -> None:
	"""Run the MCP server based on MCP_TRANSPORT env var.

	Usage:
	    python -m fiscal_agent mcp           → STDIO (default)
	    MCP_TRANSPORT=http python -m fiscal_agent mcp  → HTTP/SSE
	"""
	transport = os.environ.get('MCP_TRANSPORT', 'stdio').strip().lower()

	if transport == 'http':
		_run_http()
	else:
		_run_stdio()


def _run_stdio() -> None:
	"""Run MCP server via STDIO transport — local only, no auth."""
	from fiscal_agent.mcp.server import mcp

	logger.info('[mcp] Starting STDIO transport ...')
	mcp.run(transport='stdio')


def _run_http() -> None:
	"""Run MCP server via HTTP/SSE transport.

	Auth status: auth REMOVED — TODO: re-add bearer/API-key auth before
	exposing this over a network. Local-only for now.
	"""
	from fiscal_agent.mcp.server import mcp
	from starlette.applications import Starlette

	sse_app = mcp.sse_app()

	app = Starlette(routes=sse_app.routes)

	logger.info('[mcp] Starting HTTP/SSE transport on port 8000 ...')
	import uvicorn

	uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('MCP_PORT', '8000')))
