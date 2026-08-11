"""Fiscal agent CLI — pipeline orchestration.

Usage:
        python -m fiscal_agent run --config clients.yaml
        python -m fiscal_agent validate [config_path]
        python -m fiscal_agent generate-template [output_path]
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from fiscal_agent.config import CERT_DIR, CERT_PATH, KEY_PATH, REPRESENTANTE_CUIT, get_settings
from fiscal_agent.pipeline.service import PipelineService, _completar_cliente_desde_padron
import typer
import yaml

from fiscal_agent.arca_ws import consultar_cuit, get_ta
from fiscal_agent.email_sender import EmailSender
from fiscal_agent.memory import FiscalMemoryClient
from fiscal_agent.models import AppConfig, ClientConfig, TipoContribuyente, TipoPersona
from fiscal_agent.pdf_generator import PdfGenerator
from fiscal_agent.rules_engine import RulesEngine

logger = logging.getLogger(__name__)

app = typer.Typer(
	name='fiscal-agent',
	help='Vertical AI Agent Fiscal — calendario de vencimientos ARCA',
)

# ── Paths ───────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = Path('clients.yaml')


# ── Shared Pipeline ──────────────────────────────────────────────────────────────


def _procesar_cliente_pipeline(
	cliente: ClientConfig,
	token: str,
	sign: str,
	engine: RulesEngine,
	pdf_gen: PdfGenerator,
	mes: int,
	anio: int,
	browser: Optional[ComposioBrowser] = None,
	with_deuda: bool = False,
	with_facilidades: bool = False,
	with_registro: bool = False,
	with_iibb: bool = False,
	send_email: bool = True,
	config: Optional[AppConfig] = None,
	output_dir: Optional[Path] = None,
	memory_client: Optional[FiscalMemoryClient] = None,
	echo_func: Optional = None,
) -> dict:
	"""Pipeline single-cliente. Retorna dict con resultado + pdf_path.

	Thin wrapper delegating to ``PipelineService.run_pipeline()``.
	Preserves backward-compatible signature and return dict.
	"""
	if echo_func is None:
		echo_func = typer.echo

	svc = PipelineService(engine, pdf_gen, memory_client)
	result = svc.run_pipeline(
		cliente=cliente,
		token=token,
		sign=sign,
		mes=mes,
		anio=anio,
		browser=browser,
		with_deuda=with_deuda,
		with_facilidades=with_facilidades,
		with_registro=with_registro,
		with_iibb=with_iibb,
		send_email=send_email,
		config=config,
		output_dir=output_dir,
		progress_callback=echo_func,
	)
	return result.model_dump()


# ── Commands ────────────────────────────────────────────────────────────────────


@app.command()
def validate(
	config_path: Path = typer.Argument(
		DEFAULT_CONFIG,
		help='Ruta al archivo clients.yaml',
		exists=True,
	),
) -> None:
	"""Validate clients.yaml against Pydantic models."""
	raw = yaml.safe_load(config_path.read_text())
	config = AppConfig(**raw)
	typer.echo(f'Config valida: {len(config.clientes)} cliente(s), SMTP en {config.smtp.host}')
	for c in config.clientes:
		prov = ', '.join(c.provincias) if c.provincias else '(sin especificar)'
		nombre = c.nombre or c.cuit
		tipo_str = c.tipo.value if c.tipo else '—(pendiente)—'
		typer.echo(f'  {c.cuit} | {nombre:30s} | {tipo_str:20s} | {prov}')
		if not c.email:
			typer.echo(f'  ⚠️   Falta email para {nombre}')
		if c.tipo is not None and c.tipo != 'monotributo' and not c.clave_fiscal:
			typer.echo(f'  ⚠️   Falta clave_fiscal para {nombre} (necesaria para browser-use)')


@app.command()
def generate_template(
	output: Path = typer.Argument(
		Path('clientes_para_completar.csv'),
		help='Ruta de salida del CSV',
	),
) -> None:
	"""Generate a CSV template for the accountant to fill in."""
	import csv

	fields = [
		'cuit',
		'clave_fiscal',
		'tipo',
		'tipo_persona',
		'email',
		'cierre_ejercicio',
		'provincias',
	]

	with output.open('w', newline='') as f:
		writer = csv.writer(f)
		writer.writerow(fields)
		writer.writerow(
			[
				'30716395541',
				'Pablo20325',
				'responsable_inscripto',
				'juridica',
				'cliente@ejemplo.com',
				'12',
				'CABA',
			]
		)
		writer.writerow(
			[
				'33718532669',
				'',
				'responsable_inscripto',
				'juridica',
				'',
				'12',
				'CABA, Buenos Aires',
			]
		)

	typer.echo(f'Template generado: {output}')
	typer.echo('Completar: clave_fiscal, email, provincias de cada cliente')


@app.command()
def discover(
	cuit: str = typer.Argument(..., help='CUIT a consultar en el Padrón A5'),
) -> None:
	"""Consultar Padrón A5 y deducir datos de un cliente interactivamente."""
	load_dotenv()

	# 1. Verificar certificados
	if not CERT_PATH.exists() or not KEY_PATH.exists():
		typer.echo('Error: certificados no encontrados en .certificados-arca/')
		raise typer.Exit(1)

	# 2. Obtener TA
	typer.echo('Obteniendo TA ...')
	token, sign = get_ta()
	typer.echo(f'TA vigente: {token[:40]}...')
	typer.echo()

	# 3. Consultar padrón
	typer.echo(f'Consultando CUIT {cuit} ...')
	result = consultar_cuit(cuit, token, sign, REPRESENTANTE_CUIT)
	output = result.to_output()
	output_dict = result.to_dict()

	# Verificar errores
	if output.errorConstancia:
		typer.echo('❌ Error en la consulta:')
		for e in output.errorConstancia.error:
			typer.echo(f'   • {e}')
		raise typer.Exit(1)

	# 4. Mostrar datos deducidos
	tipo = output_dict.get('tipo', '')
	tipo_persona = output_dict.get('tipo_persona', '')
	cierre = output_dict.get('mes_cierre', 12)
	provincia = output_dict.get('provincia', '')

	# Nombre: prefiere razon_social para jurídicas, nombre+apellido para físicas
	nombre = (
		output_dict.get('razon_social')
		or output_dict.get('nombre')
		or f'{output_dict.get("nombre", "")} {output_dict.get("apellido", "")}'.strip()
		or cuit
	)

	typer.echo()
	typer.echo('═' * 50)
	typer.echo('  DATOS DEDUCIDOS DEL PADRÓN A5')
	typer.echo('═' * 50)
	typer.echo(f'  CUIT:             {cuit}')
	typer.echo(f'  Nombre/Razón Soc: {nombre}')
	typer.echo(f'  Tipo:             {tipo}')
	typer.echo(f'  Tipo persona:     {tipo_persona}')
	typer.echo(f'  Cierre ejercicio: {cierre}')
	typer.echo(f'  Provincia fiscal: {provincia}')
	typer.echo('═' * 50)
	typer.echo()

	# 5. Pedir solo lo que ARCA no sabe
	email = typer.prompt('Email del cliente', default='')
	clave_fiscal = typer.prompt('Clave fiscal ARCA', default='')

	# Provincia se deduce del padrón (domicilio fiscal).
	# Si opera en más, se edita manual en clients.yaml después.
	provincias = [provincia] if provincia else []

	# 6. Mostrar bloque YAML
	typer.echo()
	typer.echo('═' * 50)
	typer.echo('  BLOQUE YAML — copialo en clients.yaml')
	typer.echo('═' * 50)
	typer.echo(f'  - cuit: {cuit}')
	typer.echo(f'    clave_fiscal: "{clave_fiscal}"')
	typer.echo(f'    email: "{email}"')
	typer.echo(f'    nombre: "{nombre}"')
	typer.echo(f'    tipo: {tipo}')
	if tipo_persona:
		typer.echo(f'    tipo_persona: {tipo_persona}')
	typer.echo(f'    cierre_ejercicio: {cierre}')
	if provincias:
		typer.echo(f'    provincias: [{", ".join(provincias)}]')
	else:
		typer.echo('    provincias: []')
	typer.echo('═' * 50)
	typer.echo()
	typer.echo('📋 Copiá ese bloque y pegálo en clients.yaml bajo clientes:')
	typer.echo()


@app.command()
def run(
	config_path: Path = typer.Option(
		DEFAULT_CONFIG,
		'--config',
		'-c',
		help='Ruta al archivo clients.yaml',
		exists=True,
	),
	mes: Optional[int] = typer.Option(
		None,
		'--mes',
		'-m',
		help='Mes a calcular (1-12). Default: mes actual',
	),
	anio: Optional[int] = typer.Option(
		None,
		'--anio',
		'-a',
		help='Año (e.g. 2026). Default: año actual',
	),
	send_email: bool = typer.Option(
		True,
		'--send/--no-send',
		help='Enviar email con el PDF',
	),
	with_deuda: bool = typer.Option(
		False,
		'--with-deuda',
		'-d',
		help='Extraer deuda real vía Composio Browser para cada cliente',
	),
	with_facilidades: bool = typer.Option(
		False,
		'--with-facilidades',
		'-f',
		help='Extraer planes de pago de Mis Facilidades ARCA',
	),
	with_registro: bool = typer.Option(
		False,
		'--with-registro',
		'-r',
		help='Extraer registro tributario IIBB e impuestos de ARCA',
	),
	with_iibb: bool = typer.Option(
		False,
		'--with-iibb',
		help='Extraer jurisdicciones IIBB detalladas del RUT',
	),
	headed: bool = typer.Option(
		False,
		'--headed',
		help='Mostrar URL en vivo del browser Composio (debug)',
	),
) -> None:
	"""Run the full pipeline for all clients.

	Pipeline: WS API → Rules Engine → PDF → Email (opcional)
	Con --with-deuda: agrega Composio Browser (ctacte.cloud) entre Rules Engine y PDF.
	Con --with-facilidades: agrega planes de pago de Mis Facilidades ARCA.
	Con --with-registro: agrega registro tributario IIBB e impuestos.
	Con --with-iibb: agrega extracción detallada de jurisdicciones IIBB.
	"""
	now = datetime.now()
	mes = mes or now.month
	anio = anio or now.year

	# Load .env before anything else
	load_dotenv()

	# Configurar logging: INFO para ver task boundaries, formato limpio
	logging.basicConfig(level=logging.INFO, format='%(message)s', force=True)

	typer.echo(f'🚀 Pipeline fiscal — {mes:02d}/{anio}')
	typer.echo(f'   Config: {config_path}')
	typer.echo()

	# 0a. Init memory client (Engram + Redis cache)
	memory = FiscalMemoryClient()
	available = memory.is_available()
	if available:
		typer.echo('   Engram Memory: disponible')
		logger.info('[memory] Engram reachable at %s', memory.config.engram_url)
	else:
		typer.echo('   Engram Memory: no disponible (best-effort, continuando)')
		logger.warning('[memory] Engram not reachable at %s', memory.config.engram_url)
	typer.echo()

	# 0b. Early validation for browser flags
	usa_browser = with_deuda or with_facilidades or with_registro or with_iibb
	if usa_browser:
		creds = get_settings().credentials
		composio_api_key = creds.composio_api_key
		if not composio_api_key:
			typer.echo('❌ COMPOSIO_API_KEY no configurada en .env')
			raise typer.Exit(1)
		estudio_clave = creds.clave_fiscal
		if not estudio_clave:
			typer.echo('❌ ESTUDIO_CLAVE_FISCAL no configurada en .env')
			raise typer.Exit(1)

	# 1. Load config
	raw = yaml.safe_load(config_path.read_text())
	config = AppConfig(**raw)
	typer.echo(f'Clientes: {len(config.clientes)}')

	# 2. Init engine
	engine = RulesEngine()
	pdf_gen = PdfGenerator()

	# 3. Load certs
	if not CERT_PATH.exists() or not KEY_PATH.exists():
		typer.echo('Error: certificados no encontrados en .certificados-arca/')
		raise typer.Exit(1)

	# 4. Get TA (reusable for all clients — same representante)
	typer.echo('Obteniendo TA ...')
	token, sign = get_ta()
	typer.echo(f'TA vigente: {token[:40]}...')
	typer.echo()

	# 5. Init browser (deferred import — solo si --with-deuda o --with-facilidades)
	browser = None
	if usa_browser:
		from fiscal_agent.browser import ComposioBrowser

		browser = ComposioBrowser(
			composio_api_key=composio_api_key,
			estudio_cuit=REPRESENTANTE_CUIT,
			estudio_clave=estudio_clave,
			headed=headed,
		)

	# 6. Process each client
	resultados: list[dict] = []
	for i, cliente in enumerate(config.clientes, 1):
		typer.echo(f'── [{i}/{len(config.clientes)}] {cliente.nombre or cliente.cuit} ({cliente.cuit}) ──')
		resultado = _procesar_cliente_pipeline(
			cliente=cliente,
			token=token,
			sign=sign,
			engine=engine,
			pdf_gen=pdf_gen,
			mes=mes,
			anio=anio,
			browser=browser,
			with_deuda=with_deuda,
			with_facilidades=with_facilidades,
			with_registro=with_registro,
			with_iibb=with_iibb,
			send_email=send_email,
			config=config,
			memory_client=memory,
		)
		resultados.append(resultado)
		typer.echo()

	# 6. Summary
	ok = sum(1 for r in resultados if r['error'] is None)
	typer.echo('═' * 50)
	typer.echo(f'Resumen: {ok}/{len(resultados)} clientes OK')
	for r in resultados:
		status = '✅' if r['error'] is None else '❌'
		parts = []
		if r['ws_api']:
			parts.append('WS API')
		if r['calendario']:
			parts.append('Calendario')
		if r['pdf']:
			parts.append('PDF')
		if r['email']:
			parts.append('Email')
		typer.echo(f'  {status} {r["cliente"]}: {", ".join(parts) if parts else r["error"]}')

	if any(r['error'] for r in resultados):
		typer.echo('⚠️  Algunos clientes tienen errores — revisar logs')
		raise typer.Exit(1)

	typer.echo('Pipeline completado exitosamente.')


@app.command()
def deuda(
	config_path: Path = typer.Option(
		DEFAULT_CONFIG,
		'--config',
		'-c',
		help='Ruta al archivo clients.yaml',
		exists=True,
	),
	headed: bool = typer.Option(
		False,
		'--headed',
		help='Mostrar navegador para debug',
	),
) -> None:
	"""Extraer deuda real vía browser automation (proveedor configurable).

	Requiere: ESTUDIO_CUIT y ESTUDIO_CLAVE_FISCAL en .env
	"""
	load_dotenv()
	raw = yaml.safe_load(config_path.read_text())
	config = AppConfig(**raw)

	creds = get_settings().credentials
	estudio_clave = creds.clave_fiscal
	if not estudio_clave:
		typer.echo('❌ ESTUDIO_CLAVE_FISCAL no configurada en .env')
		raise typer.Exit(1)

	# ═══════════════════════════════════════════════════════════════════
	# Browser provider — intercambiable
	# Hoy: ComposioBrowser (Composio Browser Tool vía REST API)
	# ═══════════════════════════════════════════════════════════════════
	composio_api_key = creds.composio_api_key
	if not composio_api_key:
		typer.echo('❌ COMPOSIO_API_KEY no configurada en .env')
		typer.echo('   Obtenela en https://dashboard.composio.dev/settings')
		raise typer.Exit(1)

	from fiscal_agent.browser import ComposioBrowser

	deuda_resultados: list[dict] = []
	extractor = ComposioBrowser(
		composio_api_key=composio_api_key,
		estudio_cuit=REPRESENTANTE_CUIT,
		estudio_clave=estudio_clave,
		headed=headed,
	)
	try:
		outputs = asyncio.run(extractor.run_all(config.clientes))
		nombres = {c.cuit: c.nombre for c in config.clientes}
		for out in outputs:
			status = 'error' if out.error else 'ok'
			deuda_resultados.append(
				{
					'cliente': nombres.get(out.cuit, out.cuit),
					'cuit': out.cuit,
					'status': status,
					'error': out.error,
				}
			)
			if out.error:
				typer.echo(f'  ❌ {out.cuit}: {out.error}')
			else:
				typer.echo(f'  ✅ {out.cuit}: login + extract OK')
	finally:
		asyncio.run(extractor.close())

	# Summary
	if deuda_resultados:
		typer.echo()
		ok_d = sum(1 for r in deuda_resultados if r['status'] == 'ok')
		typer.echo(f'Browser: {ok_d}/{len(deuda_resultados)} representados OK')
		for r in deuda_resultados:
			status_sym = '✅' if r['status'] == 'ok' else '❌'
			err = f' — {r["error"]}' if r['error'] else ''
			typer.echo(f'  {status_sym} {r["cliente"]} ({r["cuit"]}){err}')


# ── Interactive Helpers (report command) ────────────────────────────────────────


def _validar_cuit(cuit: str) -> bool:
	"""Validar formato CUIT: 11 dígitos (con/sin guiones)."""
	return bool(re.fullmatch(r'\d{2}-?\d{8}-?\d{1}', cuit.strip()))


def _buscar_cliente_en_yaml(cuit: str, config: AppConfig) -> Optional[ClientConfig]:
	"""Buscar cliente por CUIT en la config cargada."""
	cuit_limpio = cuit.replace('-', '')
	for c in config.clientes:
		if c.cuit.replace('-', '') == cuit_limpio:
			return c
	return None


def _mostrar_datos_cliente(cliente: ClientConfig) -> None:
	"""Mostrar datos del cliente formateados."""
	typer.echo(f'  • CUIT:      {cliente.cuit}')
	typer.echo(f'  • Nombre:    {cliente.nombre or "(sin nombre)"}')
	typer.echo(f'  • Tipo:      {cliente.tipo.value if cliente.tipo else "—"}')
	typer.echo(f'  • Email:     {cliente.email or "(sin email)"}')
	if cliente.provincias:
		typer.echo(f'  • Provincias: {", ".join(cliente.provincias)}')


def _preguntar_tasks() -> dict:
	"""Preguntar al usuario qué tasks ejecutar. Retorna dict con flags."""
	typer.echo('─' * 60)
	typer.echo(' ¿Qué querés extraer?')
	typer.echo()
	deuda = typer.confirm(' ¿Extraer deuda real?', default=False)
	facilidades = typer.confirm(' ¿Extraer planes de pago?', default=False)
	registro = typer.confirm(' ¿Extraer registro tributario?', default=False)
	iibb = typer.confirm(' ¿Extraer jurisdicciones IIBB detalladas?', default=False)
	return {
		'with_deuda': deuda,
		'with_facilidades': facilidades,
		'with_registro': registro,
		'with_iibb': iibb,
	}


def _descubrir_cliente(
	cuit: str,
	cert_path: Path,
	key_path: Path,
	representante_cuit: str,
	config_path: Path,
) -> Optional[ClientConfig]:
	"""Descubrir cliente desde Padrón A5 y agregarlo al YAML.

	1. Obtiene TA
	2. Consulta Padrón A5
	3. Pide email y provincias
	4. Agrega el nuevo cliente a clients.yaml

	Nota: En el modelo ``Estudio Contable`` actual, la ``clave_fiscal``
	del contribuyente NO se necesita — el estudio usa su propia clave
	(``ESTUDIO_CLAVE_FISCAL`` en ``.env``) y hace switch de representado.
	Para el futuro modelo ``Individual``, cada cliente tendrá su propia
	clave — es una feature pendiente.
	"""
	from fiscal_agent.arca_ws import consultar_cuit, get_ta

	typer.echo(' Obteniendo TA ...')
	token, sign = get_ta()
	typer.echo(f' TA vigente: {token[:40]}...')
	typer.echo()

	typer.echo(f' Consultando CUIT {cuit} en Padrón A5 ...')
	result = consultar_cuit(cuit, token, sign, representante_cuit)
	output = result.to_output()
	output_dict = result.to_dict()

	if output.errorConstancia:
		typer.echo('❌ Error en la consulta:')
		for e in output.errorConstancia.error:
			typer.echo(f'   • {e}')
		return None

	tipo = output_dict.get('tipo', '')
	tipo_persona = output_dict.get('tipo_persona', '')
	cierre = output_dict.get('mes_cierre', 12)
	provincia = output_dict.get('provincia', '')

	nombre = (
		output_dict.get('razon_social')
		or output_dict.get('nombre')
		or f'{output_dict.get("nombre", "")} {output_dict.get("apellido", "")}'.strip()
		or cuit
	)

	typer.echo()
	typer.echo('═' * 50)
	typer.echo('  DATOS DEDUCIDOS DEL PADRÓN A5')
	typer.echo('═' * 50)
	typer.echo(f'  CUIT:             {cuit}')
	typer.echo(f'  Nombre:           {nombre}')
	typer.echo(f'  Tipo:             {tipo}')
	typer.echo(f'  Tipo persona:     {tipo_persona}')
	typer.echo(f'  Cierre ejercicio: {cierre}')
	typer.echo(f'  Provincia fiscal: {provincia}')
	typer.echo('═' * 50)
	typer.echo()

	email = typer.prompt(' Email del cliente', default='')
	typer.echo('  (Clave fiscal: se usa la del estudio del .env — modo Estudio Contable)')
	provincias_str = typer.prompt(' Provincias (separadas por coma)', default=provincia or '')
	provincias_list = [p.strip() for p in provincias_str.split(',') if p.strip()]

	nuevo_cliente = ClientConfig(
		cuit=cuit,
		email=email,
		nombre=nombre,
		tipo=TipoContribuyente(tipo) if tipo else None,
		tipo_persona=TipoPersona.fisica if tipo_persona.upper() == 'FISICA' else TipoPersona.juridica,
		cierre_ejercicio=cierre,
		provincias=provincias_list or None,
	)

	# Agregar al YAML en disco
	import yaml

	raw = yaml.safe_load(config_path.read_text())
	raw.setdefault('clientes', []).append(nuevo_cliente.model_dump(exclude_none=True, mode='json'))
	config_path.write_text(yaml.dump(raw, default_flow_style=False, allow_unicode=True, sort_keys=False))
	typer.echo(f'✔ Cliente {nombre} agregado a {config_path}')

	return nuevo_cliente


# ── Commands: report ────────────────────────────────────────────────────────────


@app.command()
def report(
	config_path: Path = typer.Option(
		DEFAULT_CONFIG,
		'--config',
		'-c',
		help='Ruta al archivo clients.yaml',
		exists=True,
	),
	headed: bool = typer.Option(
		False,
		'--headed',
		help='Mostrar URL en vivo del browser Composio (debug)',
	),
) -> None:
	"""Generar informe fiscal para un cliente específico (modo interactivo).

	Guía al usuario paso a paso: ingresa CUIT, selecciona qué extraer,
	y genera el PDF completo en ``storage/YYYY-MM/``.

	Uso::

	    uv run python -m fiscal_agent report
	    uv run python -m fiscal_agent report --headed
	"""
	load_dotenv()
	now = datetime.now()
	mes = now.month
	anio = now.year

	logging.basicConfig(level=logging.INFO, format='%(message)s', force=True)

	typer.echo('╔══════════════════════════════════════════╗')
	typer.echo('║  Generación de Informe Fiscal           ║')
	typer.echo('╚══════════════════════════════════════════╝')
	typer.echo()

	# 1. Pedir CUIT (con re-prompt si inválido)
	while True:
		cuit_input = typer.prompt('Ingresá el CUIT del cliente').strip()
		if _validar_cuit(cuit_input):
			break
		typer.echo('❌ CUIT inválido — deben ser 11 dígitos (ej: 20332837796)')
	cuit_limpio = cuit_input.replace('-', '')
	typer.echo('✔ CUIT válido')
	typer.echo()

	# 2. Cargar config y buscar cliente
	raw = yaml.safe_load(config_path.read_text())
	config = AppConfig(**raw)

	typer.echo('Buscando en clients.yaml ...')
	cliente = _buscar_cliente_en_yaml(cuit_limpio, config)

	if cliente is None:
		typer.echo(f'✖ CUIT {cuit_limpio} no encontrado en {config_path}')
		typer.echo()
		if typer.confirm('¿Querés descubrirlo desde el Padrón A5 y agregarlo?', default=True):
			# Verificar certificados
			if not CERT_PATH.exists() or not KEY_PATH.exists():
				typer.echo('❌ Certificados no encontrados en .certificados-arca/')
				raise typer.Exit(1)
			cliente = _descubrir_cliente(cuit_limpio, CERT_PATH, KEY_PATH, REPRESENTANTE_CUIT, config_path)
			if cliente is None:
				typer.echo('❌ No se pudo descubrir el cliente')
				raise typer.Exit(1)
			# Recargar config con el nuevo cliente
			raw = yaml.safe_load(config_path.read_text())
			config = AppConfig(**raw)
		else:
			typer.echo('Operación cancelada.')
			raise typer.Exit(0)

	# 3. Mostrar datos del cliente
	typer.echo()
	typer.echo('✔ Cliente encontrado:')
	_mostrar_datos_cliente(cliente)
	typer.echo()

	# 4. Preguntar tasks
	tasks = _preguntar_tasks()
	typer.echo()

	usa_browser = any(tasks.values())

	# 5. Validar entorno si usa browser
	composio_api_key = ''
	estudio_clave = ''
	if usa_browser:
		creds = get_settings().credentials
		composio_api_key = creds.composio_api_key
		if not composio_api_key:
			typer.echo('❌ COMPOSIO_API_KEY no configurada en .env')
			raise typer.Exit(1)
		estudio_clave = creds.clave_fiscal
		if not estudio_clave:
			typer.echo('❌ ESTUDIO_CLAVE_FISCAL no configurada en .env')
			raise typer.Exit(1)

	# 6. Verificar certificados
	if not CERT_PATH.exists() or not KEY_PATH.exists():
		typer.echo('❌ Certificados no encontrados en .certificados-arca/')
		raise typer.Exit(1)

	# 7. Obtener TA
	typer.echo('Obteniendo TA ...')
	token, sign = get_ta()
	typer.echo(f'TA vigente: {token[:40]}...')
	typer.echo()

	# 8. Init engine
	engine = RulesEngine()

	# 9. Init browser si necesario
	browser = None
	if usa_browser:
		from fiscal_agent.browser import ComposioBrowser

		browser = ComposioBrowser(
			composio_api_key=composio_api_key,
			estudio_cuit=REPRESENTANTE_CUIT,
			estudio_clave=estudio_clave,
			headed=headed,
		)

	# 10. Output dir con fecha
	periodo_str = f'{anio:04d}-{mes:02d}'
	output_dir = Path('storage') / periodo_str

	# 11. PdfGenerator con output_dir dinámico
	pdf_gen = PdfGenerator()

	# 12. Procesar pipeline
	typer.echo(f'── {cliente.nombre or cliente.cuit} ({cliente.cuit}) ──')
	resultado = _procesar_cliente_pipeline(
		cliente=cliente,
		token=token,
		sign=sign,
		engine=engine,
		pdf_gen=pdf_gen,
		mes=mes,
		anio=anio,
		browser=browser,
		with_deuda=tasks['with_deuda'],
		with_facilidades=tasks['with_facilidades'],
		with_registro=tasks['with_registro'],
		with_iibb=tasks['with_iibb'],
		send_email=False,  # Preguntamos después
		config=config,
		output_dir=output_dir,  # Nuevo parámetro
	)

	# 13. Preguntar email
	if resultado.get('pdf') and not resultado.get('error'):
		typer.echo()
		if typer.confirm('¿Enviar email al cliente?', default=False):
			if cliente.email:
				typer.echo(f'Enviando email a {cliente.email} ...')
				sender = EmailSender(config.smtp)
				ok = sender.enviar(cliente, resultado['pdf_path'], mes, anio)
				typer.echo(f'Email: {"✅" if ok else "❌"}')
			else:
				typer.echo('⚠️  Sin email configurado para este cliente')

	# 14. Resumen
	typer.echo()
	typer.echo('═' * 50)
	if resultado.get('error'):
		typer.echo(f'❌ {resultado["error"]}')
	elif resultado.get('pdf'):
		typer.echo('✅ Informe generado exitosamente')
		if resultado.get('pdf_path'):
			typer.echo(f'📄 {resultado["pdf_path"]}')
	else:
		typer.echo('⚠️  Informe incompleto — no se pudo generar el PDF')
		if resultado.get('pdf_path'):
			typer.echo(f'📄 {resultado["pdf_path"]}')
	typer.echo('═' * 50)


def main() -> None:
	"""Entry point for ``python -m fiscal_agent``."""
	app()
