"""PDF calendar generator using ReportLab — portrait multi-page layout.

Generates a professional A4 portrait PDF with:

1. **Cover page** — title, description + client info
2. **WebService page** — Obligaciones Registrales with matched importes
3. **Calendar page** — monthly due dates from Rules Engine + observations
4. **Deuda page** — structured debt details from ARCA (ctacte.cloud)
5. **Planes page** — Mis Facilidades ARCA payment plans
6. **Registro page** — IIBB + tax registry info
7. *(optional)* Rentas Córdoba placeholder

Filename pattern: ``Calendario_{CUIT}_{YYYY-MM}.pdf``
Output directory: ``storage/calendarios/``
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
	Flowable,
	PageBreak,
	Paragraph,
	SimpleDocTemplate,
	Spacer,
	Table,
	TableStyle,
)

from agente_fiscal.domain.models import (
	DeudaDetail,
	DeudaItem,
	DeudaOutput,
	FacilidadDatosPlan,
	FacilidadPlan,
	FacilidadPlanCuota,
	FacilidadProximoVencimiento,
	IIBBCuotaVencida,
	RegistroActividad,
	RegistroDomicilio,
	RegistroIIBBJurisdiccion,
	RegistroImpuesto,
	RegistroOutput,
	RegistroPuntoVenta,
	RentasCordobaMatching,
	Vencimiento,
	VencimientoDeuda,
)

# ─── Constants ─────────────────────────────────────────────────────────────────

STORAGE_DIR = Path(__file__).resolve().parent.parent / 'storage' / 'calendarios'
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
COLOR_PRIMARY = colors.HexColor('#1a1a2e')
COLOR_ACCENT = colors.HexColor('#16213e')
COLOR_HEADER_BG = colors.HexColor('#e8e8e8')
COLOR_ROW_ALT = colors.HexColor('#f5f5f5')
# Portrait A4: 210mm x 297mm


class _HeaderMarker(Flowable):
	"""Flowable marker que actualiza el header activo antes de un PageBreak.

	Se coloca ANTES del PageBreak para que la página SIGUIENTE
	herede el título. Así funciona correctamente aunque una sección
	ocupe múltiples páginas (el header no cambia hasta el próximo marker).
	"""

	def __init__(self, generator: 'PdfGenerator', title: str) -> None:
		Flowable.__init__(self)
		self._gen = generator
		self._title = title
		self.width = 0
		self.height = 0

	def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
		return (0, 0)  # no ocupa espacio

	def draw(self) -> None:
		self._gen._current_header = self._title


class PdfGenerator:
	"""Genera PDF A4 portrait con portada, calendario fiscal y datos de ARCA."""

	def __init__(self, output_dir: Path | str | None = None) -> None:
		"""Init generator.

		Args:
			output_dir: Custom output directory. Defaults to ``storage/calendarios/``.
		"""
		self.output_dir = Path(output_dir) if output_dir else STORAGE_DIR
		self.output_dir.mkdir(parents=True, exist_ok=True)
		self._current_header: str = ''

	def generar(
		self,
		nombre: str,
		cuit: str,
		vtos: List[Vencimiento],
		mes: int,
		anio: int,
		observaciones: Optional[List[str]] = None,
		deuda: Optional[DeudaOutput] = None,
		rentas_matching: Optional[RentasCordobaMatching] = None,
		output_dir: Optional[Path] = None,
	) -> Path:
		"""Generate the portrait PDF.

		Pages:
		  1. Cover — title, description + client info
		  2. WebService — Obligaciones Registrales (detalle con importes)
		  3. Calendario de Vencimientos — due dates from Rules Engine
		  4. Detalle de Deuda — ARCA (ctacte.cloud)
		  5. Planes de Pago — Mis Facilidades ARCA
		  6. Registro Tributario — IIBB e Impuestos
		  7. (opcional) Rentas Córdoba placeholder

		Args:
			nombre: Client name (razon social).
			cuit: CUIT without hyphens.
			vtos: List of due dates from Rules Engine.
			mes: Month number (1-12).
			anio: Year (e.g. 2026).
			observaciones: Optional list of informational obligations.
			deuda: Optional DeudaOutput from Composio Browser extraction.
			rentas_matching: Optional RentasCordobaMatching result.
			    If ``requiere_integracion`` is True, a placeholder page
			    for Rentas Córdoba integration is added to the PDF.

		Returns:
			Path to the generated PDF file.
		"""
		filename = f'Calendario_{cuit}_{anio:04d}-{mes:02d}.pdf'
		dest = output_dir if output_dir is not None else self.output_dir
		if output_dir is not None:
			dest.mkdir(parents=True, exist_ok=True)
		filepath = dest / filename

		doc = SimpleDocTemplate(
			str(filepath),
			pagesize=A4,
			topMargin=1.8 * cm,  # más espacio para el header
			bottomMargin=1.8 * cm,  # más espacio para el footer
			leftMargin=2 * cm,
			rightMargin=2 * cm,
		)

		# ── Callback canvas: header (activo vía _HeaderMarker) + footer ──
		def _on_page(canvas: object, doc: object) -> None:
			"""Dibuja header (si hay título activo) y footer."""
			_canvas = canvas
			_canvas.saveState()
			hdr = self._current_header
			if hdr:
				_canvas.setStrokeColor(COLOR_ACCENT)
				_canvas.setLineWidth(0.5)
				_canvas.line(2 * cm, A4[1] - 1.65 * cm, A4[0] - 2 * cm, A4[1] - 1.65 * cm)
				_canvas.setFillColor(COLOR_PRIMARY)
				_canvas.setFont('Helvetica-Bold', 8)
				_canvas.drawString(2 * cm, A4[1] - 1.45 * cm, hdr)
			# Footer
			_canvas.setStrokeColor(colors.HexColor('#cccccc'))
			_canvas.setLineWidth(0.5)
			_canvas.line(2 * cm, 1.4 * cm, A4[0] - 2 * cm, 1.4 * cm)
			_canvas.setFillColor(colors.HexColor('#888888'))
			_canvas.setFont('Helvetica', 7)
			_canvas.drawCentredString(A4[0] / 2, 0.9 * cm, 'VERTICAL AI | Agente Fiscal')
			_canvas.restoreState()

		story: list = []
		styles = getSampleStyleSheet()

		# ═══════════════════════════════════════════════════════════════════════
		# PAGE 1 — PORTADA (solo título + descripción + contribuyente)
		# ═══════════════════════════════════════════════════════════════════════
		self._current_header = ''  # cover no lleva header
		self._build_cover(story, styles, nombre, cuit, mes, anio)

		# ═══════════════════════════════════════════════════════════════════════
		# PAGE 2 — WEBSERVICE (Obligaciones Registrales con importes matched)
		# ═══════════════════════════════════════════════════════════════════════
		story.append(_HeaderMarker(self, 'Calendario de Vencimientos'))
		story.append(PageBreak())
		self._build_detalle(story, styles, vtos, cuit, mes, anio, deuda=deuda)

		# ═══════════════════════════════════════════════════════════════════════
		# PAGE 3 — CALENDARIO DE VENCIMIENTOS
		# ═══════════════════════════════════════════════════════════════════════
		story.append(_HeaderMarker(self, 'Obligaciones Registrales'))
		story.append(PageBreak())
		self._build_calendar_table(story, styles, vtos, observaciones)

		# ═══════════════════════════════════════════════════════════════════════
		# PAGE 4 — DETALLE DE DEUDA (ARCA / ctacte.cloud)
		# ═══════════════════════════════════════════════════════════════════════
		if deuda is not None:
			story.append(_HeaderMarker(self, 'Detalle de Deuda — ARCA'))
			story.append(PageBreak())
			self._build_deuda_tables(story, styles, deuda)

		# ═══════════════════════════════════════════════════════════════════════
		# PAGE 5 — PLANES DE PAGO (Mis Facilidades ARCA)
		# ═══════════════════════════════════════════════════════════════════════
		if deuda is not None and deuda.facilidades:
			story.append(_HeaderMarker(self, 'Planes de Pago — Mis Facilidades'))
			story.append(PageBreak())
			self._build_facilidades_tables(story, styles, deuda.facilidades)

		# ═══════════════════════════════════════════════════════════════════════
		# PAGE 6 — REGISTRO TRIBUTARIO (IIBB + impuestos)
		# ═══════════════════════════════════════════════════════════════════════
		if deuda is not None and (deuda.registro or rentas_matching):
			story.append(_HeaderMarker(self, 'Registro Tributario — IIBB e Impuestos'))
			story.append(PageBreak())
			self._build_registro_tables(story, styles, deuda.registro, rentas_matching=rentas_matching)

		# ═══════════════════════════════════════════════════════════════════════
		# PAGE 7 — RENTAS CÓRDOBA PLACEHOLDER (opcional)
		# ═══════════════════════════════════════════════════════════════════════
		if rentas_matching and rentas_matching.requiere_integracion:
			story.append(_HeaderMarker(self, 'Rentas Córdoba'))
			story.append(PageBreak())
			self._build_rentas_cordoba_placeholder(story, styles, rentas_matching)

		# ── Build ────────────────────────────────────────────────────────────
		doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
		return filepath

	# ── Page builders ──────────────────────────────────────────────────────────

	def _build_cover(
		self,
		story: list,
		styles: object,
		nombre: str,
		cuit: str,
		mes: int,
		anio: int,
	) -> None:
		"""Page 1: Cover — title, description, client info. NO calendar on this page."""
		story.append(Spacer(1, 1 * cm))

		# ── Main title ───────────────────────────────────────────────────────
		cover_title = ParagraphStyle(
			'CoverTitle',
			parent=styles['Title'],
			fontName='Helvetica-Bold',
			fontSize=20,
			textColor=COLOR_PRIMARY,
			spaceAfter=3 * mm,
			alignment=1,
		)
		story.append(Paragraph('Agente Fiscal', cover_title))

		cover_sub = ParagraphStyle(
			'CoverSub',
			parent=styles['Normal'],
			fontName='Helvetica',
			fontSize=11,
			textColor=COLOR_ACCENT,
			spaceAfter=6 * mm,
			alignment=1,
		)
		story.append(
			Paragraph(
				'Agente inteligente para estudios contables argentinos',
				cover_sub,
			)
		)

		# ── Separator ────────────────────────────────────────────────────────
		sep_style = ParagraphStyle(
			'SepStyle',
			parent=styles['Normal'],
			fontSize=8,
			textColor=colors.HexColor('#cccccc'),
			spaceAfter=4 * mm,
			alignment=1,
		)
		story.append(Paragraph('━' * 50, sep_style))

		# ── Solution description (compact) ───────────────────────────────────
		desc_style = ParagraphStyle(
			'CoverDesc',
			parent=styles['Normal'],
			fontName='Helvetica',
			fontSize=9,
			textColor=colors.HexColor('#333333'),
			leading=13,
			spaceAfter=4 * mm,
			alignment=1,
		)
		story.append(
			Paragraph(
				'Solución automatizada que se conecta con ARCA (ex AFIP) para '
				'obtener datos tributarios reales, aplica reglas de negocio '
				'para determinar obligaciones vigentes y genera calendarios '
				'fiscales personalizados.',
				desc_style,
			)
		)

		# ── Client info ──────────────────────────────────────────────────────
		client_style = ParagraphStyle(
			'CoverClient',
			parent=styles['Normal'],
			fontName='Helvetica-Bold',
			fontSize=11,
			textColor=COLOR_ACCENT,
			alignment=1,
			spaceAfter=2 * mm,
		)
		story.append(
			Paragraph(
				f'{nombre} &mdash; CUIT {cuit}',
				client_style,
			)
		)
		period_style = ParagraphStyle(
			'CoverPeriod',
			parent=styles['Normal'],
			fontName='Helvetica',
			fontSize=10,
			textColor=colors.HexColor('#666666'),
			alignment=1,
			spaceAfter=6 * mm,
		)
		story.append(
			Paragraph(
				f'{MESES_ES[mes]} {anio}',
				period_style,
			)
		)

	# ────────────────────────────────────────────────────────────────────────────

	def _build_calendar_table(
		self,
		story: list,
		styles: object,
		vtos: List[Vencimiento],
		observaciones: Optional[List[str]],
	) -> None:
		"""Page 3: Calendar table + observations on its own page."""
		# Título en el header (vía _HeaderMarker)
		story.append(Spacer(1, 2 * mm))

		# ── Table ────────────────────────────────────────────────────────────
		if not vtos:
			empty_style = ParagraphStyle(
				'EmptyStyle',
				parent=styles['Normal'],
				fontName='Helvetica-Oblique',
				fontSize=10,
				textColor=colors.HexColor('#666666'),
				alignment=1,
				spaceBefore=1 * cm,
				spaceAfter=1 * cm,
			)
			story.append(Paragraph('Sin vencimientos este mes', empty_style))
		else:
			table_data = self._build_table_data(vtos)
			table = self._build_table(table_data)
			story.append(table)

		# ── Observations ─────────────────────────────────────────────────────
		if observaciones:
			story.append(Spacer(1, 4 * mm))
			obs_title_style = ParagraphStyle(
				'ObsTitle',
				parent=styles['Normal'],
				fontName='Helvetica-Bold',
				fontSize=8,
				textColor=COLOR_ACCENT,
			)
			story.append(Paragraph('Otras obligaciones del período:', obs_title_style))
			story.append(Spacer(1, 1 * mm))

			obs_style = ParagraphStyle(
				'ObsItem',
				parent=styles['Normal'],
				fontName='Helvetica',
				fontSize=8,
				textColor=colors.HexColor('#555555'),
				leftIndent=12,
			)
			for obs in observaciones:
				story.append(Paragraph(f'• {obs}', obs_style))

	# ────────────────────────────────────────────────────────────────────────────

	def _build_detalle(
		self,
		story: list,
		styles: object,
		vtos: List[Vencimiento],
		cuit: str,
		mes: int,
		anio: int,
		deuda: Optional[DeudaOutput] = None,
	) -> None:
		"""Page 2: WebService — Obligaciones Registrales con importes matched."""
		# Título en el header (vía _HeaderMarker)
		story.append(Spacer(1, 2 * mm))

		cuit_style = ParagraphStyle(
			'DetCuit',
			parent=styles['Normal'],
			fontName='Helvetica',
			fontSize=11,
			textColor=COLOR_ACCENT,
			spaceAfter=6 * mm,
			alignment=1,
		)
		story.append(Paragraph(f'CUIT: {cuit} — {MESES_ES[mes]} {anio}', cuit_style))

		# ── Table ────────────────────────────────────────────────────────────
		sorted_vtos = sorted(vtos, key=lambda v: v.fecha)
		header = ['Vencimiento', 'Importe', 'Concepto / Impuestos', 'Período', 'Obs.']
		rows: List[List[str]] = [header]

		for v in sorted_vtos:
			fecha_str = v.fecha.strftime('%d/%m/%Y') if isinstance(v.fecha, date) else str(v.fecha)
			periodo_str = f'{mes:02d}/{str(anio)[-2:]}'
			importe_str = ''
			if deuda and (deuda.deudas or deuda.saldos):
				importe_val = self._match_importe(v.concepto, deuda)
				if importe_val is not None:
					importe_str = self._format_ars(importe_val)
					logger.warning('   ✓ Match: %s → $ %.2f', v.concepto, importe_val)
				else:
					logger.warning('   ✗ Sin match: %s', v.concepto)
			rows.append([fecha_str, importe_str, v.concepto, periodo_str, ''])

		col_widths = [2.8 * cm, 2.5 * cm, 7.5 * cm, 2.2 * cm, 2 * cm]
		table = Table(rows, colWidths=col_widths, repeatRows=1)

		style_cmds = [
			('BACKGROUND', (0, 0), (-1, 0), COLOR_PRIMARY),
			('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
			('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
			('FONTSIZE', (0, 0), (-1, 0), 9),
			('ALIGN', (0, 0), (-1, -1), 'CENTER'),
			('ALIGN', (0, 0), (2, -1), 'LEFT'),
			('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
			('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
			('TOPPADDING', (0, 0), (-1, -1), 5),
			('BOTTOMPADDING', (0, 0), (-1, -1), 5),
			('LEFTPADDING', (0, 0), (-1, -1), 6),
			('RIGHTPADDING', (0, 0), (-1, -1), 6),
		]
		for i in range(1, len(rows)):
			if i % 2 == 0:
				style_cmds.append(('BACKGROUND', (0, i), (-1, i), COLOR_ROW_ALT))

		table.setStyle(TableStyle(style_cmds))
		story.append(table)

		# ── Detectar tipo de contribuyente ─────────────────────────────────
		tipo_label = self._detectar_tipo(vtos)

		# ── Notas al pie ────────────────────────────────────────────────────
		story.append(Spacer(1, 8 * mm))
		notas_title = ParagraphStyle(
			'NotasTitle',
			parent=styles['Normal'],
			fontName='Helvetica-Bold',
			fontSize=9,
			textColor=COLOR_ACCENT,
		)
		story.append(Paragraph('Notas:', notas_title))
		story.append(Spacer(1, 2 * mm))

		nota_style = ParagraphStyle(
			'NotaItem',
			parent=styles['Normal'],
			fontName='Helvetica',
			fontSize=8,
			textColor=colors.HexColor('#555555'),
			leftIndent=12,
		)

		notas = [
			f'Calendario correspondiente a: {tipo_label}.',
			'A modo informativo, los casilleros que no contienen "importe" corresponderán a declaraciones juradas.',
			'Solicitamos el envío de la información para liquidar '
			'los impuestos, al menos 3 días hábiles antes de su vencimiento.',
		]
		for nota in notas:
			story.append(Paragraph(f'• {nota}', nota_style))

	# ── Página 4: tablas de deuda estructurada ────────────────────────────────

	def _build_deuda_tables(
		self,
		story: list,
		styles: object,
		deuda: DeudaOutput,
	) -> None:
		"""Page 4: Tablas con datos estructurados extraídos de ARCA (ctacte.cloud).

		Dos tablas: vencimientos registrados y deudas pendientes con importes.
		Solo se llama si ``deuda`` no es None.
		"""
		# Título en el header (vía _HeaderMarker)
		story.append(Spacer(1, 2 * mm))

		sub_title = ParagraphStyle(
			'DeudaSubTitle',
			parent=styles['Normal'],
			fontName='Helvetica-Bold',
			fontSize=10,
			textColor=COLOR_ACCENT,
			spaceAfter=3 * mm,
		)
		cell_style = ParagraphStyle(
			'DeudaCell',
			parent=styles['Normal'],
			fontName='Helvetica',
			fontSize=7,
			leading=9,
		)

		# ── Tabla 1: Vencimientos registrados ────────────────────────────
		story.append(Spacer(1, 3 * mm))
		story.append(Paragraph('Vencimientos registrados en ctacte.cloud:', sub_title))

		if deuda.vencimientos:
			header = ['Impuesto', 'Concepto', 'Período', 'Vencimiento', 'Detalle']
			rows: list[list] = [header]
			for v in deuda.vencimientos:
				fv_str = v.fecha_vencimiento.strftime('%d/%m/%Y') if v.fecha_vencimiento else '—'
				rows.append(
					[
						Paragraph(v.impuesto or '—', cell_style),
						Paragraph(v.concepto or '—', cell_style),
						Paragraph(f'{v.periodo}-{v.anticuota}', cell_style),
						Paragraph(fv_str, cell_style),
						Paragraph(v.detalle or '—', cell_style),
					]
				)

			col_widths = [3.5 * cm, 3.5 * cm, 2.5 * cm, 2.5 * cm, 5 * cm]
			table = Table(rows, colWidths=col_widths, repeatRows=1)
			style_cmds = [
				('BACKGROUND', (0, 0), (-1, 0), COLOR_PRIMARY),
				('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
				('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
				('FONTSIZE', (0, 0), (-1, 0), 8),
				('ALIGN', (0, 0), (-1, -1), 'CENTER'),
				('ALIGN', (0, 0), (1, -1), 'LEFT'),
				('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
				('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
				('TOPPADDING', (0, 0), (-1, -1), 3),
				('BOTTOMPADDING', (0, 0), (-1, -1), 3),
				('LEFTPADDING', (0, 0), (-1, -1), 4),
				('RIGHTPADDING', (0, 0), (-1, -1), 4),
			]
			for i in range(1, len(rows)):
				if i % 2 == 0:
					style_cmds.append(('BACKGROUND', (0, i), (-1, i), COLOR_ROW_ALT))
			table.setStyle(TableStyle(style_cmds))
			story.append(table)
		else:
			empty_style = ParagraphStyle(
				'DeudaEmpty',
				parent=styles['Normal'],
				fontName='Helvetica-Oblique',
				fontSize=9,
				textColor=colors.HexColor('#666666'),
				spaceBefore=4 * mm,
			)
			story.append(Paragraph('Sin vencimientos registrados', empty_style))

		# ── Tabla 2: Deudas pendientes ───────────────────────────────────
		story.append(Spacer(1, 6 * mm))
		story.append(Paragraph('Deudas pendientes con importe:', sub_title))

		if deuda.deudas:
			header2 = ['Impuesto', 'Concepto', 'Período', 'Vencimiento', 'Importe']
			rows2: list[list] = [header2]
			for d in deuda.deudas:
				fv_str = d.vencimiento.strftime('%d/%m/%Y') if d.vencimiento else '—'
				rows2.append(
					[
						Paragraph(d.impuesto or '—', cell_style),
						Paragraph(d.concepto or '—', cell_style),
						Paragraph(f'{d.periodo}-{d.anticuota}', cell_style),
						Paragraph(fv_str, cell_style),
						Paragraph(self._format_ars(d.saldo) if d.saldo else '—', cell_style),
					]
				)

			col_widths2 = [4.5 * cm, 4.5 * cm, 2.2 * cm, 2.8 * cm, 3 * cm]
			table2 = Table(rows2, colWidths=col_widths2, repeatRows=1)
			style_cmds2 = [
				('BACKGROUND', (0, 0), (-1, 0), COLOR_PRIMARY),
				('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
				('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
				('FONTSIZE', (0, 0), (-1, 0), 8),
				('ALIGN', (0, 0), (-1, -1), 'CENTER'),
				('ALIGN', (0, 0), (1, -1), 'LEFT'),
				('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
				('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
				('TOPPADDING', (0, 0), (-1, -1), 3),
				('BOTTOMPADDING', (0, 0), (-1, -1), 3),
				('LEFTPADDING', (0, 0), (-1, -1), 4),
				('RIGHTPADDING', (0, 0), (-1, -1), 4),
			]
			for i in range(1, len(rows2)):
				if i % 2 == 0:
					style_cmds2.append(('BACKGROUND', (0, i), (-1, i), COLOR_ROW_ALT))
			table2.setStyle(TableStyle(style_cmds2))
			story.append(table2)

			# ── Total si hay más de un ítem ──────────────────────────────
			total = sum(d.saldo for d in deuda.deudas if d.saldo)
			total_style = ParagraphStyle(
				'DeudaTotal',
				parent=styles['Normal'],
				fontName='Helvetica-Bold',
				fontSize=10,
				textColor=COLOR_PRIMARY,
				spaceBefore=4 * mm,
				alignment=2,  # right
			)
			story.append(Paragraph(f'Total deuda: {self._format_ars(total)}', total_style))
		else:
			empty_style = ParagraphStyle(
				'DeudaEmpty2',
				parent=styles['Normal'],
				fontName='Helvetica-Oblique',
				fontSize=9,
				textColor=colors.HexColor('#666666'),
				spaceBefore=4 * mm,
			)
			story.append(Paragraph('Sin deudas pendientes', empty_style))

		# ── Footer ─────────────────────────────────────────────────────
		story.append(Spacer(1, 8 * mm))
		footer_style = ParagraphStyle(
			'DeudaFooter',
			parent=styles['Normal'],
			fontName='Helvetica-Oblique',
			fontSize=7,
			textColor=colors.HexColor('#999999'),
			alignment=1,
		)
		story.append(
			Paragraph(
				'Datos extraídos automáticamente de ctacte.cloud. Los importes '
				'mostrados son los saldos registrados al momento de la extracción.',
				footer_style,
			)
		)

	# ── Página 5: Planes de pago Mis Facilidades ──────────────────────────────

	def _build_facilidades_tables(
		self,
		story: list,
		styles: object,
		facilidades: List[FacilidadPlan],
	) -> None:
		"""Page 5: Tablas con datos de planes de pago de Mis Facilidades ARCA.

		Un bloque por plan: resumen + tabla de cuotas + datos del plan.
		Solo se llama si ``facilidades`` no está vacío.
		"""
		# Título en el header (vía _HeaderMarker)
		story.append(Spacer(1, 2 * mm))

		sub_title = ParagraphStyle(
			'FacSubTitle',
			parent=styles['Normal'],
			fontName='Helvetica-Bold',
			fontSize=10,
			textColor=COLOR_ACCENT,
			spaceAfter=2 * mm,
		)
		plan_title = ParagraphStyle(
			'FacPlanTitle',
			parent=styles['Normal'],
			fontName='Helvetica-Bold',
			fontSize=9,
			textColor=COLOR_PRIMARY,
			spaceBefore=4 * mm,
			spaceAfter=1 * mm,
		)
		cell_style = ParagraphStyle(
			'FacCell',
			parent=styles['Normal'],
			fontName='Helvetica',
			fontSize=7,
			leading=9,
		)
		obs_style = ParagraphStyle(
			'FacObs',
			parent=styles['Normal'],
			fontName='Helvetica-Oblique',
			fontSize=8,
			textColor=colors.HexColor('#555555'),
			spaceBefore=2 * mm,
			spaceAfter=3 * mm,
			alignment=1,
		)

		for i, plan in enumerate(facilidades, 1):
			# ── Resumen del plan ─────────────────────────────────────────
			story.append(Paragraph(f'Plan {i}: {plan.plan or plan.nro_plan}', plan_title))

			resumen = (
				f'<b>Estado:</b> {plan.estado} &nbsp;&nbsp;'
				f'<b>Cuotas:</b> {plan.cuotas_pagas} pagas / {plan.cuotas_impagas} impagas de {plan.cantidad_cuotas} &nbsp;&nbsp;'
				f'<b>Saldo:</b> {self._format_ars(plan.saldo)}'
			)
			if plan.fecha_presentacion:
				resumen += f' &nbsp;&nbsp;<b>Presentación:</b> {plan.fecha_presentacion.strftime("%d/%m/%Y")}'
			if plan.concepto:
				resumen += f' &nbsp;&nbsp;<b>Concepto:</b> {plan.concepto}'

			res_style = ParagraphStyle(
				'FacResumen',
				parent=styles['Normal'],
				fontName='Helvetica',
				fontSize=8,
				textColor=colors.HexColor('#333333'),
				spaceAfter=2 * mm,
			)
			story.append(Paragraph(resumen, res_style))

			# ── Próximo vencimiento ─────────────────────────────────────-
			if plan.proximo_vencimiento:
				pv = plan.proximo_vencimiento
				pv_style = ParagraphStyle(
					'FacPV',
					parent=styles['Normal'],
					fontName='Helvetica-Bold',
					fontSize=9,
					textColor=colors.HexColor('#cc6600'),
					spaceAfter=2 * mm,
				)
				story.append(
					Paragraph(
						f'⚠ Próximo vencimiento: Cuota {pv.nro_cuota} — '
						f'{pv.fecha.strftime("%d/%m/%Y")} por {self._format_ars(pv.total)}',
						pv_style,
					)
				)

			# ── Tabla de cuotas ──────────────────────────────────────────
			if plan.cuotas:
				story.append(Paragraph('Cuotas:', sub_title))
				header = ['N°', 'Capital', 'Int. Financ.', 'Int. Resarc.', 'Total', 'Vencimiento', 'Pago', 'Estado']
				rows: list[list] = [header]
				for c in plan.cuotas:
					rows.append(
						[
							Paragraph(str(c.numero), cell_style),
							Paragraph(self._format_ars(c.capital), cell_style),
							Paragraph(self._format_ars(c.interes_financiero), cell_style),
							Paragraph(self._format_ars(c.interes_resarcitorio), cell_style),
							Paragraph(self._format_ars(c.total), cell_style),
							Paragraph(c.vencimiento.strftime('%d/%m/%Y') if c.vencimiento else '—', cell_style),
							Paragraph(c.fecha_pago.strftime('%d/%m/%Y') if c.fecha_pago else '—', cell_style),
							Paragraph(c.estado, cell_style),
						]
					)

				col_widths = [1.2 * cm, 2.2 * cm, 2.2 * cm, 2.2 * cm, 2.2 * cm, 2.2 * cm, 2.2 * cm, 2 * cm]
				table = Table(rows, colWidths=col_widths, repeatRows=1)
				style_cmds = [
					('BACKGROUND', (0, 0), (-1, 0), COLOR_PRIMARY),
					('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
					('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
					('FONTSIZE', (0, 0), (-1, 0), 7),
					('ALIGN', (0, 0), (-1, -1), 'CENTER'),
					('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
					('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
					('TOPPADDING', (0, 0), (-1, -1), 2),
					('BOTTOMPADDING', (0, 0), (-1, -1), 2),
					('LEFTPADDING', (0, 0), (-1, -1), 3),
					('RIGHTPADDING', (0, 0), (-1, -1), 3),
				]
				for i_row in range(1, len(rows)):
					if i_row % 2 == 0:
						style_cmds.append(('BACKGROUND', (0, i_row), (-1, i_row), COLOR_ROW_ALT))
				table.setStyle(TableStyle(style_cmds))
				story.append(table)
			else:
				empty_style = ParagraphStyle(
					'FacEmpty',
					parent=styles['Normal'],
					fontName='Helvetica-Oblique',
					fontSize=8,
					textColor=colors.HexColor('#666666'),
					spaceBefore=2 * mm,
				)
				story.append(Paragraph('Sin cuotas registradas', empty_style))

			# ── Datos del plan ───────────────────────────────────────────
			if plan.datos_plan:
				story.append(Spacer(1, 2 * mm))
				story.append(Paragraph('Datos del plan:', sub_title))
				dp = plan.datos_plan
				dp_items = []
				if dp.fecha_consolidacion:
					dp_items.append(f'Consolidación: {dp.fecha_consolidacion.strftime("%d/%m/%Y")}')
				if dp.cbu:
					dp_items.append(f'CBU: {dp.cbu}')
				if dp.titular_cbu:
					dp_items.append(f'Titular: {dp.titular_cbu}')

				dp_style = ParagraphStyle(
					'FacDP',
					parent=styles['Normal'],
					fontName='Helvetica',
					fontSize=8,
					textColor=colors.HexColor('#555555'),
					leftIndent=8,
					spaceAfter=1 * mm,
				)
				for item in dp_items:
					story.append(Paragraph(f'• {item}', dp_style))

			# ── Observación ─────────────────────────────────────────────-
			if plan.observacion:
				story.append(Paragraph(plan.observacion, obs_style))

			# Separador entre planes
			if i < len(facilidades):
				sep = ParagraphStyle(
					'FacSep',
					parent=styles['Normal'],
					fontSize=6,
					textColor=colors.HexColor('#dddddd'),
					spaceBefore=2 * mm,
					spaceAfter=2 * mm,
				)
				story.append(Paragraph('─' * 60, sep))

		# Footer
		story.append(Spacer(1, 6 * mm))
		footer_style = ParagraphStyle(
			'FacFooter',
			parent=styles['Normal'],
			fontName='Helvetica-Oblique',
			fontSize=7,
			textColor=colors.HexColor('#999999'),
			alignment=1,
		)
		story.append(
			Paragraph(
				'Planes de pago extraídos automáticamente de Mis Facilidades ARCA. '
				'Los importes mostrados son los saldos registrados al momento de la extracción.',
				footer_style,
			)
		)

	@staticmethod
	def _draw_table(story: list, rows: list, col_widths: list) -> None:
		"""Dibuja una tabla con estilo consistente (encabezado oscuro, filas alternadas, alineación uniforme)."""
		table = Table(rows, colWidths=col_widths, repeatRows=1)
		cmds = [
			('BACKGROUND', (0, 0), (-1, 0), COLOR_PRIMARY),
			('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
			('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
			('FONTSIZE', (0, 0), (-1, 0), 8),
			# Header centrado, datos alineados a izquierda (coherente con el resto del PDF)
			('ALIGN', (0, 0), (-1, 0), 'CENTER'),
			('ALIGN', (0, 1), (-1, -1), 'LEFT'),
			('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
			('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
			('TOPPADDING', (0, 0), (-1, -1), 4),
			('BOTTOMPADDING', (0, 0), (-1, -1), 4),
			('LEFTPADDING', (0, 0), (-1, -1), 5),
			('RIGHTPADDING', (0, 0), (-1, -1), 5),
		]
		for i in range(1, len(rows)):
			if i % 2 == 0:
				cmds.append(('BACKGROUND', (0, i), (-1, i), COLOR_ROW_ALT))
		table.setStyle(TableStyle(cmds))
		story.append(table)

	# ── Página 6: Registro tributario IIBB + impuestos ───────────────────────

	def _build_registro_tables(
		self,
		story: list,
		styles: object,
		registro: Optional[RegistroOutput],
		rentas_matching: Optional[RentasCordobaMatching] = None,
	) -> None:
		"""Page 6: Tablas con provincias IIBB e impuestos registrados + match detection."""
		# Título en el header (vía _HeaderMarker)
		story.append(Spacer(1, 2 * mm))

		sub_title = ParagraphStyle(
			'RegSubTitle',
			parent=styles['Normal'],
			fontName='Helvetica-Bold',
			fontSize=10,
			textColor=COLOR_ACCENT,
			spaceAfter=2 * mm,
		)
		cell_style = ParagraphStyle(
			'RegCell',
			parent=styles['Normal'],
			fontName='Helvetica',
			fontSize=8,
			leading=10,
		)

		# ── Jurisdicción ────────────────────────────────────────────────
		if registro and registro.jurisdiccion:
			j_style = ParagraphStyle(
				'RegJ',
				parent=styles['Normal'],
				fontName='Helvetica-Bold',
				fontSize=10,
				textColor=COLOR_ACCENT,
				spaceAfter=4 * mm,
				alignment=1,
			)
			story.append(Paragraph(f'Jurisdicción: {registro.jurisdiccion}', j_style))

		# ── Tabla: Domicilios ───────────────────────────────────────────
		if registro and registro.domicilios:
			story.append(Paragraph('Domicilios registrados:', sub_title))
			header = ['Tipo', 'Provincia', 'Localidad', 'Dirección', 'CP']
			rows: list[list] = [header]
			for d in registro.domicilios:
				rows.append(
					[
						Paragraph(d.tipo, cell_style),
						Paragraph(d.provincia, cell_style),
						Paragraph(d.localidad, cell_style),
						Paragraph(d.direccion, cell_style),
						Paragraph(d.codigo_postal, cell_style),
					]
				)
			col_widths = [3 * cm, 3.5 * cm, 3.5 * cm, 5 * cm, 2 * cm]
			self._draw_table(story, rows, col_widths)

		# ── Tabla: Actividades ──────────────────────────────────────────
		if registro and registro.actividades:
			story.append(Spacer(1, 4 * mm))
			story.append(Paragraph('Actividades económicas:', sub_title))
			header2 = ['Actividad', 'Código', 'Estado']
			rows2: list[list] = [header2]
			for a in registro.actividades:
				rows2.append(
					[
						Paragraph(a.actividad, cell_style),
						Paragraph(a.codigo, cell_style),
						Paragraph(a.estado, cell_style),
					]
				)
			self._draw_table(story, rows2, [8 * cm, 4 * cm, 3 * cm])

		# ── Tabla: Impuestos ────────────────────────────────────────────
		if registro and registro.impuestos:
			story.append(Spacer(1, 4 * mm))
			story.append(Paragraph('Impuestos registrados:', sub_title))
			header3 = ['Impuesto', 'Categoría', 'Estado']
			rows3: list[list] = [header3]
			for imp in registro.impuestos:
				rows3.append(
					[
						Paragraph(imp.impuesto, cell_style),
						Paragraph(imp.categoria or '—', cell_style),
						Paragraph(imp.estado, cell_style),
					]
				)
			self._draw_table(story, rows3, [6 * cm, 5 * cm, 3 * cm])

		# ── Tabla: Puntos de venta ──────────────────────────────────────
		if registro and registro.puntos_de_venta:
			story.append(Spacer(1, 4 * mm))
			story.append(Paragraph('Puntos de venta:', sub_title))
			header4 = ['Punto', 'Tipo', 'Estado']
			rows4: list[list] = [header4]
			for pv in registro.puntos_de_venta:
				rows4.append(
					[
						Paragraph(pv.punto, cell_style),
						Paragraph(pv.tipo, cell_style),
						Paragraph(pv.estado, cell_style),
					]
				)
			self._draw_table(story, rows4, [4 * cm, 6 * cm, 3 * cm])

		# ── Tabla: Jurisdicciones IIBB ────────────────────────────────
		if registro and registro.iibb_jurisdicciones:
			story.append(Spacer(1, 4 * mm))
			story.append(Paragraph('Jurisdicciones IIBB:', sub_title))
			header5 = ['Provincia', 'Inscripción', 'Estado', 'Match']
			rows5: list[list] = [header5]
			for ij in registro.iibb_jurisdicciones:
				rows5.append(
					[
						Paragraph(ij.provincia, cell_style),
						Paragraph(ij.inscripcion or '—', cell_style),
						Paragraph(ij.estado, cell_style),
						Paragraph('—', cell_style),
					]
				)
			self._draw_table(story, rows5, [4 * cm, 5 * cm, 3 * cm, 2 * cm])

		# ── Tabla: Cuotas vencidas IIBB ──────────────────────────────
		if registro and registro.iibb_cuotas_vencidas:
			story.append(Spacer(1, 4 * mm))
			story.append(Paragraph('Cuotas vencidas — Ingresos Brutos Córdoba:', sub_title))
			header6 = ['Período', 'Vencimiento', 'Saldo', 'Recargo', 'Estado']
			rows6: list[list] = [header6]
			for cv in registro.iibb_cuotas_vencidas:
				saldo_str = f'${cv.saldo:,.2f}' if cv.saldo is not None else '—'
				recargo_str = f'${cv.recargo:,.2f}' if cv.recargo is not None else '—'
				vto_str = cv.vencimiento.strftime('%d/%m/%Y') if cv.vencimiento else '—'
				estado_str = cv.estado
				if cv.estado == 'EN MORA':
					estado_str = '🔴 EN MORA'
				rows6.append(
					[
						Paragraph(cv.periodo, cell_style),
						Paragraph(vto_str, cell_style),
						Paragraph(saldo_str, cell_style),
						Paragraph(recargo_str, cell_style),
						Paragraph(estado_str, cell_style),
					]
				)
			self._draw_table(story, rows6, [3 * cm, 3.5 * cm, 3.5 * cm, 3 * cm, 4 * cm])

		# ── IIBB Match Detection ──────────────────────────────────────────
		if rentas_matching:
			story.append(Spacer(1, 6 * mm))
			iibb_title = ParagraphStyle(
				'RegIIBB',
				parent=styles['Normal'],
				fontName='Helvetica-Bold',
				fontSize=10,
				textColor=COLOR_PRIMARY,
				spaceAfter=2 * mm,
			)
			if rentas_matching.tiene_convenio_multilateral:
				story.append(
					Paragraph(
						'✅ Ingresos Brutos detectado — el contribuyente tiene Convenio Multilateral activo.',
						iibb_title,
					)
				)
				if rentas_matching.tiene_iibb_cordoba:
					cba_style = ParagraphStyle(
						'RegCBA',
						parent=styles['Normal'],
						fontName='Helvetica',
						fontSize=9,
						textColor=colors.HexColor('#555555'),
						leftIndent=8,
						spaceAfter=1 * mm,
					)
					story.append(
						Paragraph(
							'  • Registrado en IIBB Córdoba',
							cba_style,
						)
					)

		# Footer
		story.append(Spacer(1, 6 * mm))
		footer_style = ParagraphStyle(
			'RegFooter',
			parent=styles['Normal'],
			fontName='Helvetica-Oblique',
			fontSize=7,
			textColor=colors.HexColor('#999999'),
			alignment=1,
		)
		story.append(
			Paragraph(
				'Datos de registro tributario extraídos automáticamente de ARCA.',
				footer_style,
			)
		)

	# ── Rentas Córdoba Placeholder ─────────────────────────────────────────────

	def _build_rentas_cordoba_placeholder(
		self,
		story: list,
		styles: object,
		matching: RentasCordobaMatching,
	) -> None:
		"""Page 7: Placeholder for Rentas Córdoba integration (en desarrollo)."""
		# Título en el header (vía _HeaderMarker)
		story.append(Spacer(1, 2 * mm))

		body_style = ParagraphStyle(
			'RCBody',
			parent=styles['Normal'],
			fontName='Helvetica',
			fontSize=11,
			leading=16,
			alignment=1,
			spaceAfter=1.5 * cm,
		)
		story.append(
			Paragraph(
				'El contribuyente tiene Convenio Multilateral IIBB y está registrado '
				'en IIBB Córdoba. La integración automática con Rentas Córdoba '
				'está en desarrollo.<br/><br/>'
				'Mientras tanto, podés consultar la deuda y vencimientos provinciales '
				'ingresando al portal oficial:',
				body_style,
			)
		)

		link_style = ParagraphStyle(
			'RCLink',
			parent=styles['Normal'],
			fontName='Helvetica',
			fontSize=13,
			textColor=colors.HexColor('#0066cc'),
			alignment=1,
			spaceAfter=1.5 * cm,
		)
		story.append(Paragraph(f'<a href="{matching.url}">{matching.url}</a>', link_style))

		if matching.observacion:
			obs_style = ParagraphStyle(
				'RCObs',
				parent=styles['Normal'],
				fontName='Helvetica-Oblique',
				fontSize=9,
				textColor=colors.HexColor('#666666'),
				alignment=1,
			)
			story.append(Paragraph(matching.observacion, obs_style))

	# ── Tipo detection ─────────────────────────────────────────────────────────

	@staticmethod
	def _detectar_tipo(vtos: List[Vencimiento]) -> str:
		"""Inferir tipo de contribuyente desde los conceptos de vencimientos.

		Se usa para la observación de la página 3. No requiere lógica externa.
		"""
		for v in vtos:
			c = v.concepto
			if 'IVA' in c or 'Ganancias Sociedades' in c:
				return 'Responsable Inscripto'
		for v in vtos:
			if 'Monotributo' in v.concepto:
				return 'Monotributista'
		for v in vtos:
			if 'Autónomos' in v.concepto:
				return 'Autónomo'
		return 'No identificado'

	# ── Matching helpers ───────────────────────────────────────────────────────

	@staticmethod
	def _match_importe(concepto: str, deuda: Optional[DeudaOutput]) -> Optional[float]:
		"""Fuzzy keyword match entre concepto de Vencimiento y deuda extraída.

		Busca intersección de tokens (palabras) entre ambos conceptos.
		Prioriza formato nuevo (``DeudaDetail.saldo``), fallback a legacy (``DeudaItem.importe``).
		Retorna el importe del primer ítem que matchee, o None si no hay match.
		"""
		if not deuda:
			return None
		keywords = set(re.findall(r'\w+', concepto.lower()))

		# Nuevo formato: deuda.deudas[].concepto → .saldo
		for item in deuda.deudas:
			item_words = set(re.findall(r'\w+', item.concepto.lower()))
			if keywords & item_words:
				return item.saldo

		# Legacy: deuda.saldos[].concepto → .importe
		for item in deuda.saldos:
			item_words = set(re.findall(r'\w+', item.concepto.lower()))
			if keywords & item_words:
				return item.importe

		return None

	@staticmethod
	def _format_ars(importe: float) -> str:
		"""Formatear importe como moneda argentina: ``$ 75.000,25``."""
		return f'$ {importe:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')

	# ── Table helpers ──────────────────────────────────────────────────────────

	@staticmethod
	def _build_table_data(vtos: List[Vencimiento]) -> List[List[str]]:
		"""Convert vencimientos list to table rows.

		Returns:
			List of [concepto, fecha, estado] rows with header.
		"""
		sorted_vtos = sorted(vtos, key=lambda v: v.fecha)

		header = ['Obligación', 'Vencimiento', 'Día hábil']
		rows: List[List[str]] = [header]

		for v in sorted_vtos:
			fecha_str = v.fecha.strftime('%d/%m/%Y') if isinstance(v.fecha, date) else str(v.fecha)
			estado = 'Sí' if v.es_fecha_habil else 'No'
			rows.append([v.concepto, fecha_str, estado])

		return rows

	@staticmethod
	def _build_table(data: List[List[str]]) -> Table:
		"""Create a styled ReportLab table — matching detalle table style."""
		# Portrait usable width ≈ 17cm (210mm - 2*2cm margins)
		col_widths = [9 * cm, 4.5 * cm, 3.5 * cm]
		table = Table(data, colWidths=col_widths, repeatRows=1)

		style_cmds = [
			# Header row
			('BACKGROUND', (0, 0), (-1, 0), COLOR_PRIMARY),
			('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
			('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
			('FONTSIZE', (0, 0), (-1, 0), 9),
			('ALIGN', (0, 0), (-1, -1), 'CENTER'),
			('ALIGN', (0, 0), (0, -1), 'LEFT'),
			('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
			# Grid
			('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
			('TOPPADDING', (0, 0), (-1, -1), 5),
			('BOTTOMPADDING', (0, 0), (-1, -1), 5),
			('LEFTPADDING', (0, 0), (-1, -1), 6),
			('RIGHTPADDING', (0, 0), (-1, -1), 6),
		]

		# Alternating row colors
		for i in range(1, len(data)):
			if i % 2 == 0:
				style_cmds.append(('BACKGROUND', (0, i), (-1, i), COLOR_ROW_ALT))

		table.setStyle(TableStyle(style_cmds))
		return table
