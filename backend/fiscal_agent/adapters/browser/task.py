"""BrowserTask hierarchy — atomic navigation operations for Composio Browser Tool.

Each BrowserTask is a standalone navigation operation (login, extract, etc.)
that shares a Composio session via session_id. The orchestrator iterates
tasks sequentially, reusing the same session across multiple tasks.
"""

from __future__ import annotations

import json
import logging
from abc import abstractmethod
from dataclasses import field

from fiscal_agent.adapters.tasks.base import BaseTask, TaskResult
from typing import Any, Optional

from fiscal_agent.adapters.browser.iibb_router import IIBBRouter
from fiscal_agent.adapters.browser.workflows import TEMPLATE_FACILIDADES, TEMPLATE_FULL, TEMPLATE_LOGIN, TEMPLATE_REGISTRO

logger = logging.getLogger(__name__)


# ── Parse helpers (module-level, transplanted from ComposioBrowser static methods) ──


def _parse_arca_error(data: str) -> Optional[str]:
	"""Detecta errores ARCA-4 y ARCA-6 en texto de respuesta.

	Busca patrones conocidos en el output del AI agent (insensible a
	mayúsculas/minúsculas). Si el AI agent reportó el error en el template,
	o si el texto contiene indicadores de error, lo detecta acá.

	Args:
		data: Texto de output del AI agent (de WatchTask response).

	Returns:
		Código de error (``'ARCA-4'``, ``'ARCA-6'``) o ``None`` si no hay error.
	"""
	if not data:
		return None

	data_lower = data.lower()

	arca_4_patterns = [
		'arca-4',
		'arca_4',
		'error arca-4',
		'error arca_4',
		'credencial',
		'credenciales inválidas',
		'credenciales invalidas',
		'cuit incorrecto',
		'clave incorrecta',
		'clave fiscal incorrecta',
		'usuario y/o clave incorrectos',
		'invalid credentials',
		'login failed',
	]
	arca_6_patterns = [
		'arca-6',
		'arca_6',
		'error arca-6',
		'error arca_6',
		'2fa',
		'doble factor',
		'two-factor',
		'mfa',
		'código de verificación',
		'codigo de verificacion',
		'token',
		'autenticacion de dos',
		'autenticación de dos',
		'verification code',
	]

	for pattern in arca_4_patterns:
		if pattern in data_lower:
			logger.error('ARCA-4 detected (pattern: %s)', pattern)
			return 'ARCA-4'

	for pattern in arca_6_patterns:
		if pattern in data_lower:
			logger.error('ARCA-6 detected (pattern: %s)', pattern)
			return 'ARCA-6'

	return None


def _parse_extract_output(data: str) -> dict[str, Any]:
	"""Parsea el JSON de extract devuelto por el AI agent.

	Busca un bloque JSON válido en el texto de respuesta. El agente debería
	devolver JSON puro, pero por las dudas busca el primer bloque JSON
	con un algorithm de brace-matching.

	Returns:
		Dict con ``deuda_actual``, ``saldos``, ``plan_pagos``.
		Si no puede parsear, retorna dict vacío con ``_raw`` truncado.
	"""
	if not data or not data.strip():
		return {'deuda_actual': None, 'saldos': [], 'plan_pagos': None}

	# 1. Intentar parsear todo el data como JSON directo
	try:
		return json.loads(data)
	except (json.JSONDecodeError, ValueError):
		pass

	# 2. Desescapar \" → " (doble serialización de Composio: el AI agent
	#    devuelve JSON string dentro de done({text: ...}) y Composio
	#    lo serializa otra vez en la respuesta HTTP)
	try:
		cleaned = data.replace('\\"', '"')
		return json.loads(cleaned)
	except (json.JSONDecodeError, ValueError):
		pass

	# 3. Brace-matching para JSON anidado o con texto alrededor
	brace_depth = 0
	start = -1
	for i, ch in enumerate(data):
		if ch == '{':
			if start == -1:
				start = i
			brace_depth += 1
		elif ch == '}':
			brace_depth -= 1
			if brace_depth == 0 and start != -1:
				try:
					return json.loads(data[start : i + 1])
				except (json.JSONDecodeError, ValueError):
					start = -1

	logger.warning('Could not parse extract output as JSON')
	return {'deuda_actual': None, 'saldos': [], 'plan_pagos': None, '_raw': data[:500]}


