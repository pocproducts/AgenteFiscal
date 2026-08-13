"""Shared calendar-email copy — subject/body text, used by every ``EmailSenderPort`` adapter."""

from __future__ import annotations

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


def build_subject(nombre: str, mes: int, anio: int) -> str:
	"""Email subject line for a calendar PDF delivery."""
	return f'Calendario Fiscal {MESES_ES[mes]} {anio} - {nombre}'


def build_body(nombre: str, mes: int, anio: int) -> str:
	"""Plain-text email body for a calendar PDF delivery."""
	return (
		f'Hola,\n\n'
		f'Adjuntamos el Calendario Fiscal de {MESES_ES[mes]} {anio} '
		f'correspondiente a {nombre}.\n\n'
		f'Recordá revisar las fechas de vencimiento y los importes '
		f'en el portal de ARCA.\n\n'
		f'Saludos cordiales,\n'
		f'Estudio Contable'
	)


__all__ = ['MESES_ES', 'build_body', 'build_subject']
