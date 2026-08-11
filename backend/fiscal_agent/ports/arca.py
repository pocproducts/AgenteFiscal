"""ARCA / Padrón A5 ports — abstraction over the SOAP WS API client."""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from fiscal_agent.domain.models import PadronA5Output


@runtime_checkable
class TicketProvider(Protocol):
	"""Provides an ARCA Ticket de Acceso (token + sign pair)."""

	def obtain(self, service: str = 'ws_sr_constancia_inscripcion') -> tuple[Optional[str], Optional[str]]:
		"""Return a cached/valid (token, sign) pair, refreshing when expired."""
		...


@runtime_checkable
class PadronProvider(Protocol):
	"""Queries the ARCA Padrón A5 for a CUIT."""

	def consultar_cuit(
		self,
		cuit: str,
		token: str,
		sign: str,
		representante_cuit: str,
	) -> object:
		"""Query padron data for *cuit*. Returns a ``PadronA5Result``-like object."""
		...


@runtime_checkable
class ArcaPort(Protocol):
	"""Combined facade over ticket obtaining and padron queries."""

	def get_ta(self, service: str = 'ws_sr_constancia_inscripcion') -> tuple[Optional[str], Optional[str]]:
		"""Return a cached (token, sign) pair."""
		...

	def consultar_cuit(
		self,
		cuit: str,
		token: str,
		sign: str,
		representante_cuit: str,
	) -> object:
		"""Query padron data for *cuit*. Returns a ``PadronA5Result``-like object."""
		...