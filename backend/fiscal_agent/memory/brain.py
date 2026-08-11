"""TenantBrain — agrega todas las fuentes fiscales de un CUIT en un TenantContext.

Best-effort semantics: cada fuente se consulta secuencialmente con try/except.
Si una fuente falla, se setea a ``None``/``[]`` y se continúa con la siguiente.
El primer error se captura en ``ultimo_error``.

Typical usage::

        brain = TenantBrain(client)
        context = brain.build_context('20324837796')
"""

from __future__ import annotations

import logging
import unicodedata
from typing import Any

from fiscal_agent.memory.client import FiscalMemoryClient
from fiscal_agent.memory.models import TenantContext
from fiscal_agent.models import ImpuestoInscripto, RegistroImpuesto, RentasCordobaMatching

logger = logging.getLogger(__name__)

#: idImpuesto del padrón que corresponden a IIBB — copiado de
#: ``fiscal_agent.matching._IIBB_IDS`` para mantener el refactor autocontenido.
_IIBB_IDS: set[int] = {5904, 5902, 5905, 5906, 215}


def _normalize(text: str) -> str:
	"""Normaliza el texto: uppercase + remueve acentos para matching robusto."""
	text = text.upper()
	nfkd = unicodedata.normalize('NFKD', text)
	return nfkd.encode('ASCII', 'ignore').decode('ASCII')


