"""ARCA Web Services — consulta de padrón tributario vía WSAA + WS SR Padrón.

Alternativa limpia a pyafipws (incompatible con Python 3.12).
Usa cryptography + requests para autenticación con certificado y SOAP.
"""

from __future__ import annotations

import logging
import os
import pickle
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
from xml.etree import ElementTree as ET

import requests

WSAA_URL = 'https://wsaa.afip.gov.ar/ws/services/LoginCms'
PADRON_A5_URL = 'https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA5'
PADRON_A13_URL = 'https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA13'

# ─── Proxy ARCA ─────────────────────────────────────────────────────────────
# Cuando se ejecuta desde WSL2, ciertos rangos de IP de AFIP/ARCA no son
# accesibles. Configurá ARCA_PROXY_URL para routing via Windows host:
#
#   1. Corré proxy-arca.py en Windows (puerto 8443)
#   2. Seteá ARCA_PROXY_URL=http://host.docker.internal:8443
#
# El proxy HTTP CONNECT tuneliza sólo el tráfico a wsaa.afip.gov.ar
# y aws.afip.gov.ar — el resto del tráfico del backend no se toca.


def _get_arca_proxies() -> dict[str, str] | None:
	"""Return proxies dict for ARCA traffic if ARCA_PROXY_URL is configured.

	Returns ``{'https': proxy_url}`` which routes all HTTPS from the calling
	function through the proxy. Since this is only applied at the call site
	of ``obtener_ta`` and ``consultar_cuit``, other outbound HTTPS (Clerk,
	Redis, Engram, etc.) is not affected.
	"""
	proxy_url = os.environ.get('ARCA_PROXY_URL', '').strip()
	if not proxy_url:
		return None
	return {'https': proxy_url}


NS_SOAP = 'http://schemas.xmlsoap.org/soap/envelope/'
NS_WSU = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd'
NS_PADRON = 'http://a5.soap.ws.server.puc.sr/'


# ─── WSAA: Ticket de Acceso ────────────────────────────────────────────────


def _build_cms_xml(service: str) -> str:
	"""Build the XML to be signed for WSAA authentication.

	Reglas de ARCA:
	- generationTime debe estar en el pasado (5-10 min de diferencia).
	- uniqueId debe ser un entero de 32 bits (sin signo), PERO valores cercanos
	  a 2^31 (como timestamps Unix) son rechazados. Usar un número chico.
	- timezone offset explícito (+00:00), no Z.
	"""
	import time
	from datetime import timedelta, timezone

	now = datetime.now(timezone.utc) - timedelta(minutes=15)  # 15 min en pasado
	exp = now + timedelta(hours=12)
	uid = int(time.time()) % 1_000_000  # uniqueId chico
	fmt = '%Y-%m-%dT%H:%M:%S+00:00'

	return f"""<?xml version="1.0" encoding="UTF-8"?>
<loginTicketRequest version="1.0">
	<header>
		<uniqueId>{uid}</uniqueId>
		<generationTime>{now.strftime(fmt)}</generationTime>
		<expirationTime>{exp.strftime(fmt)}</expirationTime>
	</header>
	<service>{service}</service>
</loginTicketRequest>"""


def _sign_xml_openssl(xml: str, cert_path: str, key_path: str) -> bytes:
	"""Sign XML with certificate using openssl (CMS/PKCS#7)."""
	with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
		f.write(xml)
		xml_path = f.name

	try:
		result = subprocess.run(
			[
				'openssl',
				'smime',
				'-sign',
				'-signer',
				cert_path,
				'-inkey',
				key_path,
				'-outform',
				'DER',
				'-nodetach',
				'-in',
				xml_path,
			],
			capture_output=True,
			check=True,
		)
		return result.stdout
	finally:
		os.unlink(xml_path)


