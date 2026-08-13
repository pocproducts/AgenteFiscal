"""Ports package — abstract contracts (Protocols) between domain and infra.

Only interfaces live here; concrete implementations live in ``adapters``.
Domain code and ``pipeline`` depend on these protocols, never on adapters.
"""

from agente_fiscal.ports.arca import ArcaPort, PadronProvider, TicketProvider
from agente_fiscal.ports.api_keys import (
	ApiKeyContext,
	ApiKeyPort,
	ApiKeyRepository,
	ApiKeyStoreUnavailableError,
)
from agente_fiscal.ports.browser import BrowserPort
from agente_fiscal.ports.email import EmailSenderPort
from agente_fiscal.ports.memory import (
	MemoryPort,
	MemoryReader,
	MemoryWriter,
)
from agente_fiscal.ports.pdf import PdfGeneratorPort
from agente_fiscal.ports.settings import SettingsPort

__all__ = [
	'ArcaPort',
	'ApiKeyContext',
	'ApiKeyPort',
	'ApiKeyRepository',
	'ApiKeyStoreUnavailableError',
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