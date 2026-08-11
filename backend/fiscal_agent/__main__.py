"""Fiscal agent entry point: uv run python -m fiscal_agent [command].

Usage:
	uv run python -m fiscal_agent validate [config]      Validar clients.yaml
	uv run python -m fiscal_agent generate-template      Generar CSV template
	uv run python -m fiscal_agent run                    Ejecutar pipeline completo
	uv run python -m fiscal_agent report                 Generar informe interactivo
	uv run python -m fiscal_agent mcp                    Iniciar servidor MCP (STDIO)
	uv run python -m fiscal_agent <comando> --help       Ayuda del comando

MCP (Model Context Protocol):
	python -m fiscal_agent mcp                           STDIO (default, local)
	MCP_TRANSPORT=http python -m fiscal_agent mcp        HTTP/SSE (remoto, con auth)
"""

import sys


def main() -> None:
	"""Entry point: dispatches to CLI or MCP server based on first argument."""
	if len(sys.argv) > 1 and sys.argv[1] == 'mcp':
		# Remove 'mcp' from argv before dispatching to transport
		sys.argv.pop(1)
		from fiscal_agent.mcp.transport import run_mcp

		run_mcp()
	else:
		from fiscal_agent.cli import main as cli_main

		cli_main()


if __name__ == '__main__':
	main()
