"""Agente Fiscal entry point: uv run python -m agente_fiscal [command].

Usage:
	uv run python -m agente_fiscal validate [config]      Validar clients.yaml
	uv run python -m agente_fiscal generate-template      Generar CSV template
	uv run python -m agente_fiscal run                    Ejecutar pipeline completo
	uv run python -m agente_fiscal report                 Generar informe interactivo
	uv run python -m agente_fiscal mcp                    Iniciar servidor MCP (STDIO)
	uv run python -m agente_fiscal <comando> --help       Ayuda del comando

MCP (Model Context Protocol):
	python -m agente_fiscal mcp                           STDIO (default, local)
	MCP_TRANSPORT=http python -m agente_fiscal mcp        HTTP/SSE (remoto, con auth)
"""

import sys


def main() -> None:
	"""Entry point: dispatches to CLI or MCP server based on first argument."""
	if len(sys.argv) > 1 and sys.argv[1] == 'mcp':
		# Remove 'mcp' from argv before dispatching to transport
		sys.argv.pop(1)
		from agente_fiscal.mcp.transport import run_mcp

		run_mcp()
	else:
		from agente_fiscal.cli import main as cli_main

		cli_main()


if __name__ == '__main__':
	main()