class TenantBrain:
	"""Brain que construye un ``TenantContext`` agregando fuentes fiscales.

	Args:
		client: Instancia de ``FiscalMemoryClient`` para leer observaciones.
	"""

	def __init__(self, client: FiscalMemoryClient) -> None:
		self._client = client

	def build_context(self, cuit: str) -> TenantContext:
		"""Construye el contexto fiscal completo de *cuit*.

		Ejecuta 8 pasos secuenciales, cada uno con **best-effort**:
		si una fuente falla, se registra el error y se continúa.

		Args:
			cuit: CUIT del contribuyente.

		Returns:
			TenantContext con todos los campos poblados (parcialmente si hubo errores).
		"""
		ctx = TenantContext()
		ultimo_error: dict | None = None

		# ── 1. Padrón A5 ───────────────────────────────────────────────
		try:
			padron_data = self._client.get_padron_history(cuit)
			ctx.padron = padron_data
		except Exception as exc:
			logger.warning('[brain] Padrón falló para CUIT %s: %s', cuit, exc)
			ctx.padron = None
			ultimo_error = {'source': 'padron', 'error': str(exc)}

		# ── 2. Deuda ────────────────────────────────────────────────────
		try:
			ctx.deuda = self._client.get_extraction_history(cuit, 'deuda')
		except Exception as exc:
			logger.warning('[brain] Deuda falló para CUIT %s: %s', cuit, exc)
			ctx.deuda = []
			if ultimo_error is None:
				ultimo_error = {'source': 'deuda', 'error': str(exc)}

		# ── 3. Facilidades ─────────────────────────────────────────────
		try:
			ctx.facilidades = self._client.get_extraction_history(cuit, 'facilidades')
		except Exception as exc:
			logger.warning('[brain] Facilidades falló para CUIT %s: %s', cuit, exc)
			ctx.facilidades = []
			if ultimo_error is None:
				ultimo_error = {'source': 'facilidades', 'error': str(exc)}

		# ── 4. Registro tributario ─────────────────────────────────────
		try:
			registro_data = self._client.get_extraction_history(cuit, 'registro')
			ctx.registro = registro_data
		except Exception as exc:
			logger.warning('[brain] Registro falló para CUIT %s: %s', cuit, exc)
			ctx.registro = None
			if ultimo_error is None:
				ultimo_error = {'source': 'registro', 'error': str(exc)}

		# ── 5. Calendario fiscal ───────────────────────────────────────
		try:
			from fiscal_agent.rules_engine import RulesEngine

			engine = RulesEngine()
			# Nota: el calendario necesita datos del padrón. Si padron falló,
			# RulesEngine.calcular() puede fallar internamente — se captura aquí.
			ctx.calendario = None
			if ctx.padron:
				# Intentar calcular con el primer resultado del padron
				padron_obs = ctx.padron[0] if isinstance(ctx.padron, list) and ctx.padron else None
				if padron_obs:
					# pylint: disable=protected-access
					ctx.calendario = engine.calcular(padron_obs, _mes_actual(), _anio_actual())
		except Exception as exc:
			logger.warning('[brain] Calendario falló para CUIT %s: %s', cuit, exc)
			ctx.calendario = None
			if ultimo_error is None:
				ultimo_error = {'source': 'calendario', 'error': str(exc)}

		# ── 6. Rentas Córdoba matching ────────────────────────────────
		try:
			impuestos_ws = _extraer_impuestos_ws(ctx.padron)
			registro_impuestos = _extraer_registro_impuestos(ctx.registro)
			ctx.rentas_matching = self._match_rentas(
				provincias=None,
				impuestos_ws=impuestos_ws,
				registro_impuestos=registro_impuestos,
			)
		except Exception as exc:
			logger.warning('[brain] Rentas matching falló para CUIT %s: %s', cuit, exc)
			ctx.rentas_matching = None
			if ultimo_error is None:
				ultimo_error = {'source': 'rentas_matching', 'error': str(exc)}

		# ── 7. Memoria histórica (pipeline completo) ───────────────────
		try:
			ctx.memoria_historica = self._client.get_pipeline_history(cuit, limit=20)
		except Exception as exc:
			logger.warning('[brain] Memoria histórica falló para CUIT %s: %s', cuit, exc)
			ctx.memoria_historica = []
			if ultimo_error is None:
				ultimo_error = {'source': 'memoria_historica', 'error': str(exc)}

		# ── 8. Resumen ejecutivo ───────────────────────────────────────
		ctx.resumen_ejecutivo = self._generar_resumen(cuit, ctx)
		ctx.ultimo_error = ultimo_error

		return ctx

	def _match_rentas(
		self,
		provincias: list[str] | None = None,
		impuestos_ws: list[ImpuestoInscripto] | None = None,
		registro_impuestos: list[RegistroImpuesto] | None = None,
	) -> RentasCordobaMatching:
		"""Evalúa si un contribuyente requiere integración con Rentas Córdoba.

		Refactor de ``fiscal_agent.matching.evaluar_rentas_cordoba()`` como
		método interno del brain. Tiene la **misma firma y lógica** que la
		función original — el thin wrapper en ``matching.py`` delega aquí.

		Args:
			provincias: Provincias configuradas del cliente (``ClientConfig.provincias``).
			impuestos_ws: Impuestos del Padrón A5 (``list[ImpuestoInscripto]``).
			registro_impuestos: Impuestos del RegistroOutput (``list[RegistroImpuesto]``).

		Returns:
			RentasCordobaMatching con campos evaluados.
		"""
		# ── Convenio Multilateral check ───────────────────────────────
		tiene_convenio: bool = False
		if provincias is not None and len(provincias) >= 2 and impuestos_ws is not None:
			tiene_convenio = any(imp.idImpuesto is not None and imp.idImpuesto in _IIBB_IDS for imp in impuestos_ws)

		# ── IIBB Córdoba check ────────────────────────────────────────
		tiene_iibb_cordoba: bool | None = None
		if registro_impuestos is not None and len(registro_impuestos) > 0:
			tiene_iibb_cordoba = any('CORDOBA' in _normalize(imp.impuesto or '') for imp in registro_impuestos)

		# ── Resultado ─────────────────────────────────────────────────
		requiere_integracion = tiene_convenio and (tiene_iibb_cordoba is True)

		if requiere_integracion:
			estado = 'pendiente'
			observacion = (
				'Contribuyente con Convenio Multilateral IIBB y registro en '
				'IIBB Córdoba. La integración con Rentas Córdoba está en desarrollo.'
			)
		elif tiene_iibb_cordoba is None:
			estado = 'sin_datos'
			observacion = (
				'No se pudo evaluar la necesidad de integración con Rentas Córdoba (faltan datos de registro tributario).'
			)
		else:
			estado = 'no_requerido'
			observacion = ''

		return RentasCordobaMatching(
			requiere_integracion=requiere_integracion,
			tiene_convenio_multilateral=tiene_convenio,
			tiene_iibb_cordoba=tiene_iibb_cordoba,
			estado=estado,
			observacion=observacion,
		)

	@staticmethod
	def _generar_resumen(cuit: str, ctx: TenantContext) -> str:
		"""Genera un resumen ejecutivo en texto plano del contexto fiscal."""
		partes: list[str] = [f'Contexto fiscal para CUIT {cuit}']
		partes.append('')

		if ctx.padron:
			partes.append('✓ Padrón A5 consultado')
		else:
			partes.append('✗ Padrón A5 no disponible')

		partes.append(f'  - Deuda: {len(ctx.deuda)} registros')
		partes.append(f'  - Facilidades: {len(ctx.facilidades)} planes')
		partes.append(f'  - Registro: {"disponible" if ctx.registro else "no disponible"}')
		partes.append(f'  - Calendario: {"calculado" if ctx.calendario else "no disponible"}')

		if ctx.rentas_matching:
			rm = ctx.rentas_matching
			if isinstance(rm, dict):
				estado_rentas = rm.get('estado', 'desconocido')
			else:
				estado_rentas = getattr(rm, 'estado', 'desconocido')
			partes.append(f'  - Rentas Córdoba: {estado_rentas}')

		partes.append(f'  - Memoria histórica: {len(ctx.memoria_historica)} eventos')

		if ctx.ultimo_error:
			partes.append(f'  - ⚠ Último error: {ctx.ultimo_error.get("source")}: {ctx.ultimo_error.get("error")}')

		return '\n'.join(partes)


