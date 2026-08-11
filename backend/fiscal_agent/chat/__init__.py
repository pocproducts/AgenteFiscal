"""Chat AI — intent routing and response formatting for the fiscal chat interface.

Re-exports from ``domain`` (the logic moved to the domain layer).
"""

from fiscal_agent.domain.intent_router import Intent, detect
from fiscal_agent.domain.response_builder import (
	format_reporte_response,
	format_taxpayer_response,
)

__all__ = ['Intent', 'detect', 'format_reporte_response', 'format_taxpayer_response']