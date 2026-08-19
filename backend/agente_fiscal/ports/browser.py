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
		on_task_metrics: Optional[Callable[[dict], None]] = None,
	) -> DeudaOutput:
		"""Run the given browser tasks for one client. Returns a DeudaOutput, never raises.

		``cliente`` may be ``None`` (the MCP tool passes only ``tasks``).

		``on_task_metrics`` is a SYNCHRONOUS callback for real run metrics
		(session_id, context_id, duration_ms, cost_cents, tasks): the dispatch
		passes it unconditionally (AST-5), so EVERY provider must accept it —
		providers without telemetry (composio, mock) accept-and-ignore, and the
		``agent_sessions`` row is written post-run by the backend anyway (ADR-3).
		The callback runs on the calling thread (inside ``to_thread``) and must
		never raise.
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