# ── TaskResult ────────────────────────────────────────────────────────────────


# ── BrowserTask hierarchy ────────────────────────────────────────────────────


class BrowserTask(BaseTask):
	"""Atomic navigation operation for Composio Browser Tool.

	Each task wraps a Composio NL template with its parameters,
	secrets, and parsing logic. Tasks can share a Composio session
	via session_id when needs_auth=False.
	"""

	name: str = ''
	template: str = ''
	template_params: dict = field(default_factory=dict)
	secrets: Optional[dict] = None
	start_url: Optional[str] = None
	needs_auth: bool = True
	timeout: int = 600

	@abstractmethod
	def parse_output(self, raw: str) -> dict:
		"""Parse raw AI agent output into structured data."""
		...


class VencimientosDeudasTask(BrowserTask):
	"""Vencimientos + deudas: login + switch representado + extract deuda.

	Combined task for backward compatibility — same as the original
	single-task _run_single() pipeline. Antes llamado ``FullTask``.
	"""

	name = 'full'
	template = TEMPLATE_FULL
	needs_auth = True
	timeout = 600

	def __init__(self, cuit: str, clave: str, cliente_cuit: str) -> None:
		self.template_params = {
			'cuit': cuit,
			'clave': clave,
			'cliente_cuit': cliente_cuit,
		}
		self.secrets = {
			'auth.afip.gob.ar': f'{cuit}:{clave}',
		}
		self.start_url = 'https://auth.afip.gob.ar/contribuyente_/login.xhtml'

	def parse_output(self, raw: str) -> dict:
		return _parse_extract_output(raw)


class LoginTask(BrowserTask):
	"""ARCA login only — detecta ARCA-4 y ARCA-6.

	Task rápida (timeout=30s) que solo autentica. Produce
	parsed_data vacío si login OK, o arca_error si falla.
	"""

	name = 'login'
	template = TEMPLATE_LOGIN
	needs_auth = True
	timeout = 30
	start_url = 'https://auth.afip.gob.ar/contribuyente_/login.xhtml'

	def __init__(self, cuit: str, clave: str) -> None:
		self.template_params = {
			'cuit': cuit,
			'clave': clave,
		}
		self.secrets = {
			'auth.afip.gob.ar': f'{cuit}:{clave}',
		}

	def parse_output(self, raw: str) -> dict:
		error = _parse_arca_error(raw)
		if error:
			return {'arca_error': error}
		return {}


class ExtractV2Task(BrowserTask):
	"""Extract deuda from ctacte.cloud — reuse session.

	Assumes session is already authenticated (session_id passed
	from a prior LoginTask). Does NOT set secrets or start_url.
	"""

	name = 'extract_v2'
	template = TEMPLATE_FULL
	needs_auth = False
	timeout = 600

	def __init__(self, cuit: str, clave: str, cliente_cuit: str) -> None:
		self.template_params = {
			'cuit': cuit,
			'clave': clave,
			'cliente_cuit': cliente_cuit,
		}

	def parse_output(self, raw: str) -> dict:
		return _parse_extract_output(raw)


