"""Settings ports — abstraction over the app/env configuration.

Domain and pipeline code consume this port instead of importing
``fiscal_agent.config`` directly, killing the ``config.py:140`` import-time
``get_settings()`` trap for pure business code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class SettingsPort(Protocol):
	"""Exposes the environment-derived values business code needs."""

	representante_cuit: str
	clave_fiscal: str
	composio_api_key: str
	cert_dir: Path
	cert_path: Path
	key_path: Path

	def smtp_config(self) -> object:
		"""Return the SMTP config object (``SmtpConfig``-like)."""
		...