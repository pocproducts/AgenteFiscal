"""Adapters package — concrete infrastructure implementations.

Houses wired infra: ARCA WS SOAP client, Composio browser + tasks,
Engram/Redis memory client, SMTP email sender, reportlab PDF generator,
and the Postgres API-key port (cutover Phase 5).
"""

from fiscal_agent.adapters.arca_ws import consultar_cuit, consultar_padron, get_ta
from fiscal_agent.adapters.db_api_keys import PostgresApiKeyPort, hash_api_key
from fiscal_agent.adapters.email_sender import EmailSender
from fiscal_agent.adapters.pdf_generator import PdfGenerator

__all__ = [
	'EmailSender',
	'PdfGenerator',
	'PostgresApiKeyPort',
	'consultar_cuit',
	'consultar_padron',
	'get_ta',
	'hash_api_key',
]