"""Adapters package — concrete infrastructure implementations.

Houses wired infra: ARCA WS SOAP client, Composio browser + tasks,
Engram/Redis memory client, SMTP email sender, reportlab PDF generator,
and the Postgres API-key port (cutover Phase 5).
"""

from agente_fiscal.adapters.arca_ws import consultar_cuit, consultar_padron, get_ta
from agente_fiscal.adapters.db_api_keys import PostgresApiKeyPort, hash_api_key
from agente_fiscal.adapters.email_sender import EmailSender
from agente_fiscal.adapters.pdf_generator import PdfGenerator

__all__ = [
	'EmailSender',
	'PdfGenerator',
	'PostgresApiKeyPort',
	'consultar_cuit',
	'consultar_padron',
	'get_ta',
	'hash_api_key',
]