def _build_soap_login(cms_b64: str) -> str:
	"""Build SOAP request for WSAA loginCms."""
	return f'''<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="{NS_SOAP}">
	<SOAP-ENV:Body>
		<loginCms xmlns="http://wsaa.afip.gov.ar/ws/services/LoginCms">
			<in0>{cms_b64}</in0>
		</loginCms>
	</SOAP-ENV:Body>
</SOAP-ENV:Envelope>'''


def _parse_ta_response(xml: str) -> tuple[str, str, datetime]:
	"""Parse WSAA response XML to extract token, sign, and expiration."""
	root = ET.fromstring(xml)

	# Find the loginTicketResponse in the SOAP body
	body = root.find(f'.//{{{NS_SOAP}}}Body')
	if body is None:
		raise ValueError('No SOAP body in response')

	login_response = body.find('.//{http://wsaa.afip.gov.ar/ws/services/LoginCms}loginCmsReturn')
	if login_response is None:
		raise ValueError('No loginCmsReturn in response')

	ta_xml = login_response.text
	ta_root = ET.fromstring(ta_xml)

	token = ta_root.findtext('.//token')
	sign = ta_root.findtext('.//sign')
	exp_str = ta_root.findtext('.//expirationTime')

	if not token or not sign or not exp_str:
		raise ValueError(f'Missing fields in TA: token={token}, sign={sign}, exp={exp_str}')

	expiry = datetime.fromisoformat(exp_str.replace('Z', '+00:00').replace('T', ' '))
	return token, sign, expiry


def obtener_ta(
	service: str,
	cert_path: str,
	key_path: str,
	cache_file: Optional[str] = None,
) -> tuple[str, str]:
	"""Obtener Ticket de Acceso de WSAA, con caché local."""
	if cache_file and os.path.exists(cache_file):
		with open(cache_file, 'rb') as f:
			cached = pickle.load(f)
		if datetime.now(timezone.utc) < cached['expiry']:
			print(f'  ✓ TA vigente (cache) — vence: {cached["expiry"]}')
			return cached['token'], cached['sign']

	print(f'  → Solicitando TA para {service} ...')
	xml = _build_cms_xml(service)
	cms_signed = _sign_xml_openssl(xml, cert_path, key_path)

	import base64

	cms_b64 = base64.b64encode(cms_signed).decode('ascii')
	soap = _build_soap_login(cms_b64)

	resp = requests.post(
		WSAA_URL,
		data=soap.encode('utf-8'),
		headers={
			'Content-Type': 'text/xml;charset=UTF-8',
			'SOAPAction': 'urn:LoginCms',
		},
		timeout=30,
		proxies=_get_arca_proxies(),
	)
	resp.raise_for_status()

	token, sign, expiry = _parse_ta_response(resp.text)

	if cache_file:
		os.makedirs(os.path.dirname(cache_file) or '.', exist_ok=True)
		with open(cache_file, 'wb') as f:
			pickle.dump({'token': token, 'sign': sign, 'expiry': expiry}, f)

	print(f'  ✓ TA obtenido — vence: {expiry}')
	return token, sign


# ─── TA cache compartido (in-memory, 11h TTL) ─────────────────────────────


_ta_cache: dict = {}  # {'token': str, 'sign': str, 'expiry': datetime}
_ta_error_reason: str = ''  # reason for last get_ta() failure


def get_ta_error() -> str:
	"""Return the reason for the last ``get_ta()`` failure."""
	return _ta_error_reason


