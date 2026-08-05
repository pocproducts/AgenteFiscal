import { tool } from "ai";
import { z } from "zod";

const cuitSchema = z.object({
  cuit: z
    .string()
    .min(11)
    .max(11)
    .describe("CUIT del contribuyente (11 dígitos)"),
});

const emailSchema = z.object({
  email: z.string().email().describe("Dirección de correo electrónico"),
});

// ─────────────────────────────────────────────
// Standalone execute functions (called directly
// from route.ts without going through the LLM)
// ─────────────────────────────────────────────

export async function ejecutarConsultaArca(cuit: string) {
  // TODO: Replace with real MCP call → ARCA (ex-AFIP) consulta de obligaciones
  return {
    cuit,
    denominacion: "EMPRESA DE PRUEBA S.A.",
    condicionFiscal: "Responsable Inscripto",
    obligaciones: [
      {
        impuesto: "IVA",
        codigo: "030",
        estado: "Activo",
        periodicidad: "Mensual",
        vencimientoProximo: "2025-07-21",
      },
      {
        impuesto: "Impuesto a las Ganancias - Personas Jurídicas",
        codigo: "011",
        estado: "Activo",
        periodicidad: "Anual",
        vencimientoProximo: "2025-10-15",
      },
      {
        impuesto: "Bienes Personales",
        codigo: "006",
        estado: "Activo",
        periodicidad: "Anual",
        vencimientoProximo: "2025-06-30",
      },
      {
        impuesto: "Monotributo",
        codigo: "020",
        estado: "Inactivo",
        periodicidad: "—",
        vencimientoProximo: null,
      },
    ],
    fuente: "ARCA (ex-AFIP)",
  };
}

export async function ejecutarSistemaRegistral(cuit: string) {
  // TODO: Replace with real MCP call → Sistema Registral ARCA
  return {
    cuit,
    razonSocial: "EMPRESA DE PRUEBA S.A.",
    tipoPersoneria: "Jurídica",
    formaJuridica: "Sociedad Anónima",
    fechaInscripcionAFIP: "2010-03-15",
    actividadPrincipal: {
      codigo: "620100",
      descripcion:
        "Servicios de consultores en informática y suministros de programas de informática",
    },
    actividadesSecundarias: [
      {
        codigo: "620200",
        descripcion:
          "Consultoría informática y actividades de gestión de instalaciones informáticas",
      },
    ],
    domicilioFiscal: {
      calle: "Av. Colón",
      numero: "1234",
      localidad: "Córdoba Capital",
      provincia: "Córdoba",
      codigoPostal: "X5000EPZ",
    },
    estadoDomicilio: "Verificado",
    fuente: "Sistema Registral ARCA",
  };
}

export async function ejecutarMisFacilidades(cuit: string) {
  // TODO: Replace with real MCP call → Mis Facilidades ARCA
  return {
    cuit,
    planesActivos: [
      {
        nroPlan: "MF-2024-001247",
        regimen: "Moratoria 2024 — Ley 27.737",
        periodoDeuda: "2020-01 a 2023-12",
        totalDeudaConsolidada: 185_000,
        cuotasPagadas: 3,
        cuotasTotales: 12,
        montoCuotaActual: 15_416.67,
        proximoVencimientoCuota: "2025-07-01",
        estadoPlan: "Al día",
        porcentajeCumplimiento: 25,
      },
    ],
    planesFinalizados: [],
    planesCaducos: [],
    fuente: "Mis Facilidades — ARCA (ex-AFIP)",
  };
}

export async function ejecutarDeudaVencimientos(cuit: string) {
  // TODO: Replace with real MCP call → Deuda y vencimientos ARCA
  return {
    cuit,
    saldoTotal: 165_200,
    deudasVencidas: [
      {
        impuesto: "IVA",
        periodo: "05/2025",
        tipo: "Declaración Jurada",
        montoOriginal: 45_200,
        interes: 3200,
        total: 48_400,
        fechaVencimiento: "2025-06-20",
        estadoCobranza: "Intimado",
      },
    ],
    deudasPendientes: [
      {
        impuesto: "Impuesto a las Ganancias",
        periodo: "2024",
        tipo: "Declaración Jurada Anual",
        montoOriginal: 120_000,
        interes: 0,
        total: 120_000,
        fechaVencimiento: "2025-10-15",
        estadoCobranza: "Sin intimación",
      },
    ],
    enJuicioEjecucion: false,
    fuente: "ARCA (ex-AFIP) — Deuda y Vencimientos",
  };
}

export async function ejecutarRentasCordoba(cuit: string) {
  // TODO: Replace with real MCP call → Rentas Córdoba IIBB
  return {
    cuit,
    inscripcionIIBB: {
      numero: "903-123456-7",
      tipo: "Convenio Multilateral",
      fechaInscripcion: "2010-04-01",
      estado: "Activo",
    },
    actividades: [
      {
        codigo: "620100",
        descripcion: "Servicios de informática",
        alicuota: "3.5%",
        jurisdiccion: "Córdoba",
      },
    ],
    declaracionesJuradas: {
      ultimaDeclarada: "05/2025",
      estadoCuenta: "Sin deuda",
      saldoAFavor: 2300,
    },
    certificadoExencion: null,
    fuente: "Rentas Córdoba — IIBB",
  };
}

