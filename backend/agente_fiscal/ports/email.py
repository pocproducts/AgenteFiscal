"""Email ports — abstraction over the SMTP sender."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from agente_fiscal.domain.models import ClientConfig


@runtime_checkable
class EmailSenderPort(Protocol):
	"""Sends generated calendar PDFs to clients."""

	def enviar(self, cliente: ClientConfig, pdf_path: Path, mes: int, anio: int) -> bool:
		"""Send a single calendar email. Returns True on success."""
		...

	def enviar_lote(self, clientes: list[ClientConfig], pdfs: list[Path], mes: int, anio: int) -> list[bool]:
		"""Send PDFs to multiple clients. Returns per-client booleans."""
		...