# ── Helper functions (extracción de datos de observaciones) ──────────────────


def _extraer_impuestos_ws(padron: Any) -> list[ImpuestoInscripto] | None:
	"""Extrae ``list[ImpuestoInscripto]`` de la observación del padrón.

	La observación tiene ``content`` en formato Markdown con un JSON
	embebido. Se intenta parsear el JSON del campo ``data``.

	Args:
		padron: ``list[dict]`` de observaciones del padrón o ``None``.

	Returns:
		Lista de ``ImpuestoInscripto`` o ``None`` si no se puede extraer.
	"""
	if not padron:
		return None
	if not isinstance(padron, list) or len(padron) == 0:
		return None

	obs = padron[0]
	content = obs.get('content', '') if isinstance(obs, dict) else ''
	if not content:
		return None

	# Parsear el JSON del content
	import json
	import re

	# Buscar el JSON data dentro del content Markdown
	match = re.search(r'\*\*Data\*\*: (.+?)(?:\n|$)', content)
	if not match:
		return None

	try:
		data = json.loads(match.group(1))
	except (json.JSONDecodeError, ValueError):
		return None

	# Intentar extraer regimenGeneral.impuestos
	regimen = data.get('regimenGeneral', {}) if isinstance(data, dict) else {}
	impuestos_data = regimen.get('impuestos', []) if isinstance(regimen, dict) else []
	if not impuestos_data:
		return None

	return [ImpuestoInscripto(**imp) for imp in impuestos_data if isinstance(imp, dict)]


def _extraer_registro_impuestos(registro: Any) -> list[RegistroImpuesto] | None:
	"""Extrae ``list[RegistroImpuesto]`` de la observación del registro.

	Args:
		registro: ``list[dict]`` de observaciones del registro o ``None``.

	Returns:
		Lista de ``RegistroImpuesto`` o ``None`` si no se puede extraer.
	"""
	if not registro:
		return None
	if not isinstance(registro, list) or len(registro) == 0:
		return None

	obs = registro[0]
	content = obs.get('content', '') if isinstance(obs, dict) else ''
	if not content:
		return None

	import json
	import re

	match = re.search(r'\*\*Data\*\*: (.+?)(?:\n|$)', content)
	if not match:
		return None

	try:
		data = json.loads(match.group(1))
	except (json.JSONDecodeError, ValueError):
		return None

	impuestos_data = data.get('impuestos', []) if isinstance(data, dict) else []
	if not impuestos_data:
		return None

	return [RegistroImpuesto(**imp) for imp in impuestos_data if isinstance(imp, dict)]


def _mes_actual() -> int:
	"""Retorna el mes actual (1-12). Separado para facilitar testing."""
	from datetime import datetime

	return datetime.now().month


def _anio_actual() -> int:
	"""Retorna el año actual. Separado para facilitar testing."""
	from datetime import datetime

	return datetime.now().year