export async function ejecutarCalendarioVencimientosArca(cuit: string) {
  // TODO: Replace with real MCP call → Calendario de vencimientos ARCA
  return {
    cuit,
    periodo: "Julio — Diciembre 2025",
    vencimientos: [
      {
        fecha: "2025-07-01",
        obligacion: "Mis Facilidades — Cuota 4/12",
        importe: 15_416.67,
        estado: "Próximo",
      },
      {
        fecha: "2025-07-21",
        obligacion: "IVA — DDJJ 06/2025",
        importe: null,
        estado: "Pendiente declarar",
      },
      {
        fecha: "2025-08-21",
        obligacion: "IVA — DDJJ 07/2025",
        importe: null,
        estado: "Pendiente declarar",
      },
      {
        fecha: "2025-09-22",
        obligacion: "IVA — DDJJ 08/2025",
        importe: null,
        estado: "Pendiente declarar",
      },
      {
        fecha: "2025-10-01",
        obligacion: "Mis Facilidades — Cuota 5/12",
        importe: 15_416.67,
        estado: "Futuro",
      },
      {
        fecha: "2025-10-15",
        obligacion: "Ganancias — DDJJ Anual 2024",
        importe: 120_000,
        estado: "Pendiente declarar",
      },
      {
        fecha: "2025-10-21",
        obligacion: "IVA — DDJJ 09/2025",
        importe: null,
        estado: "Pendiente declarar",
      },
    ],
    fuente: "Calendario Fiscal ARCA (ex-AFIP)",
  };
}

export async function ejecutarInformeFiscal(cuit: string) {
  // El informe concentra y resume la información de otras herramientas
  return {
    cuit,
    metadata: {
      idReporte: `REP-${Math.floor(Math.random() * 100_000)}`,
      fechaGeneracion: new Date().toISOString(),
      scoreRiesgoFiscal: 15, // 0-100, bajo es mejor
    },
    resumenCumplimiento: [
      {
        area: "Impuestos Nacionales",
        estado: "Al día",
        observaciones: "Sin deudas exigibles",
      },
      {
        area: "Agentes de Retención",
        estado: "Observado",
        observaciones: "Pendiente DDJJ 05/2025",
      },
      {
        area: "Impuestos Provinciales",
        estado: "Al día",
        observaciones: "Saldo a favor en IIBB",
      },
    ],
    inconsistenciasDetectadas: [
      "Diferencia entre IVA Ventas y Facturación Electrónica en periodo 04/2025.",
      "Acreditaciones bancarias superiores a ingresos declarados en un 12%.",
    ],
    fuente: "Sistema de Inteligencia Fiscal — Informe Consolidado",
  };
}

export async function ejecutarEnviarMail(cuit: string, email?: string) {
  return {
    cuit,
    transaccion: {
      idEnvio: `MAIL-${Math.floor(Math.random() * 999_999)}`,
      emailDestino: email ?? "usuario@ejemplo.com",
      timestamp: new Date().toISOString(),
      intentos: 1,
    },
    archivoAdjunto: {
      nombre: `Reporte_Fiscal_Consolidado_${cuit}.pdf`,
      tamaño: "2.4 MB",
      hashSeguridad: "6f5a4e3d2c1b0a9f8e7d6c5b4a3f2e1d",
    },
    servidorSalida: "mail.fiscalis.arca.gob.ar (SMTP)",
    estado: email ? "Enviado con éxito" : "Simulando carga de servidor",
    mensaje: email
      ? `Reporte enviado satisfactoriamente a ${email}`
      : "Prueba de mockup del servicio de correos.",
  };
}

// ─────────────────────────────────────────────
// Command name → executor mapping
// Keys must be the slash-command name lowercased
// ─────────────────────────────────────────────

export const FISCAL_COMMAND_MAP: Record<
  string,
  (cuit: string, ...args: any[]) => Promise<unknown>
> = {
  consultaarca: ejecutarConsultaArca,
  sistemaregistral: ejecutarSistemaRegistral,
  misfacilidades: ejecutarMisFacilidades,
  deudavencimientos: ejecutarDeudaVencimientos,
  rentascordoba: ejecutarRentasCordoba,
  calendariovencimientosarca: ejecutarCalendarioVencimientosArca,
  informefiscal: ejecutarInformeFiscal,
  enviarmail: ejecutarEnviarMail,
};

// ─────────────────────────────────────────────
// Tool definitions for future LLM integration
// ─────────────────────────────────────────────

export const enviarMail = tool({
  description: "Envía el reporte fiscal consolidado por correo electrónico.",
  inputSchema: emailSchema,
  execute: async (input) => ejecutarEnviarMail("—", input.email),
});

export const consultaArca = tool({
  description:
    "Consulta las obligaciones impositivas vigentes en ARCA (ex-AFIP) dado un CUIT.",
  inputSchema: cuitSchema,
  execute: async (input) => ejecutarConsultaArca(input.cuit),
});

export const sistemaRegistral = tool({
  description:
    "Obtiene datos de inscripción del Sistema Registral de ARCA dado un CUIT.",
  inputSchema: cuitSchema,
  execute: async (input) => ejecutarSistemaRegistral(input.cuit),
});

export const misFacilidades = tool({
  description:
    "Consulta los planes de pago activos en Mis Facilidades (ARCA) dado un CUIT.",
  inputSchema: cuitSchema,
  execute: async (input) => ejecutarMisFacilidades(input.cuit),
});

export const deudaVencimientos = tool({
  description:
    "Obtiene la deuda vencida y próximos vencimientos de ARCA dado un CUIT.",
  inputSchema: cuitSchema,
  execute: async (input) => ejecutarDeudaVencimientos(input.cuit),
});

export const rentasCordoba = tool({
  description: "Consulta el estado de IIBB en Rentas Córdoba dado un CUIT.",
  inputSchema: cuitSchema,
  execute: async (input) => ejecutarRentasCordoba(input.cuit),
});

export const calendarioVencimientosArca = tool({
  description:
    "Obtiene el calendario de vencimientos fiscales de ARCA para los próximos meses dado un CUIT.",
  inputSchema: cuitSchema,
  execute: async (input) => ejecutarCalendarioVencimientosArca(input.cuit),
});
