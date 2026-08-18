"""Browser ports — the interface consumed by the extraction layer.

The pipeline/API/CLI/MCP depend on ``BrowserPort``, never on a concrete
provider. Concrete providers (ComposioBrowser, MockBrowser, future ones)
are resolved by name through ``adapters.browser.provider.build_browser_provider``.
"""

from __future__ import annotations

from typing import Callable, Optional, Protocol, runtime_checkable

from agente_fiscal.domain.models import ClientConfig, DeudaOutput


@runtime_checkable
class BrowserRunnerPort(Protocol):
	"""Runs browser extraction tasks for a client."""

	def run_single(
		self,
		cliente: Optional[ClientConfig],
		tasks: Optional[list[object]] = None,
		echo_func: Optional[Callable[[str], None]] = None,
		on_live_url: Optional[Callable[[str], None]] = None,
		on_step: Optional[Callable[[int, str, str, str], None]] = None,
	) -> DeudaOutput:
		"""Run the given browser tasks for one client. Returns a DeudaOutput, never raises.

		``cliente`` may be ``None`` (the MCP tool passes only ``tasks``).
		"""
		...


@runtime_checkable
class BrowserPort(BrowserRunnerPort, Protocol):
	"""Full browser automation contract (runner + batch + lifecycle)."""

	async def run_all(self, clientes: list[ClientConfig]) -> list[DeudaOutput]:
		"""Process every client (typically in parallel), 1:1 with the input."""
		...

	async def close(self) -> None:
		"""Release browser resources."""
		...