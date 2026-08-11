"""Rules Engine — fuente PRIMARIA del calendario fiscal.

Consume ``PadronA5Output`` de la WS API (no browser-use) y genera
``RulesOutput`` con vencimientos ordenados por fecha, aplicando:

- Tablas AFIP de vencimientos por CUIT terminación y tipo de impuesto
- Feriados argentinos (desde ``feriados.csv``)
- Próximo día hábil si la fecha cae en fin de semana o feriado
- Mapping de ``idImpuesto`` del padrón a obligaciones del calendario

Sin LLM, sin browser-use. Reglas literales determinísticas.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set

from fiscal_agent.models import (
	CalendarioAFIP,
	ObligacionCalendario,
	PadronA5Output,
	RulesOutput,
	Vencimiento,
)

_HERE = Path(__file__).parent


# ─── Mapeo de impuestos WS API → claves del calendario AFIP ────────────────

#: idImpuesto del padrón → lista de obligation keys que aplican
_IMPUESTO_TO_OBLIGACION: dict[int, list[str]] = {
	30: ['iva_ddjj'],  # IVA
	10: ['ganancias_sociedades', 'anticipos_ganancias', 'gcias_bienes'],  # Ganancias
	211: ['gcias_bienes'],  # BP-Acciones o Participaciones (Bienes Personales)
	# IIBB — se agrega convenio_multilateral si aplica (ver _obligaciones_para_contribuyente)
	5904: ['_iibb'],  # REG. GENERAL IIBB CORDOBA
	5902: ['_iibb'],  # REG. GENERAL IIBB CABA
	5905: ['_iibb'],  # REG. GENERAL IIBB BUENOS AIRES
	5906: ['_iibb'],  # REG. GENERAL IIBB SANTA FE
	215: ['_iibb'],  # IIBB ACCIONES O PARTICIPACIONES (otra variante)
	# Pendiente de identificar códigos para:
	# - empleadores_sicoss (seguridad social)
	# - internos_ddjj (impuestos internos)
	# - personal_casas (personal doméstico)
}

#: Obligaciones que aplican a todo responsable inscripto con actividad
_OBLIGACIONES_RI_SIEMPRE: list[str] = [
	'ret_perc_sicore_sire',
]

#: Obligaciones aplicables cuando el contribuyente tiene empleados en relación
#: de dependencia. Por ahora no tenemos un idImpuesto específico para detectarlo
#: desde el padrón, así que se incluyen condicionalmente.
_OBLIGACIONES_EMPLEADORES: list[str] = [
	'empleadores_sicoss',
	'personal_casas',
]


class RulesEngine:
	"""Motor de reglas fiscales.

	Carga ``feriados.csv`` y ``calendario_afip.json`` al iniciar.
	El método principal es :meth:`calcular`, que toma un ``PadronA5Output``
	y produce un ``RulesOutput`` con los vencimientos del mes.

	Usage::

	        engine = RulesEngine()
	        output = engine.calcular(padron, mes=6, anio=2026)
	"""

	def __init__(
		self,
		feriados_path: Optional[Path] = None,
		calendario_path: Optional[Path] = None,
	):
		self.feriados: Set[date] = self._cargar_feriados(
			feriados_path or (_HERE / 'feriados.csv'),
		)
		self.calendario: CalendarioAFIP = self._cargar_calendario(
			calendario_path or (_HERE / 'calendario_afip.json'),
		)
		# Lookup plano desde por_tipo (busca en todos los tipos)
		self._obligaciones_flat: Dict[str, ObligacionCalendario] = {}
		for tipo_obl in self.calendario.por_tipo.values():
			self._obligaciones_flat.update(tipo_obl)

	# ── Carga de datos ────────────────────────────────────────────────────

	@staticmethod
	def _cargar_feriados(path: Path) -> Set[date]:
		"""Cargar feriados desde CSV y devolver un set de ``date``.

		Formato esperado::

			date,description
			2026-01-01,Año Nuevo
			# comentarios se ignoran

		Si el archivo no existe o está corrupto, retorna set vacío y
		emite un warning (el pipeline continúa sin feriados).
		"""
		feriados: Set[date] = set()
		if not path.exists():
			print(f'  ⚠ RulesEngine: {path.name} no encontrado — sin feriados')
			return feriados

		try:
			with open(path, newline='', encoding='utf-8') as f:
				reader = csv.reader(f)
				for row in reader:
					# Saltar líneas vacías y comentarios
					if not row or row[0].startswith('#'):
						continue
					if len(row) < 1:
						continue
					fecha_str = row[0].strip()
					if not fecha_str:
						continue
					try:
						feriados.add(date.fromisoformat(fecha_str))
					except (ValueError, TypeError):
						# Línea malformada — se ignora
						continue
		except (OSError, csv.Error) as exc:
			print(f'  ⚠ RulesEngine: error leyendo {path.name}: {exc}')
			return set()

		return feriados

	@staticmethod
	def _cargar_calendario(path: Path) -> CalendarioAFIP:
		"""Cargar calendario AFIP desde JSON.

		Si el archivo no existe o está corrupto, levanta FileNotFoundError
		(no se puede generar calendario sin las tablas de vencimientos).
		"""
		if not path.exists():
			raise FileNotFoundError(
				f'Calendario AFIP no encontrado: {path}\nEl rules engine no puede funcionar sin las tablas de vencimientos.',
			)

		with open(path, encoding='utf-8') as f:
			data = json.load(f)

		return CalendarioAFIP(**data)

	# ── Lógica de días hábiles ────────────────────────────────────────────

	def _proximo_habil(self, fecha: date) -> date:
		"""Ajustar *fecha* al próximo día hábil.

		Reglas:
		1. Si es sábado (weekday==5) o domingo (weekday==6) → avanza al lunes.
		2. Si es feriado nacional → avanza al día siguiente.
		3. Repite hasta encontrar un día hábil.
		"""
		while fecha.weekday() >= 5 or fecha in self.feriados:
			fecha += timedelta(days=1)
		return fecha

	# ── Determinación de obligaciones aplicables ──────────────────────────

	def _obligaciones_para_contribuyente(
		self,
		padron: PadronA5Output,
		provincias: Optional[List[str]] = None,
	) -> List[str]:
		"""Determinar qué obligaciones del calendario aplican al contribuyente.

		Analiza ``padron.regimenGeneral.impuestos[]``, la presencia de
		monotributo y categorías de autónomo para armar la lista de claves
		del calendario que corresponden al contribuyente.

		Args:
			padron: Datos del contribuyente desde WS API.
			provincias: Provincias donde opera. Si tiene 2+, aplica Convenio Multilateral.
		"""
		obligaciones: List[str] = []
		tiene_iibb = False

		# ── Impuestos del régimen general ────────────────────────────
		impuestos = padron.regimenGeneral.impuestos if padron and padron.regimenGeneral else []
		for imp in impuestos:
			if imp.idImpuesto is not None and imp.idImpuesto in _IMPUESTO_TO_OBLIGACION:
				for key in _IMPUESTO_TO_OBLIGACION[imp.idImpuesto]:
					if key == '_iibb':
						tiene_iibb = True
					elif key not in obligaciones:
						obligaciones.append(key)

		# ── IIBB: Convenio Multilateral vs Local ─────────────────────
		if tiene_iibb:
			nro_provincias = len(provincias) if provincias else 0
			if nro_provincias >= 2:
				if 'convenio_multilateral' not in obligaciones:
					obligaciones.append('convenio_multilateral')
			elif nro_provincias == 1:
				# Una sola provincia → IIBB local
				# Por ahora usamos convenio_multilateral como fallback
				# (fechas similares; en el futuro se puede particularizar por provincia)
				if 'convenio_multilateral' not in obligaciones:
					obligaciones.append('convenio_multilateral')
			else:
				# Sin provincias configuradas → convenio como fallback
				if 'convenio_multilateral' not in obligaciones:
					obligaciones.append('convenio_multilateral')

		# ── Monotributo ──────────────────────────────────────────────
		if padron and padron.monotributo is not None:
			if 'monotributo' not in obligaciones:
				obligaciones.append('monotributo')

		# ── Autónomo ─────────────────────────────────────────────────
		if padron and padron.regimenGeneral and padron.regimenGeneral.categoriasAutonomo:
			if 'autonomos' not in obligaciones:
				obligaciones.append('autonomos')

		# ── Obligaciones estándar de RI ──────────────────────────────
		tiene_iva = any(imp.idImpuesto == 30 for imp in impuestos)
		if tiene_iva:
			for key in _OBLIGACIONES_RI_SIEMPRE:
				if key not in obligaciones:
					obligaciones.append(key)

		return obligaciones

	def _observaciones_para_contribuyente(
		self,
		padron: PadronA5Output,
	) -> List[str]:
		"""Detectar obligaciones informativas (sin fecha de pago) desde AFIP.

		Estas se muestran como observaciones en el calendario, no como
		vencimientos con fecha.
		"""
		obs: List[str] = []

		impuestos = padron.regimenGeneral.impuestos if padron and padron.regimenGeneral else []
		regimenes = padron.regimenGeneral.regimenes if padron and padron.regimenGeneral else []

		for imp in impuestos:
			if imp.idImpuesto == 103:
				obs.append('Régimen de Información — presentación obligatoria')

		for reg in regimenes:
			if reg.idRegimen == '68':
				obs.append(
					'Participaciones Societarias (RG 4697) — '
					'vencimiento anual en julio según terminación CUIT: '
					'0-1-2-3 → 28 jul, 4-5-6 → 29 jul, 7-8-9 → 30 jul. '
					'Fuente: RG 4697 (AFIP/ARCA) – Calendario de Vencimientos.'
				)
			elif reg.idRegimen == '255':
				obs.append('Presentación de Estados Contables en formato PDF')

		return obs

	# ── Cálculo de día de vencimiento ─────────────────────────────────────

	def _dia_vencimiento(
		self,
		obligacion_key: str,
		ultimo_digito_cuit: int,
		mes: int,
	) -> int:
		"""Obtener el día de vencimiento para una obligación.

		1. Busca el grupo CUIT que corresponde al dígito terminal.
		2. Retorna el día desde ``obligacion.meses[str(mes)]``.

		Si el mes no está en la tabla, retorna el último día del mes
		como fallback.
		"""
		obligacion = self._obligaciones_flat.get(obligacion_key)
		if not obligacion:
			raise KeyError(
				f'Obligación "{obligacion_key}" no encontrada en el calendario AFIP.',
			)

		mes_str = str(mes)

		# Buscar el día base
		dia = obligacion.meses.get(mes_str)
		if dia is not None:
			return dia

		# Fallback: último día del mes
		print(f'  ⚠ RulesEngine: {obligacion_key} no tiene día para mes {mes}')
		return 28  # fallback conservador

	# ── Generación de conceptos ───────────────────────────────────────────

	@staticmethod
	def _generar_concepto(obligacion: ObligacionCalendario, mes: int, anio: int) -> str:
		"""Generar el nombre del concepto para un vencimiento.

		Sigue la convención de nomenclatura del estudio contable:
		- IVA: "IVA - Período {mes_anterior}/{anio_anterior}"
		- Monotributo: "Monotributo - Cuota Mensual {mes}/{anio}"
		- Ganancias anticipo: "Ganancias - Anticipo {mes}/{anio}"
		- Autónomos: "Autónomos - Cuota {mes}/{anio}"
		- Otros: "{label} - {mes}/{anio}"
		"""
		key = obligacion.key
		if key == 'iva_ddjj':
			mes_anterior = mes - 1 if mes > 1 else 12
			anio_anterior = anio if mes > 1 else anio - 1
			return f'IVA - Período {mes_anterior}/{anio_anterior}'
		elif key == 'monotributo':
			return f'Monotributo - Cuota Mensual {mes}/{anio}'
		elif key == 'anticipos_ganancias':
			return f'Ganancias - Anticipo {mes}/{anio}'
		elif key == 'autonomos':
			return f'Autónomos - Cuota {mes}/{anio}'
		elif key == 'ganancias_sociedades':
			mes_anterior = mes - 1 if mes > 1 else 12
			anio_anterior = anio if mes > 1 else anio - 1
			return f'Ganancias Sociedades - Período {mes_anterior}/{anio_anterior}'
		else:
			return f'{obligacion.label} - {mes}/{anio}'

	# ── Punto de entrada principal ────────────────────────────────────────

	def calcular(
		self,
		padron: PadronA5Output,
		mes: int,
		anio: int,
		provincias: Optional[List[str]] = None,
	) -> RulesOutput:
		"""Calcular vencimientos fiscales para un contribuyente en un mes dado.

		Parameters
		----------
		padron : PadronA5Output
			Datos del contribuyente desde WS API (Padrón A5).
		mes : int
			Mes del calendario (1-12).
		anio : int
			Año del calendario (ej. 2026).
		provincias : list[str] or None
			Provincias donde opera el contribuyente. Usado para determinar
			si aplica Convenio Multilateral (2+ provincias) o IIBB local.

		Returns
		-------
		RulesOutput
			Lista ordenada de vencimientos con fechas ajustadas a día hábil.
		"""
		# ── Obtener CUIT y último dígito ─────────────────────────────
		cuit = ''
		if padron and padron.datosGenerales and padron.datosGenerales.idPersona:
			cuit = padron.datosGenerales.idPersona

		ultimo_digito = 0
		if cuit and cuit[-1].isdigit():
			ultimo_digito = int(cuit[-1])

		# ── Determinar obligaciones aplicables ───────────────────────
		obligacion_keys = self._obligaciones_para_contribuyente(padron, provincias)
		observaciones = self._observaciones_para_contribuyente(padron)

		vencimientos: List[Vencimiento] = []
		feriados_presentes: List[date] = []

		# ── Generar vencimientos ─────────────────────────────────────
		for key in obligacion_keys:
			obligacion = self._obligaciones_flat.get(key)
			if not obligacion:
				print(f'  ⚠ RulesEngine: obligación "{key}" no encontrada en calendario')
				continue

			try:
				dia = self._dia_vencimiento(key, ultimo_digito, mes)
			except KeyError:
				continue

			# Validar que el día sea válido para el mes
			try:
				fecha_base = date(anio, mes, dia)
			except (ValueError, OverflowError):
				print(f'  ⚠ RulesEngine: fecha inválida {anio}-{mes}-{dia} para {key}')
				continue

			# Ajustar a día hábil
			fecha_habil = self._proximo_habil(fecha_base)

			# Recolectar feriados entre la fecha base y la ajustada
			d = fecha_base
			while d <= fecha_habil:
				if d in self.feriados:
					feriados_presentes.append(d)
				d += timedelta(days=1)

			# Generar concepto
			concepto = self._generar_concepto(obligacion, mes, anio)

			vencimientos.append(
				Vencimiento(
					concepto=concepto,
					fecha=fecha_habil,
					es_fecha_habil=(fecha_base == fecha_habil),
				)
			)

		# ── Ordenar por fecha y deduplicar feriados ──────────────────
		vencimientos.sort(key=lambda v: v.fecha)
		feriados_presentes = sorted(set(feriados_presentes))

		periodo = f'{anio}-{mes:02d}'

		return RulesOutput(
			cuit=cuit,
			periodo=periodo,
			vencimientos=vencimientos,
			observaciones=observaciones,
			feriados_presentes=feriados_presentes,
		)


# ─── Helper de alto nivel ───────────────────────────────────────────────────


def calcular_calendario(
	padron: PadronA5Output,
	mes: int,
	anio: int,
	feriados_path: Optional[Path] = None,
	calendario_path: Optional[Path] = None,
) -> RulesOutput:
	"""Crear un RulesEngine y calcular vencimientos en un solo paso."""
	engine = RulesEngine(
		feriados_path=feriados_path,
		calendario_path=calendario_path,
	)
	return engine.calcular(padron, mes, anio)
