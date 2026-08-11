"""Ports package — abstract contracts (Protocols) between domain and infra.

Only interfaces live here; concrete implementations live in ``adapters``.
Domain code and ``pipeline`` depend on these protocols, never on adapters.
"""

from fiscal_agent.ports.arca import ArcaPort, PadronProvider, TicketProvider
from fiscal_agent.ports.browser import BrowserPort
from fiscal_agent.ports.email import EmailSenderPort
from fiscal_agent.ports.memory import (
	MemoryPort,
	MemoryReader,
	MemoryWriter,
)
from fiscal_agent.ports.pdf import PdfGeneratorPort
from fiscal_agent.ports.settings import SettingsPort

__all__ = [
	'ArcaPort',
	'BrowserPort',
	'EmailSenderPort',
	'MemoryPort',
	'MemoryReader',
	'MemoryWriter',
	'PadronProvider',
	'PdfGeneratorPort',
	'SettingsPort',
	'TicketProvider',
]