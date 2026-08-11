"""Email sender for fiscal calendar PDF delivery.

Sends calendar PDFs via SMTP with professional subject/body.
One client failure MUST NOT block others — each send is isolated.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional

from fiscal_agent.models import ClientConfig, SmtpConfig

logger = logging.getLogger(__name__)

MESES_ES = [
	'',
	'Enero',
	'Febrero',
	'Marzo',
	'Abril',
	'Mayo',
	'Junio',
	'Julio',
	'Agosto',
	'Setiembre',
	'Octubre',
	'Noviembre',
	'Diciembre',
]


class EmailSender:
	"""SMTP email sender for fiscal calendar delivery.

	Args:
		smtp_config: SMTP server configuration from clients.yaml.
	"""

	def __init__(self, smtp_config: SmtpConfig) -> None:
		self.smtp = smtp_config

	def enviar(
		self,
		cliente: ClientConfig,
		pdf_path: Path,
		mes: int,
		anio: int,
	) -> bool:
		"""Send a single calendar email.

		Args:
			cliente: Client config with name, email, CUIT.
			pdf_path: Path to the generated PDF file.
			mes: Month number (1-12).
			anio: Year (e.g. 2026).

		Returns:
			True if sent successfully, False on error.
		"""
		try:
			msg = self._build_message(cliente, pdf_path, mes, anio)
			self._send(msg)
			logger.info('Email OK: %s -> %s', cliente.nombre, cliente.email)
			return True
		except Exception as exc:
			logger.error('Email FAIL: %s -> %s: %s', cliente.nombre, cliente.email, exc)
			return False

	def enviar_lote(
		self,
		clientes: List[ClientConfig],
		pdfs: List[Path],
		mes: int,
		anio: int,
	) -> List[bool]:
		"""Send emails for multiple clients.

		Each client is isolated — one failure does not block others.

		Args:
			clientes: List of client configs.
			pdfs: List of PDF paths (same order as clientes).
			mes: Month number.
			anio: Year.

		Returns:
			List of booleans (True = sent, False = failed), one per client.
		"""
		results: List[bool] = []
		for cliente, pdf in zip(clientes, pdfs, strict=False):
			ok = self.enviar(cliente, pdf, mes, anio)
			results.append(ok)
		return results

	# ── Internal helpers ──────────────────────────────────────────────────────────

	def _build_message(
		self,
		cliente: ClientConfig,
		pdf_path: Path,
		mes: int,
		anio: int,
	) -> MIMEMultipart:
		"""Build a MIME multipart message with PDF attachment."""
		msg = MIMEMultipart()
		msg['From'] = self.smtp.from_addr
		msg['To'] = cliente.email
		msg['Subject'] = f'Calendario Fiscal {MESES_ES[mes]} {anio} - {cliente.nombre}'
		msg['Reply-To'] = self.smtp.from_addr

		# Body
		body = self._build_body(cliente.nombre, mes, anio)
		msg.attach(MIMEText(body, 'plain', 'utf-8'))

		# PDF attachment
		if pdf_path.exists():
			with open(pdf_path, 'rb') as f:
				part = MIMEApplication(f.read(), _subtype='pdf')
				part.add_header(
					'Content-Disposition',
					'attachment',
					filename=pdf_path.name,
				)
				msg.attach(part)
		else:
			logger.warning('PDF no encontrado: %s — enviando sin adjunto', pdf_path)

		return msg

	def _build_body(self, nombre: str, mes: int, anio: int) -> str:
		"""Build plain-text email body."""
		return (
			f'Hola,\n\n'
			f'Adjuntamos el Calendario Fiscal de {MESES_ES[mes]} {anio} '
			f'correspondiente a {nombre}.\n\n'
			f'Recordá revisar las fechas de vencimiento y los importes '
			f'en el portal de ARCA.\n\n'
			f'Saludos cordiales,\n'
			f'Estudio Contable'
		)

	def _send(self, msg: MIMEMultipart) -> None:
		"""Send the message via SMTP.

		Port 465 → SSL directo (SMTP_SSL).
		Port 587 → STARTTLS (SMTP + starttls).
		"""
		if self.smtp.port == 465:
			with smtplib.SMTP_SSL(self.smtp.host, self.smtp.port, timeout=30) as server:
				server.login(self.smtp.user, self.smtp.password)
				server.sendmail(
					self.smtp.from_addr,
					[msg['To']],
					msg.as_string(),
				)
		else:
			with smtplib.SMTP(self.smtp.host, self.smtp.port, timeout=30) as server:
				server.starttls()
				server.login(self.smtp.user, self.smtp.password)
				server.sendmail(
					self.smtp.from_addr,
					[msg['To']],
					msg.as_string(),
				)
