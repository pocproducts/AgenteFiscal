"""Browser ports — abstraction over the Composio browser extraction runner."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Protocol, runtime_checkable

from fiscal_agent.domain.models import ClientConfig, DeudaOutput


@runtime_checkable
class BrowserRunnerPort(Protocol):
	"""Runs browser extraction tasks for a client."""

	def run_single(
		self,
		cliente: ClientConfig,
		tasks: Optional[list[object]] = None,
		echo_func: Optional[Callable[[str], None]] = None,
	) -> DeudaOutput:
		"""Run the given browser tasks. Returns a DeudaOutput, never raises."""
		...


@runtime_checkable
class BrowserPort(BrowserRunnerPort, Protocol):
	"""Full browser automation contract (runner + lifecycle)."""

	async def close(self) -> None:
		"""Release browser resources."""
		...