def get_ta(service: str = 'ws_sr_constancia_inscripcion') -> tuple[Optional[str], Optional[str]]:
	"""Return cached Ticket de Acceso, refreshing if expired.

	In-memory cache con 11h TTL. Compartido por CLI, API y MCP.
	Requiere CERT_PATH y KEY_PATH definidos (tipicamente en config).

	Returns (token, sign) or (None, None) if certs are missing.

	Check ``get_ta_error()`` for a human-readable reason on failure.
	"""
	from agente_fiscal.config import CERT_PATH, KEY_PATH

	global _ta_cache, _ta_error_reason

	now = datetime.now(timezone.utc)

	# Return cached TA if still valid
	if _ta_cache and _ta_cache.get('expiry', now) > now:
		return _ta_cache['token'], _ta_cache['sign']

	# Attempt to obtain a new TA
	if not CERT_PATH.exists() or not KEY_PATH.exists():
		logger.warning('Certificados no encontrados en %s', CERT_PATH.parent)
		_ta_error_reason = 'Certificados X.509 no encontrados en el servidor'
		return None, None

	try:
		token, sign = obtener_ta(service, str(CERT_PATH), str(KEY_PATH))
		_ta_cache = {
			'token': token,
			'sign': sign,
			'expiry': now + timedelta(hours=11),
		}
		_ta_error_reason = ''
		return token, sign
	except requests.exceptions.ConnectTimeout:
		_ta_error_reason = 'ARCA no responde (tiempo de espera agotado) — puede estar temporalmente caído'
		logger.error('Error obteniendo TA: timeout conectando a ARCA')
		return None, None
	except requests.exceptions.ConnectionError:
		_ta_error_reason = 'ARCA no está disponible temporalmente — no se puede establecer conexión'
		logger.error('Error obteniendo TA: no se pudo conectar a ARCA')
		return None, None
	except Exception as exc:
		_ta_error_reason = f'Error de autenticación contra ARCA: {exc}'
		logger.error('Error obteniendo TA: %s', exc)
		return None, None


# ─── WS SR PADRÓN A5: consulta de CUIT ────────────────────────────────────


def _build_padron_soap(cuit_representante: str, token: str, sign: str, cuit_consulta: str) -> str:
	"""Build SOAP request for padrón A5 getPersona.

	Estructura según manual AFIP ws_sr_constancia_inscripcion v3.1 (sección 3.2.1):
	- Namespace: http://a5.soap.ws.server.puc.sr/
	- Método: a5:getPersona
	- Token, sign, cuitRepresentada, idPersona en el Body
	- Header vacío
	"""
	return f'''<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="{NS_SOAP}"
	xmlns:a5="{NS_PADRON}">
	<soapenv:Header/>
	<soapenv:Body>
		<a5:getPersona>
			<token>{token}</token>
			<sign>{sign}</sign>
			<cuitRepresentada>{cuit_representante}</cuitRepresentada>
			<idPersona>{cuit_consulta}</idPersona>
		</a5:getPersona>
	</soapenv:Body>
</soapenv:Envelope>'''


def _ns(tag: str) -> str:
	"""Wrap tag in A5 namespace for ElementTree lookups."""
	return f'{{{NS_PADRON}}}{tag}'


def _parse_int(val: Optional[str]) -> Optional[int]:
	"""Parse string to int, returning None on failure."""
	if val is not None and val.strip():
		try:
			return int(val.strip())
		except (ValueError, TypeError):
			return None
	return None


