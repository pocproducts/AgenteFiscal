"""PDF ports — abstraction over the reportlab calendar generator."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from fiscal_agent.domain.models import DeudaOutput, RentasCordobaMatching, Vencimiento


@runtime_checkable
class PdfGeneratorPort(Protocol):
	"""Generates the fiscal calendar PDF for a client."""

	def generar(
		self,
		nombre: str,
		cuit: str,
		vtos: list[Vencimiento],
		mes: int,
		anio: int,
		observaciones: Optional[list[str]] = None,
		deuda: Optional[DeudaOutput] = None,
		rentas_matching: Optional[RentasCordobaMatching] = None,
		output_dir: Optional[Path] = None,
	) -> Path:
		"""Generate the calendar PDF. Returns the output Path."""
		...