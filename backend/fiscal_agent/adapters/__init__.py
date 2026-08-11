"""Adapters package — concrete infrastructure implementations.

Houses wired infra: ARCA WS SOAP client, Composio browser + tasks,
Engram/Redis memory client, SMTP email sender, and reportlab PDF generator.
"""

from fiscal_agent.adapters.arca_ws import consultar_cuit, consultar_padron, get_ta
from fiscal_agent.adapters.email_sender import EmailSender
from fiscal_agent.adapters.pdf_generator import PdfGenerator

__all__ = [
	'EmailSender',
	'PdfGenerator',
	'consultar_cuit',
	'consultar_padron',
	'get_ta',
]