class PadronA5Result:
	"""Resultado de consulta al padrón A5.

	Parses the full SOAP XML response from ``getPersona`` and exposes
	every field via properties. Backward-compatible with the original
	simplified accessors (``denominacion``, ``estado``, etc.) while
	adding complete structured access to all sections.
	"""

	def __init__(self, xml: str):
		self._raw = xml
		self._root = ET.fromstring(xml)

	# ── Helpers de parsing ──────────────────────────────────────────────

	def _extract(self, *tags: str) -> Optional[str]:
		"""Try multiple XML tag paths in order, return first match.

		Strips whitespace — container elements (e.g. ``<impuesto>`` with
		children) return whitespace-only text which we must reject.
		"""
		for tag in tags:
			elem = self._root.find(f'.//{{{tag}}}' if '{' in tag else f'.//{tag}')
			if elem is not None and elem.text and elem.text.strip():
				return elem.text.strip()
			elem = self._root.find(f'.//{_ns(tag)}')
			if elem is not None and elem.text and elem.text.strip():
				return elem.text.strip()
		return None

	def _find_section(self, section: str) -> Optional[ET.Element]:
		"""Find a named section under ``personaReturn``.

		Tries namespace-qualified and bare lookups to handle
		both Axis SOAP quirks and strict XML.
		"""
		for path in (
			f'.//personaReturn/{_ns(section)}',
			f'.//personaReturn/{section}',
			f'.//{_ns(section)}',
			f'.//{section}',
		):
			elem = self._root.find(path)
			if elem is not None:
				return elem
		return None

	def _child_text(self, parent: ET.Element, tag: str) -> Optional[str]:
		"""Get text content of a child element (namespaced or bare)."""
		elem = parent.find(_ns(tag))
		if elem is not None and elem.text:
			return elem.text.strip()
		elem = parent.find(tag)
		if elem is not None and elem.text:
			return elem.text.strip()
		return None

	@staticmethod
	def _element_to_dict(elem: ET.Element) -> dict:
		"""Flatten an XML element's direct children into a {tag: text} dict."""
		d = {}
		for child in elem:
			key = child.tag.split('}')[-1]  # strip namespace prefix
			d[key] = child.text.strip() if child.text else ''
		return d

	def _parse_repeated(self, parent: ET.Element, tag: str) -> list[dict]:
		"""Parse 0..N child elements into a list of flat dicts."""
		items = []
		for elem in parent.findall(_ns(tag)):
			items.append(self._element_to_dict(elem))
		if not items:
			for elem in parent.findall(tag):
				items.append(self._element_to_dict(elem))
		return items

	def _parse_single_child(self, parent: ET.Element, tag: str) -> Optional[dict]:
		"""Parse an optional single child element into a flat dict."""
		elem = parent.find(_ns(tag))
		if elem is None:
			elem = parent.find(tag)
		if elem is not None:
			return self._element_to_dict(elem)
		return None

	# ── Propiedades originales (backward compat) ───────────────────────

	def raw_xml(self) -> str:
		return self._raw

	@property
	def denominacion(self) -> Optional[str]:
		"""Nombre o razón social. Prueba ``razonSocial`` primero para jurídicas."""
		return self._extract('razonSocial', 'denominacion', 'apellido', 'nombre')

	@property
	def tipo_persona(self) -> Optional[str]:
		"""Tipo de persona: FISICA o JURIDICA (raw desde AFIP)."""
		return self._extract('tipoPersona')

	@property
	def estado(self) -> Optional[str]:
		"""Estado de la clave: ACTIVO, INACTIVO, etc."""
		return self._extract('estadoClave', 'estado')

	@property
	def provincia(self) -> Optional[str]:
		return self._extract('provincia', 'descripcionProvincia')

	@property
	def imp_iva(self) -> Optional[str]:
		return self._extract('impuesto', 'idImpuesto')

	@property
	def monotributo(self) -> Optional[str]:
		return self._extract('monotributo', 'categoriaMonotributo')

	@property
	def mes_cierre(self) -> Optional[str]:
		return self._extract('mesCierre')

	# ── Nuevas propiedades: datosGenerales ─────────────────────────────

	@property
	def apellido(self) -> Optional[str]:
		dg = self._find_section('datosGenerales')
		return self._child_text(dg, 'apellido') if dg is not None else None

	@property
	def nombre(self) -> Optional[str]:
		dg = self._find_section('datosGenerales')
		return self._child_text(dg, 'nombre') if dg is not None else None

	@property
	def razon_social(self) -> Optional[str]:
		dg = self._find_section('datosGenerales')
		return self._child_text(dg, 'razonSocial') if dg is not None else None

	@property
	def id_persona(self) -> Optional[str]:
		"""CUIT de la persona consultada."""
		dg = self._find_section('datosGenerales')
		return self._child_text(dg, 'idPersona') if dg is not None else None

	@property
	def tipo_clave(self) -> Optional[str]:
		"""Tipo de clave: CUIT, CUIL o CDI."""
		dg = self._find_section('datosGenerales')
		return self._child_text(dg, 'tipoClave') if dg is not None else None

	@property
	def estado_clave(self) -> Optional[str]:
		"""Estado de la clave: ACTIVO o INACTIVO."""
		dg = self._find_section('datosGenerales')
		return self._child_text(dg, 'estadoClave') if dg is not None else None

	@property
	def domicilio_fiscal(self) -> Optional[dict]:
		"""Domicilio fiscal como dict plano."""
		dg = self._find_section('datosGenerales')
		if dg is None:
			return None
		return self._parse_single_child(dg, 'domicilioFiscal')

	@property
	def domicilio_fiscal_dict(self) -> dict:
		"""Like ``domicilio_fiscal`` but always returns a dict (empty if absent)."""
		return self.domicilio_fiscal or {}

	@property
	def dependencia(self) -> Optional[dict]:
		"""Dependencia registrada (opcional)."""
		dg = self._find_section('datosGenerales')
		if dg is None:
			return None
		return self._parse_single_child(dg, 'dependencia')

	@property
	def datos_generales_dict(self) -> dict:
		"""All ``datosGenerales`` flat fields as a dict."""
		dg = self._find_section('datosGenerales')
		if dg is None:
			return {}
		return {
			'apellido': self._child_text(dg, 'apellido'),
			'nombre': self._child_text(dg, 'nombre'),
			'razonSocial': self._child_text(dg, 'razonSocial'),
			'idPersona': self._child_text(dg, 'idPersona'),
			'tipoPersona': self._child_text(dg, 'tipoPersona'),
			'tipoClave': self._child_text(dg, 'tipoClave'),
			'estadoClave': self._child_text(dg, 'estadoClave'),
			'mesCierre': self._child_text(dg, 'mesCierre'),
		}

	# ── Nuevas propiedades: datosRegimenGeneral ────────────────────────

	@property
	def actividades(self) -> list[dict]:
		"""Actividades económicas registradas (0..N)."""
		rg = self._find_section('datosRegimenGeneral')
		if rg is None:
			return []
		return self._parse_repeated(rg, 'actividad')

	@property
	def impuestos_rg(self) -> list[dict]:
		"""Impuestos registrados en el régimen general (0..N)."""
		rg = self._find_section('datosRegimenGeneral')
		if rg is None:
			return []
		return self._parse_repeated(rg, 'impuesto')

	@property
	def categorias_autonomo(self) -> list[dict]:
		"""Categorías de autónomo registradas (0..N)."""
		rg = self._find_section('datosRegimenGeneral')
		if rg is None:
			return []
		return self._parse_repeated(rg, 'categoriaAutonomo')

	@property
	def regimenes(self) -> list[dict]:
		"""Regímenes impositivos registrados (0..N)."""
		rg = self._find_section('datosRegimenGeneral')
		if rg is None:
			return []
		return self._parse_repeated(rg, 'regimen')

	# ── Nuevas propiedades: datosMonotributo ───────────────────────────

	@property
	def actividad_monotributo(self) -> Optional[dict]:
		"""Actividad monotributista registrada (0..1)."""
		mt = self._find_section('datosMonotributo')
		if mt is None:
			return None
		return self._parse_single_child(mt, 'actividadMonotributista')

	@property
	def categoria_monotributo(self) -> Optional[dict]:
		"""Categoría de monotributo (0..1)."""
		mt = self._find_section('datosMonotributo')
		if mt is None:
			return None
		return self._parse_single_child(mt, 'categoriaMonotributo')

	@property
	def componentes_sociedad(self) -> list[dict]:
		"""Componentes de sociedad (socios/administradores, 0..N)."""
		mt = self._find_section('datosMonotributo')
		if mt is None:
			return []
		return self._parse_repeated(mt, 'componenteDeSociedad')

	@property
	def impuestos_mt(self) -> list[dict]:
		"""Impuestos del monotributo (0..N)."""
		mt = self._find_section('datosMonotributo')
		if mt is None:
			return []
		return self._parse_repeated(mt, 'impuesto')

	# ── Nuevas propiedades: errores y metadata ─────────────────────────

	@property
	def error_constancia(self) -> Optional[dict]:
		"""Error de constancia (persona no encontrada, baja, etc.)."""
		ec = self._find_section('errorConstancia')
		if ec is None:
			return None
		errors = [e.text or '' for e in ec.findall(_ns('error'))]
		if not errors:
			errors = [e.text or '' for e in ec.findall('error')]
		return {
			'error': errors,
			'idPersona': self._child_text(ec, 'idPersona'),
		}

	@property
	def error_regimen_general(self) -> Optional[dict]:
		"""Error en la sección de régimen general."""
		erg = self._find_section('errorRegimenGeneral')
		if erg is None:
			return None
		return self._element_to_dict(erg)

	@property
	def error_monotributo(self) -> Optional[dict]:
		"""Error en la sección de monotributo."""
		emt = self._find_section('errorMonotributo')
		if emt is None:
			return None
		return self._element_to_dict(emt)

	@property
	def metadata(self) -> Optional[dict]:
		"""Metadatos de la respuesta (fechaHora, servidor)."""
		md = self._find_section('metadata')
		if md is None:
			return None
		return self._element_to_dict(md)

	# ── Lógica de negocio ──────────────────────────────────────────────

	def detectar_tipo(self) -> str:
		"""Inferir tipo de contribuyente desde los datos del padrón.

		Reglas:
		1. Si ``idImpuesto`` == 30 (IVA) en regimen general → ``responsable_inscripto``
		2. Si tiene ``categoriaMonotributo`` no vacía → ``monotributo``
		3. Si tiene ``categoriaAutonomo`` → ``autonomo``
		4. Fallback a la heurística original (tags planas)
		"""
		# 1. IVA (idImpuesto=30) en regimen general
		for imp in self.impuestos_rg:
			if imp.get('idImpuesto') == '30':
				return 'responsable_inscripto'

		# 2. Monotributo
		cat_mt = self.categoria_monotributo
		if cat_mt:
			desc = (cat_mt.get('descripcionCategoria') or '').strip()
			if desc and desc.upper() not in ('NI', ''):
				self._cached_mt_desc = desc
				return 'monotributo'

		# 3. Autónomo
		if self.categorias_autonomo:
			return 'autonomo'

		# 4. Fallback a heurística original
		mt_old = self.monotributo
		iva_old = self.imp_iva
		if iva_old and iva_old in ('30', 'AC', 'AN'):
			return 'responsable_inscripto'
		if mt_old and mt_old not in ('NI', '', None):
			return 'monotributo'
		return 'autonomo'

	# ── Salidas estructuradas ──────────────────────────────────────────

	def to_dict(self) -> dict:
		"""Dict plano con los campos principales (backward compat)."""
		dom = self.domicilio_fiscal_dict
		dg = self.datos_generales_dict
		return {
			# Originales (backward compat)
			'denominacion': self.denominacion or '',
			'tipo_persona': 'juridica' if self.tipo_persona and 'JURIDICA' in self.tipo_persona.upper() else 'fisica',
			'estado': self.estado or '',
			'provincia': self.provincia or '',
			'imp_iva': self.imp_iva or '',
			'monotributo': self.monotributo or '',
			'mes_cierre': int(self.mes_cierre) if self.mes_cierre else 12,
			'tipo': self.detectar_tipo(),
			# Nuevos campos planos
			'apellido': dg.get('apellido') or '',
			'nombre': dg.get('nombre') or '',
			'razon_social': dg.get('razonSocial') or '',
			'cuit': dg.get('idPersona') or '',
			'tipo_clave': dg.get('tipoClave') or '',
			'estado_clave': dg.get('estadoClave') or '',
			'domicilio_fiscal': dom,
			'actividades': self.actividades,
			'impuestos_rg': self.impuestos_rg,
			'categorias_autonomo': self.categorias_autonomo,
			'regimenes': self.regimenes,
			'actividad_monotributo': self.actividad_monotributo or {},
			'categoria_monotributo': self.categoria_monotributo or {},
			'componentes_sociedad': self.componentes_sociedad,
			'impuestos_mt': self.impuestos_mt,
			'error_constancia': self.error_constancia,
			'error_regimen_general': self.error_regimen_general,
			'error_monotributo': self.error_monotributo,
			'metadata': self.metadata or {},
		}

	def to_enriched_dict(self) -> dict:
		"""Dict enriquecido: datos planos + árbol completo bajo ``_full``.

		Conserva los campos planos de ``to_dict()`` y agrega el modelo
		Pydantic serializado completo bajo ``_full``.
		"""
		enriched = self.to_dict()
		enriched['_full'] = self.to_output().model_dump()
		return enriched

	def to_output(self) -> 'PadronA5Output':
		"""Convertir el resultado XML a un modelo Pydantic estructurado.

		Returns
		-------
		PadronA5Output
			Todos los datos parseados con tipos validados.
		"""
		# Import tardío para evitar circular imports
		from agente_fiscal.domain.models import (
			ActividadEconomica,
			CategoriaContribuyente,
			ComponenteSociedad,
			DatosGenerales,
			DatosMonotributo,
			DatosRegimenGeneral,
			Dependencia,
			DomicilioFiscal,
			ErrorConstancia,
			ErrorSeccion,
			ImpuestoInscripto,
			MetadataRespuesta,
			PadronA5Output as OutputModel,
			RegimenInscripto,
		)

		# ── datosGenerales + domicilioFiscal + dependencia ──────
		dg_el = self._find_section('datosGenerales')
		datos_generales: Optional[DatosGenerales] = None
		domicilio_fiscal: Optional[DomicilioFiscal] = None
		dependencia: Optional[Dependencia] = None

		if dg_el is not None:
			datos_generales = DatosGenerales(
				apellido=self._child_text(dg_el, 'apellido'),
				nombre=self._child_text(dg_el, 'nombre'),
				razonSocial=self._child_text(dg_el, 'razonSocial'),
				idPersona=self._child_text(dg_el, 'idPersona'),
				tipoPersona=self._child_text(dg_el, 'tipoPersona'),
				tipoClave=self._child_text(dg_el, 'tipoClave'),
				estadoClave=self._child_text(dg_el, 'estadoClave'),
				mesCierre=_parse_int(self._child_text(dg_el, 'mesCierre')),
			)
			dom_raw = self._parse_single_child(dg_el, 'domicilioFiscal')
			if dom_raw:
				domicilio_fiscal = DomicilioFiscal(**dom_raw)
			dep_raw = self._parse_single_child(dg_el, 'dependencia')
			if dep_raw:
				dependencia = Dependencia(**dep_raw)

		# ── datosRegimenGeneral ─────────────────────────────────
		rg_el = self._find_section('datosRegimenGeneral')
		regimen_general: Optional[DatosRegimenGeneral] = None
		if rg_el is not None:
			regimen_general = DatosRegimenGeneral(
				actividades=[ActividadEconomica(**a) for a in self._parse_repeated(rg_el, 'actividad')],
				impuestos=[ImpuestoInscripto(**i) for i in self._parse_repeated(rg_el, 'impuesto')],
				categoriasAutonomo=[CategoriaContribuyente(**c) for c in self._parse_repeated(rg_el, 'categoriaAutonomo')],
				regimenes=[RegimenInscripto(**r) for r in self._parse_repeated(rg_el, 'regimen')],
			)

		# ── datosMonotributo ────────────────────────────────────
		mt_el = self._find_section('datosMonotributo')
		monotributo: Optional[DatosMonotributo] = None
		if mt_el is not None:
			act_mt_raw = self._parse_single_child(mt_el, 'actividadMonotributista')
			cat_mt_raw = self._parse_single_child(mt_el, 'categoriaMonotributo')
			monotributo = DatosMonotributo(
				actividad=ActividadEconomica(**act_mt_raw) if act_mt_raw else None,
				categoriaMonotributo=(CategoriaContribuyente(**cat_mt_raw) if cat_mt_raw else None),
				componentesSociedad=[ComponenteSociedad(**c) for c in self._parse_repeated(mt_el, 'componenteDeSociedad')],
				impuestos=[ImpuestoInscripto(**i) for i in self._parse_repeated(mt_el, 'impuesto')],
			)

		# ── Errores ─────────────────────────────────────────────
		ec_el = self._find_section('errorConstancia')
		error_constancia: Optional[ErrorConstancia] = None
		if ec_el is not None:
			errors = [e.text or '' for e in ec_el.findall(_ns('error'))]
			if not errors:
				errors = [e.text or '' for e in ec_el.findall('error')]
			error_constancia = ErrorConstancia(
				error=errors,
				idPersona=self._child_text(ec_el, 'idPersona'),
			)

		erg_el = self._find_section('errorRegimenGeneral')
		error_rg = (
			ErrorSeccion(
				error=self._child_text(erg_el, 'error'),
				mensaje=self._child_text(erg_el, 'mensaje'),
			)
			if erg_el is not None
			else None
		)

		emt_el = self._find_section('errorMonotributo')
		error_mt = (
			ErrorSeccion(
				error=self._child_text(emt_el, 'error'),
				mensaje=self._child_text(emt_el, 'mensaje'),
			)
			if emt_el is not None
			else None
		)

		# ── Metadata ───────────────────────────────────────────
		md_el = self._find_section('metadata')
		metadata = (
			MetadataRespuesta(
				fechaHora=self._child_text(md_el, 'fechaHora'),
				servidor=self._child_text(md_el, 'servidor'),
			)
			if md_el is not None
			else None
		)

		return OutputModel(
			datosGenerales=datos_generales,
			domicilioFiscal=domicilio_fiscal,
			dependencia=dependencia,
			regimenGeneral=regimen_general,
			monotributo=monotributo,
			errorConstancia=error_constancia,
			errorRegimenGeneral=error_rg,
			errorMonotributo=error_mt,
			metadata=metadata,
		)


