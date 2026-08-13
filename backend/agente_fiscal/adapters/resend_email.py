"""Resend-backed email adapter — implements ``agente_fiscal.ports.email.EmailSenderPort``.

Sends generated calendar PDFs via the Resend HTTP API
(https://resend.com/docs/api-reference/emails/send-email). This is the live
mechanism ``PipelineService`` resolves by default (see
``pipeline/service.py::_email_sender_obj``) — configured once via
``RESEND_API_KEY``/``EMAIL_FROM`` settings, no per-call SMTP config needed.

The legacy SMTP sender (``adapters/email_sender.py``) remains only for the
CLI's ``clients.yaml`` batch path.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import List

import requests

from agente_fiscal.adapters.email_content import build_body, build_subject
from agente_fiscal.domain.models import ClientConfig

logger = logging.getLogger(__name__)

_RESEND_API_URL = 'https://api.resend.com/emails'
_TIMEOUT = 30


class ResendEmailSender:
	"""Sends calendar PDFs via the Resend HTTP API.

	Args:
		api_key: Resend API key (``RESEND_API_KEY``).
		from_addr: Verified sender address, e.g. ``"Estudio Contable <reportes@tudominio.com>"``
			(``EMAIL_FROM``).
	"""

	def __init__(self, api_key: str, from_addr: str) -> None:
		self._api_key = api_key
		self._from_addr = from_addr

	def enviar(self, cliente: ClientConfig, pdf_path: Path, mes: int, anio: int) -> bool:
		"""Send a single calendar email. Returns True on success."""
		if not self._api_key or not self._from_addr:
			logger.error('Resend no configurado (RESEND_API_KEY/EMAIL_FROM) — no se puede enviar email')
			return False
		if not cliente.email:
			logger.warning('Cliente %s sin email — salteando envío', cliente.cuit)
			return False

		nombre = cliente.nombre or cliente.cuit
		payload: dict[str, object] = {
			'from': self._from_addr,
			'to': [cliente.email],
			'subject': build_subject(nombre, mes, anio),
			'text': build_body(nombre, mes, anio),
		}

		if pdf_path.exists():
			payload['attachments'] = [
				{
					'filename': pdf_path.name,
					'content': base64.b64encode(pdf_path.read_bytes()).decode('ascii'),
				}
			]
		else:
			logger.warning('PDF no encontrado: %s — enviando sin adjunto', pdf_path)

		try:
			resp = requests.post(
				_RESEND_API_URL,
				headers={
					'Authorization': f'Bearer {self._api_key}',
					'Content-Type': 'application/json',
				},
				json=payload,
				timeout=_TIMEOUT,
			)
			resp.raise_for_status()
		except requests.RequestException as exc:
			logger.error('Email FAIL (Resend): %s -> %s: %s', nombre, cliente.email, exc)
			return False

		logger.info('Email OK (Resend): %s -> %s', nombre, cliente.email)
		return True

	def enviar_lote(
		self,
		clientes: List[ClientConfig],
		pdfs: List[Path],
		mes: int,
		anio: int,
	) -> List[bool]:
		"""Send PDFs to multiple clients. Each failure is isolated — one does not block others."""
		return [self.enviar(cliente, pdf, mes, anio) for cliente, pdf in zip(clientes, pdfs, strict=False)]


__all__ = ['ResendEmailSender']