def _parse_facilidades_output(data: str) -> dict:
	"""Parsea el JSON de planes de pago devuelto por el AI agent.

	Busca un bloque JSON válido con key ``planes`` en el texto de respuesta.
	Igual que ``_parse_extract_output`` pero espera estructura de Mis Facilidades.

	Returns:
		Dict con ``planes`` (lista de planes).
		Si no puede parsear, retorna ``{'planes': []}``.
	"""
	if not data or not data.strip():
		return {'planes': []}

	# Limpiar wrapping de triple quotes (el agente a veces envuelve el JSON en """...""")
	cleaned = data.strip()
	if cleaned.startswith('"""') and cleaned.endswith('"""'):
		cleaned = cleaned[3:-3].strip()
	elif cleaned.startswith('"') and cleaned.endswith('"') and cleaned.count('"') == 2:
		# JSON envuelto en comillas simples: "{...}"
		import ast

		try:
			cleaned = ast.literal_eval(cleaned)
		except Exception:
			pass

	for parse_try in [
		lambda d: json.loads(d),
		lambda d: json.loads(d.replace('\\"', '"')),
		lambda d: json.loads(cleaned),
		lambda d: json.loads(cleaned.replace('\\"', '"')),
	]:
		try:
			result = parse_try(data)
			if isinstance(result, dict) and 'planes' in result:
				return result
		except (json.JSONDecodeError, ValueError):
			pass

	# Brace-matching
	brace_depth = 0
	start = -1
	for i, ch in enumerate(data):
		if ch == '{':
			if start == -1:
				start = i
			brace_depth += 1
		elif ch == '}':
			brace_depth -= 1
			if brace_depth == 0 and start != -1:
				try:
					result = json.loads(data[start : i + 1])
					if isinstance(result, dict) and 'planes' in result:
						return result
				except (json.JSONDecodeError, ValueError):
					start = -1

	logger.warning('Could not parse facilidades output as JSON')
	return {'planes': []}


class FacilidadesTask(BrowserTask):
	"""Extrae planes de pago de Mis Facilidades ARCA.

	Hace login propio (needs_auth=True) o puede reusar sesión existente.
	Usa TEMPLATE_FACILIDADES con filtro: vigentes siempre, caducos
	solo si <12 meses desde fin estimado.
	"""

	name = 'facilidades'
	template = TEMPLATE_FACILIDADES
	needs_auth = True
	timeout = 900
	start_url = 'https://auth.afip.gob.ar/contribuyente_/login.xhtml'

	def __init__(self, cuit: str, clave: str, cliente_cuit: str) -> None:
		self.template_params = {
			'cuit': cuit,
			'clave': clave,
			'cliente_cuit': cliente_cuit,
		}
		self.secrets = {
			'auth.afip.gob.ar': f'{cuit}:{clave}',
		}

	def parse_output(self, raw: str) -> dict:
		return _parse_facilidades_output(raw)


def _parse_registro_output(data: str) -> dict:
	"""Parsea el JSON de registro tributario devuelto por el AI agent.

	Busca un bloque JSON válido con keys del RUT:
	``domicilios``, ``actividades``, ``impuestos``, ``puntos_de_venta``.

	Returns:
		Dict completo con ``domicilios``, ``jurisdiccion``, ``actividades``,
		``impuestos``, ``puntos_de_venta``.
	"""
	if not data or not data.strip():
		return {
			'domicilios': [],
			'jurisdiccion': None,
			'actividades': [],
			'impuestos': [],
			'puntos_de_venta': [],
			'iibb_jurisdicciones': [],
		}

	_keys = ('domicilios', 'actividades', 'impuestos', 'puntos_de_venta', 'iibb_jurisdicciones')

	for parse_try in [
		lambda d: json.loads(d),
		lambda d: json.loads(d.replace('\\"', '"')),
	]:
		try:
			result = parse_try(data)
			if isinstance(result, dict) and any(k in result for k in _keys):
				return result
		except (json.JSONDecodeError, ValueError):
			pass

	# Brace-matching
	brace_depth = 0
	start = -1
	for i, ch in enumerate(data):
		if ch == '{':
			if start == -1:
				start = i
			brace_depth += 1
		elif ch == '}':
			brace_depth -= 1
			if brace_depth == 0 and start != -1:
				try:
					result = json.loads(data[start : i + 1])
					if isinstance(result, dict) and any(k in result for k in _keys):
						return result
				except (json.JSONDecodeError, ValueError):
					start = -1

	logger.warning('Could not parse registro output as JSON')
	return {
		'domicilios': [],
		'jurisdiccion': None,
		'actividades': [],
		'impuestos': [],
		'puntos_de_venta': [],
		'iibb_jurisdicciones': [],
	}


