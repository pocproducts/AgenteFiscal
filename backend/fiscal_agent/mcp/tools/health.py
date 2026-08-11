"""MCP tool: health — server liveness check.

Public scope (no auth required even in HTTP mode).
"""

from __future__ import annotations

from datetime import datetime, timezone

from mcp.server.fastmcp import Context

from fiscal_agent.mcp.server import mcp
from fiscal_agent.models import ApiError, UnifiedResponse


@mcp.tool()
async def health(ctx: Context) -> str:
	"""Check if the MCP server is alive and the TA cache is available.

	Returns server status, timestamp, and whether the Ticket de Acceso
	is currently cached.
	"""
	svc = ctx.request_context.lifespan_context
	ta_cache = svc.get('ta_cache', (None, None))
	token, _sign = ta_cache
	ta_vigente = token is not None

	result = {
		'status': 'ok',
		'timestamp': datetime.now(timezone.utc).isoformat(),
		'ta_vigente': ta_vigente,
	}

	return UnifiedResponse(status='success', result=result).model_dump_json()
