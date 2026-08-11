"""MCP server package — Model Context Protocol para Fiscal-Agent.

Expone el pipeline fiscal como tools MCP para LLMs via FastMCP.
STDIO por defecto; HTTP/SSE opcional con auth de Fase 2.
"""

from fiscal_agent.mcp.server import mcp
from fiscal_agent.mcp.transport import run_mcp

__all__ = ['mcp', 'run_mcp']