def _parse_iibb_output(data: str) -> dict:
	"""Parsea el JSON de IIBB jurisdicciones + cuotas vencidas devuelto por el AI agent.

	Busca un bloque JSON válido con keys ``iibb_jurisdicciones`` o ``cuotas_vencidas``.

	Returns:
		Dict con ``iibb_jurisdicciones`` y ``cuotas_vencidas``.
	"""
	if not data or not data.strip():
		return {'iibb_jurisdicciones': [], 'cuotas_vencidas': []}

	_IIBB_KEYS = ('iibb_jurisdicciones', 'cuotas_vencidas')

	for parse_try in [
		lambda d: json.loads(d),
		lambda d: json.loads(d.replace('\\"', '"')),
	]:
		try:
			result = parse_try(data)
			if isinstance(result, dict) and any(k in result for k in _IIBB_KEYS):
				return result
		except (json.JSONDecodeError, ValueError):
			pass

	# Brace-matching
	brace_depth = 0
	start = -1
	for i, ch in enumerate(data):
		if ch == '{':
			if start == -1:
				start = i
			brace_depth += 1
		elif ch == '}':
			brace_depth -= 1
			if brace_depth == 0 and start != -1:
				try:
					result = json.loads(data[start : i + 1])
					if isinstance(result, dict) and any(k in result for k in _IIBB_KEYS):
						return result
				except (json.JSONDecodeError, ValueError):
					start = -1

	logger.warning('Could not parse IIBB output as JSON')
	return {'iibb_jurisdicciones': [], 'cuotas_vencidas': []}


class RegistroTask(BrowserTask):
	"""Extrae registro tributario (RUT) desde ARCA.

	Navegación: login → Sistema Registral → RUT → extraer domicilios,
	actividades, impuestos, puntos de venta.

	El AI agent devuelve JSON con keys: domicilios[], jurisdiccion?,
	actividades[], impuestos[], puntos_de_venta[].
	"""

	name = 'registro'
	template = TEMPLATE_REGISTRO
	needs_auth = True
	timeout = 600
	start_url = 'https://auth.afip.gob.ar/contribuyente_/login.xhtml'

	def __init__(self, cuit: str, clave: str, cliente_cuit: str) -> None:
		self.template_params = {
			'cuit': cuit,
			'clave': clave,
			'cliente_cuit': cliente_cuit,
		}
		self.secrets = {
			'auth.afip.gob.ar': f'{cuit}:{clave}',
		}

	def parse_output(self, raw: str) -> dict:
		return _parse_registro_output(raw)


class IIBBTask(BrowserTask):
	"""Extrae jurisdicciones IIBB desde el RUT de ARCA.

	Navegación: login → Sistema Registral → RUT → sección IIBB →
	extraer TODAS las provincias con inscripción, estado y fechas.

	El AI agent devuelve JSON con key: iibb_jurisdicciones[].
	"""

	name = 'iibb'
	# template resolved per-instance via IIBBRouter
	needs_auth = True
	timeout = 600
	start_url = 'https://auth.afip.gob.ar/contribuyente_/login.xhtml'

	def __init__(self, cuit: str, clave: str, cliente_cuit: str, provincia: str = 'CORDOBA') -> None:
		self.template_params = {
			'cuit': cuit,
			'clave': clave,
			'cliente_cuit': cliente_cuit,
		}
		self.secrets = {
			'auth.afip.gob.ar': f'{cuit}:{clave}',
		}
		self.template = IIBBRouter.get(provincia)

	def parse_output(self, raw: str) -> dict:
		return _parse_iibb_output(raw)
