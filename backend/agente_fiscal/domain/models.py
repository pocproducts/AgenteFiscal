"""Pydantic models for fiscal agent data contracts.

Central validation layer for all pipeline stages. Uses Pydantic v2
to enforce types at stage boundaries — ARCA extraction, rules engine,
PDF generator, and email delivery all speak these models.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class TipoContribuyente(str, Enum):
	"""Taxpayer regime as registered in ARCA."""

	monotributo = 'monotributo'
	autonomo = 'autonomo'
	responsable_inscripto = 'responsable_inscripto'


class TipoPersona(str, Enum):
	"""Legal personality type — affects tax obligations."""

	fisica = 'fisica'
	juridica = 'juridica'


class SmtpConfig(BaseModel):
	"""SMTP server configuration for email delivery."""

	host: str
	port: int = Field(default=587, ge=1, le=65535)
	user: str
	password: str
	from_addr: str


class ClientConfig(BaseModel):
	"""Per-client configuration loaded from clients.yaml.

	Each client has a CUIT, ARCA credentials, and metadata that
	determines which tax obligations apply and how to calculate them.
	"""

	cuit: str = Field(description='CUIT del contribuyente')
	clave_fiscal: str = Field(default='', description='Clave fiscal ARCA (vacio si no se tiene aun)')
	tipo: Optional[TipoContribuyente] = Field(default=None, description='Tipo de contribuyente')
	email: str = Field(default='', description='Email del cliente (vacio si no se tiene aun)')
	nombre: Optional[str] = Field(default=None, description='Nombre o razon social')
	tipo_persona: Optional[TipoPersona] = Field(
		default=None,
		description='Tipo de persona: fisica o juridica. Solo aplica a RI.',
	)
	cierre_ejercicio: Optional[int] = Field(
		default=None,
		ge=1,
		le=12,
		description='Mes de cierre del ejercicio fiscal. Default 12 (diciembre) para no especificado.',
	)
	provincias: Optional[List[str]] = Field(
		default=None,
		description='Provincias donde opera. Si tiene mas de 1, aplica Convenio Multilateral.',
	)


class AppConfig(BaseModel):
	"""Full application configuration from clients.yaml."""

	smtp: SmtpConfig
	clientes: List[ClientConfig] = Field(min_length=1, description='Al menos un cliente requerido')


class ArcaOutput(BaseModel):
	"""Structured output from ARCA browser extraction.

	The ``datos`` dict is intentionally flexible — different taxpayer
	types expose different fiscal data structures. The rules engine
	interprets ``datos`` based on ``tipo``.
	"""

	cuit: str
	tipo: str
	extracted_at: datetime
	datos: dict = Field(default_factory=dict, description='Datos extraidos, estructura variable segun tipo')
	error: Optional[str] = Field(default=None, description='Error message si fallo la extraccion')


class Vencimiento(BaseModel):
	"""A single due-date line item in the fiscal calendar."""

	concepto: str = Field(description='Nombre de la obligacion (ej: "Monotributo - Cuota Mensual")')
	fecha: date
	importe: Optional[float] = Field(default=None, description='Monto si esta disponible')
	es_fecha_habil: bool = Field(default=True, description='True si la fecha es dia habil')


class RulesOutput(BaseModel):
	"""Output of the fiscal rules engine — a sorted list of due dates."""

	cuit: str
	periodo: str = Field(pattern=r'^\d{4}-\d{2}$', description='Periodo fiscal en formato YYYY-MM')
	vencimientos: List[Vencimiento] = Field(default_factory=list)
	observaciones: List[str] = Field(
		default_factory=list,
		description='Obligaciones informativas sin fecha de pago (ej: regimenes de informacion, presentacion de EE.CC.)',
	)
	feriados_presentes: List[date] = Field(default_factory=list)
	error: Optional[str] = Field(default=None)


# ─── Calendario AFIP: modelos del calendario fiscal ─────────────────────────


class GrupoCuit(BaseModel):
	"""CUIT termination range for a calendar column."""

	desde: int = Field(ge=0, le=9)
	hasta: int = Field(ge=0, le=9)
	columna: str  # original column name from the calendar


class ObligacionCalendario(BaseModel):
	"""A fiscal obligation with its due dates by month."""

	key: str  # internal key like "iva_ddjj"
	label: str  # display name like "IVA DDJJ"
	categoria: Optional[str] = None  # taxpayer type (opcional, ahora va implícito en por_tipo)
	id_impuesto: Optional[int] = None  # maps to WS API impuesto id
	grupos_cuit: List[GrupoCuit]
	meses: Dict[str, int]  # month number (1-12) -> day of month


class CalendarioAFIP(BaseModel):
	"""Full AFIP fiscal calendar loaded from JSON.

	Organizado por tipo de contribuyente::

	        por_tipo['responsable_inscripto']['iva_ddjj']
	        por_tipo['monotributo']['monotributo']
	        por_tipo['autonomo']['autonomos']
	"""

	version: str
	fuente: str
	notas: Dict[str, str] = {}
	por_tipo: Dict[str, Dict[str, ObligacionCalendario]]


class VencimientoDeuda(BaseModel):
	"""A single vencimiento row from ctacte.cloud extraction."""

	impuesto: str = ''
	concepto: str = ''
	subconcepto: str = ''
	periodo: int = 0
	anticuota: int = 0
	fecha_vencimiento: Optional[date] = None
	detalle: str = ''


class DeudaDetail(BaseModel):
	"""A single deuda row from ctacte.cloud extraction."""

	impuesto: str = ''
	concepto: str = ''
	subconcepto: str = ''
	periodo: int = 0
	anticuota: int = 0
	vencimiento: Optional[date] = None
	saldo: float = 0.0
	interes_resarcitorio: float = 0.0
	interes_punitorio: float = 0.0


class DeudaItem(BaseModel):
	"""A single debt item from browser-use extraction."""

	concepto: str
	importe: float
	vencimiento: Optional[date] = None
	estado: Optional[str] = None  # "impago", "pagado", etc.


class FacilidadPlanCuota(BaseModel):
	"""Una cuota individual dentro de un plan de pagos de Mis Facilidades."""

	numero: int
	capital: float = 0.0
	interes_financiero: float = 0.0
	interes_resarcitorio: float = 0.0
	total: float = 0.0
	vencimiento: Optional[date] = None
	fecha_pago: Optional[date] = None
	estado: str = ''


class FacilidadProximoVencimiento(BaseModel):
	"""Próximo vencimiento de un plan de pagos."""

	nro_cuota: int
	fecha: date
	total: float = 0.0


class FacilidadDatosPlan(BaseModel):
	"""Datos del plan (CBU, consolidación, titular)."""

	fecha_consolidacion: Optional[date] = None
	cbu: str = ''
	titular_cbu: str = ''


class FacilidadPlan(BaseModel):
	"""Un plan de pagos de Mis Facilidades ARCA."""

	plan: str = ''
	nro_plan: str = ''
	estado: str = ''
	fecha_presentacion: Optional[date] = None
	cantidad_cuotas: int = 0
	cuotas_pagas: int = 0
	cuotas_impagas: int = 0
	saldo: float = 0.0
	concepto: str = ''
	proximo_vencimiento: Optional[FacilidadProximoVencimiento] = None
	cuotas: List[FacilidadPlanCuota] = Field(default_factory=list)
	datos_plan: Optional[FacilidadDatosPlan] = None
	observacion: str = ''


class RegistroDomicilio(BaseModel):
	"""Domicilio registrado en ARCA."""

	tipo: str = ''
	provincia: str = ''
	localidad: str = ''
	direccion: str = ''
	codigo_postal: str = ''


class RegistroActividad(BaseModel):
	"""Actividad económica registrada."""

	actividad: str = ''
	codigo: str = ''
	estado: str = ''


class RegistroImpuesto(BaseModel):
	"""Impuesto/regimen en el que el contribuyente está inscripto."""

	impuesto: str = ''
	categoria: Optional[str] = None
	estado: str = ''


class RegistroPuntoVenta(BaseModel):
	"""Punto de venta registrado."""

	punto: str = ''
	tipo: str = ''
	estado: str = ''


class RegistroIIBBJurisdiccion(BaseModel):
	"""IIBB jurisdiction where the taxpayer is registered.

	Each entry represents one province where the taxpayer has an
	IIBB inscription, with registration number and status.
	"""

	provincia: str = ''
	inscripcion: str = ''
	estado: str = ''
	fecha_alta: Optional[date] = None
	fecha_baja: Optional[date] = None


class IIBBCuotaVencida(BaseModel):
	"""Cuota vencida de IIBB con recargo y estado de mora."""

	periodo: str = ''  # ej: "2026/3"
	impuesto: str = ''  # ej: "Ingresos Brutos Local - Régimen Mensual"
	vencimiento: Optional[date] = None  # fecha de vencimiento
	saldo: Optional[float] = None  # monto adeudado
	recargo: Optional[float] = None  # recargo por mora
	estado: str = ''  # ej: "EN MORA", "PAGADO"
	apto_plan: bool = False  # "No apta plan" / "Apta plan"


class IIBBJurisdiccionResultado(BaseModel):
	"""Result of IIBB matching for a single jurisdiction.

	Three-way check: client config, WS API, RUT data.
	``match_total`` is True only when all three align.
	"""

	provincia: str = ''
	configurada_en_cliente: bool = False
	detectada_en_ws: bool = False
	detectada_en_rut: bool = False
	inscripcion: str = ''
	estado: str = ''
	match_total: bool = False


class RentasCordobaMatching(BaseModel):
	"""Resultado del matching de integración con Rentas Córdoba.

	Indica si un contribuyente con Convenio Multilateral IIBB y registro
	en IIBB Córdoba requiere integrarse con Rentas Córdoba para consultar
	deuda y vencimientos provinciales.
	"""

	requiere_integracion: bool = False
	tiene_convenio_multilateral: bool = False
	tiene_iibb_cordoba: Optional[bool] = None
	url: str = 'https://www.rentascordoba.gob.ar/'
	estado: str = 'no_requerido'
	observacion: str = ''


class RegistroOutput(BaseModel):
	"""Registro tributario: domicilios, actividades, impuestos, etc."""

	domicilios: List[RegistroDomicilio] = Field(default_factory=list)
	jurisdiccion: Optional[str] = None
	actividades: List[RegistroActividad] = Field(default_factory=list)
	impuestos: List[RegistroImpuesto] = Field(default_factory=list)
	puntos_de_venta: List[RegistroPuntoVenta] = Field(default_factory=list)
	iibb_jurisdicciones: List[RegistroIIBBJurisdiccion] = Field(default_factory=list)
	iibb_cuotas_vencidas: List[IIBBCuotaVencida] = Field(default_factory=list)


class DeudaOutput(BaseModel):
	"""Output from browser-use deuda extraction."""

	cuit: str
	extraido_el: datetime
	fuente: str = 'browser-use'
	deuda_actual: Optional[float] = None
	saldos: List[DeudaItem] = Field(default_factory=list)
	plan_pagos: Optional[Any] = None
	error: Optional[str] = None
	# Nuevo formato ctacte.cloud
	vencimientos: List[VencimientoDeuda] = Field(default_factory=list)
	deudas: List[DeudaDetail] = Field(default_factory=list)
	# Planes de pago Mis Facilidades
	facilidades: List[FacilidadPlan] = Field(default_factory=list)
	# Registro tributario IIBB + impuestos
	registro: Optional[RegistroOutput] = None


# ─── Padrón A5: modelos de datos AFIP ───────────────────────────────────────


class DomicilioFiscal(BaseModel):
	"""Domicilio fiscal registrado en ARCA."""

	direccion: Optional[str] = None
	localidad: Optional[str] = None
	codPostal: Optional[str] = None
	idProvincia: Optional[str] = None
	descripcionProvincia: Optional[str] = None
	tipoDomicilio: Optional[str] = None


class Dependencia(BaseModel):
	"""Dependencia registrada (opcional — sucursal/agencia)."""

	idDependencia: Optional[str] = None
	descripcionDependencia: Optional[str] = None
	direccion: Optional[str] = None
	localidad: Optional[str] = None
	codPostal: Optional[str] = None
	idProvincia: Optional[str] = None
	descripcionProvincia: Optional[str] = None


class ActividadEconomica(BaseModel):
	"""Actividad económica registrada en AFIP."""

	descripcionActividad: Optional[str] = None
	idActividad: Optional[int] = None
	nomenclador: Optional[str] = None
	orden: Optional[int] = None
	periodo: Optional[str] = None


class ImpuestoInscripto(BaseModel):
	"""Impuesto en el que la persona está inscripta."""

	descripcionImpuesto: Optional[str] = None
	idImpuesto: Optional[int] = None
	periodo: Optional[str] = None


class CategoriaContribuyente(BaseModel):
	"""Categoría de monotributo o autónomo (misma estructura para ambos)."""

	descripcionCategoria: Optional[str] = None
	idCategoria: Optional[int] = None
	idImpuesto: Optional[int] = None
	periodo: Optional[str] = None


class RegimenInscripto(BaseModel):
	"""Régimen impositivo registrado."""

	descripcionRegimen: Optional[str] = None
	idRegimen: Optional[str] = None
	idImpuesto: Optional[int] = None
	periodo: Optional[str] = None
	tipoRegimen: Optional[str] = None


class ComponenteSociedad(BaseModel):
	"""Componente de sociedad (monotributo — socio/administrador)."""

	apellidoPersonaAsociada: Optional[str] = None
	nombrePersonaAsociada: Optional[str] = None
	idPersonaAsociada: Optional[str] = None
	ffRelacion: Optional[int] = None
	tipoComponente: Optional[str] = None


class DatosGenerales(BaseModel):
	"""Datos generales de la persona consultada.

	Aparece siempre que la consulta es exitosa. ``idPersona`` es el CUIT.
	"""

	apellido: Optional[str] = None
	nombre: Optional[str] = None
	razonSocial: Optional[str] = None
	idPersona: Optional[str] = None
	tipoPersona: Optional[str] = None
	tipoClave: Optional[str] = None
	estadoClave: Optional[str] = None
	mesCierre: Optional[int] = None


class DatosRegimenGeneral(BaseModel):
	"""Datos del régimen general (IVA, Ganancias, etc.)."""

	actividades: List[ActividadEconomica] = Field(default_factory=list)
	impuestos: List[ImpuestoInscripto] = Field(default_factory=list)
	categoriasAutonomo: List[CategoriaContribuyente] = Field(default_factory=list)
	regimenes: List[RegimenInscripto] = Field(default_factory=list)


class DatosMonotributo(BaseModel):
	"""Datos del monotributo (actividad, categoria, socios)."""

	actividad: Optional[ActividadEconomica] = None
	categoriaMonotributo: Optional[CategoriaContribuyente] = None
	componentesSociedad: List[ComponenteSociedad] = Field(default_factory=list)
	impuestos: List[ImpuestoInscripto] = Field(default_factory=list)


class ErrorConstancia(BaseModel):
	"""Error de constancia: CUIT no encontrado, dado de baja, etc."""

	error: List[str] = Field(default_factory=list)
	idPersona: Optional[str] = None


class ErrorSeccion(BaseModel):
	"""Error en una sección específica del padrón."""

	error: Optional[str] = None
	mensaje: Optional[str] = None


class MetadataRespuesta(BaseModel):
	"""Metadatos de la respuesta de AFIP."""

	fechaHora: Optional[str] = None
	servidor: Optional[str] = None


class PadronA5Output(BaseModel):
	"""Output estructurado completo de una consulta al padrón A5.

	Cada campo refleja una sección del XML de respuesta de AFIP.
	"""

	datosGenerales: Optional[DatosGenerales] = None
	domicilioFiscal: Optional[DomicilioFiscal] = None
	dependencia: Optional[Dependencia] = None
	regimenGeneral: Optional[DatosRegimenGeneral] = None
	monotributo: Optional[DatosMonotributo] = None
	errorConstancia: Optional[ErrorConstancia] = None
	errorRegimenGeneral: Optional[ErrorSeccion] = None
	errorMonotributo: Optional[ErrorSeccion] = None
	metadata: Optional[MetadataRespuesta] = None


# ─── Unified Output Schema ────────────────────────────────────────────────


T = TypeVar('T')


class ApiError(BaseModel):
	"""Structured error for API responses — code, cause, and optional remediation."""

	code: str = Field(description='Código de error machine-readable (ej: TA_UNAVAILABLE)')
	cause: str = Field(description='Descripción legible de la causa del error')
	remediation: str = Field(default='', description='Sugerencia para resolver el error (opcional)')


class UnifiedResponse(BaseModel, Generic[T]):
	"""Generic envelope for all agent-ready API responses.

	Wraps any domain model (DeudaOutput, RulesOutput, etc.) with a uniform
	structure that agents can reason about: status, typed result, suggested
	next actions, human approval flag, and structured error.
	"""

	model_config = ConfigDict(extra='forbid')

	status: Literal['success', 'error', 'pending', 'requires_approval'] = Field(description='Estado de la operación')
	result: T | None = Field(default=None, description='Datos de la respuesta (según el endpoint)')
	next_actions: list[str] = Field(default=[], description='Acciones sugeridas para el agente')
	human_approval_required: bool = Field(default=False, description='Indica si se requiere aprobación humana para continuar')
	error: ApiError | None = Field(default=None, description='Error estructurado (presente solo si status=error)')


class IdempotentRequest(BaseModel):
	"""Mixin/base for write operations that support idempotency.

	Note: idempotency storage is NOT implemented yet — this is the contract
	for future phases.
	"""

	model_config = ConfigDict(extra='forbid')

	idempotency_key: str | None = Field(
		default=None,
		description='Clave única de idempotencia para evitar procesamiento duplicado',
	)


# ─── Tenant / Identity Models ─────────────────────────────────────────────


class PlanTier(str, Enum):
	"""Subscription tier for a tenant.

	Values: free, pro, pro max, enterprise.
	"""

	free = 'free'
	pro = 'pro'
	pro_max = 'pro max'
	enterprise = 'enterprise'


class Tenant(BaseModel):
	"""An accounting firm or taxpayer entity using the system."""

	id: str
	name: str
	plan_tier: PlanTier = PlanTier.free
	cuit: str
	clave_fiscal: str
	certificados: list[str] = []
	clientes: list[dict] = []
	provincias: list[str] = []
	is_active: bool = True


class Client(BaseModel):
	"""A CUIT taxpayer managed by a tenant (accounting firm).

	Mirrors ``db.models.business.Client`` (Postgres, cutover Phase 5) —
	the entity ``report_runs.client_id`` points at.
	"""

	id: str
	tenant_id: str
	cuit: str
	name: str
	email: str | None = None
	config: dict = Field(default_factory=dict)
	created_at: datetime


class Developer(BaseModel):
	"""A developer account that owns applications."""

	id: str
	name: str
	email: str
	created_at: datetime
	is_active: bool = True


class App(BaseModel):
	"""An application registered by a developer, linked to an API key."""

	id: str
	developer_id: str
	name: str
	environment: Literal['sandbox', 'production']
	status: Literal['pending', 'active', 'suspended', 'revoked'] = 'pending'


class ApiKey(BaseModel):
	"""API key credential for machine-to-machine auth.

	``key_preview`` stores only the last 4 characters — the full key
	is hashed and stored elsewhere in production.
	"""

	id: str
	app_id: str
	key_preview: str
	is_active: bool = True
	scopes: list[str] = []
	tenant_id: str | None = None
	created_at: datetime
	expires_at: datetime | None = None


class Plan(BaseModel):
	"""A service plan defining available scopes and rate limits."""

	id: str
	name: str
	scopes: list[str]
	rate_limit_rpm: int
	rate_limit_rpd: int


# ─── System Monitoring Models ───────────────────────────────────────


class PipelineRun(BaseModel):
	"""First-class pipeline execution record persisted in Engram.

	Each run represents one full pipeline execution for a CUIT, tracking
	which stages completed, total duration, and final status.
	"""

	model_config = ConfigDict(extra='forbid')

	run_id: str = Field(description='UUID v4 — idempotency key')
	cuit: str = Field(description='CUIT del contribuyente')
	status: Literal['success', 'partial', 'failed'] = Field(description='Resultado final del pipeline')
	stages_completed: list[str] = Field(default_factory=list, description='Etapas que se completaron exitosamente')
	error: str | None = Field(default=None, description='Mensaje de error si el pipeline falló')
	timestamp: datetime = Field(description='Momento en que finalizó la ejecución')
	duration_seconds: float = Field(description='Duración total del pipeline en segundos')


class ServiceStatus(BaseModel):
	"""Estado individual de un servicio dependiente."""

	model_config = ConfigDict(extra='forbid')

	name: str = Field(description='Nombre del servicio (api, redis, engram, ta, composio)')
	status: Literal['healthy', 'degraded', 'down'] = Field(description='Healthy si responde correctamente')
	uptime: str = Field(default='', description='Tiempo de actividad del servicio (ej: 99.98%)')
	last_check: datetime = Field(description='Momento del último chequeo')
	latency_ms: float | None = Field(default=None, description='Latencia de la última consulta en milisegundos')
	error: str | None = Field(default=None, description='Mensaje de error si el servicio no responde')
	version: str | None = Field(default=None, description='Versión del servicio si está disponible')


class SystemHealth(BaseModel):
	"""Estado global del sistema y todos sus servicios dependientes."""

	model_config = ConfigDict(extra='forbid')

	status: Literal['healthy', 'degraded', 'down'] = Field(description='Estado global del sistema')
	services: list[ServiceStatus] = Field(description='Lista de servicios chequeados')
	timestamp: datetime = Field(description='Momento del chequeo')


class SystemMetrics(BaseModel):
	"""Métricas agregadas del sistema a partir de observaciones en Engram."""

	model_config = ConfigDict(extra='forbid')

	total_pipeline_runs: int = Field(description='Total de ejecuciones de pipeline en el período')
	successful_runs: int = Field(description='Ejecuciones exitosas')
	failed_runs: int = Field(description='Ejecuciones fallidas')
	error_rate: float = Field(description='Porcentaje de error (0.0 a 1.0)')
	total_cuits_processed: int = Field(description='CUITs únicos que ejecutaron pipeline')
	recent_errors: list[ErrorEvent] = Field(default_factory=list, description='Últimos errores registrados')
	runs_by_hour: list[dict] = Field(default_factory=list, description='Distribución de runs por hora')


class ActivityEvent(BaseModel):
	"""Evento de actividad del sistema — pipeline run o error."""

	model_config = ConfigDict(extra='forbid')

	id: str = Field(description='Identificador único del evento')
	type: Literal['pipeline_run', 'error', 'deployment', 'system'] = Field(description='Tipo de evento')
	title: str = Field(description='Título descriptivo del evento')
	description: str = Field(default='', description='Descripción detallada del evento')
	timestamp: datetime = Field(description='Momento del evento')
	cuit: str | None = Field(default=None, description='CUIT asociado al evento')
	severity: str | None = Field(default=None, description='Severidad (error, warning, info)')


class ErrorEvent(BaseModel):
	"""Evento de error registrado en el sistema."""

	model_config = ConfigDict(extra='forbid')

	id: str = Field(description='Identificador único del error')
	type: Literal[
		'TimeoutException',
		'ARCAError',
		'ComposioError',
		'EngramError',
		'RedisError',
		'ValidationError',
		'Unknown',
	] = Field(description='Tipo de error clasificado')
	message: str = Field(description='Mensaje descriptivo del error')
	severity: str = Field(default='error', description='Severidad: error, warning, critical')
	service: str = Field(default='pipeline', description='Servicio que originó el error')
	cuit: str | None = Field(default=None, description='CUIT asociado al error si aplica')
	timestamp: datetime = Field(description='Momento del error')
	count: int = Field(default=1, description='Conteo de ocurrencias del mismo error')
	trend: Literal['increasing', 'stable', 'decreasing'] = Field(
		default='stable', description='Tendencia del error en el período'
	)