def consultar_cuit(
	cuit_consulta: str,
	token: str,
	sign: str,
	cuit_representante: str,
	url: str = PADRON_A5_URL,
) -> PadronA5Result:
	"""Consultar datos de un CUIT en el padrón ARCA A5."""
	soap = _build_padron_soap(cuit_representante, token, sign, cuit_consulta)
	resp = requests.post(
		url,
		data=soap.encode('utf-8'),
		headers={
			'Content-Type': 'text/xml;charset=UTF-8',
			'SOAPAction': '',
		},
		timeout=30,
		proxies=_get_arca_proxies(),
	)
	resp.raise_for_status()
	return PadronA5Result(resp.text)


# ─── Helper de alto nivel ──────────────────────────────────────────────────


def consultar_padron(
	cuit_consulta: str,
	cert_path: str,
	key_path: str,
	cuit_representante: str,
	cache_file: Optional[str] = None,
) -> dict:
	"""Obtener datos de un CUIT desde ARCA: WSAA + Padrón A5."""
	token, sign = obtener_ta(
		'ws_sr_constancia_inscripcion',
		cert_path,
		key_path,
		cache_file=cache_file,
	)

	result = consultar_cuit(cuit_consulta, token, sign, cuit_representante)
	return result.to_enriched_dict()
