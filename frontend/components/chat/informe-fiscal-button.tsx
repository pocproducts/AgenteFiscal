"use client";

import { useState } from "react";

export const InformeFiscalButton = ({
  dataEncoded,
}: {
  dataEncoded: string;
}) => {
  const [open, setOpen] = useState(false);
  let reports: Array<{ tool: string; data: any }> = [];
  try {
    // Decode base64 → bytes → UTF-8 so accented fiscal data survives. The old
    // `atob` + JSON.parse path returned latin-1 mojibake for non-ASCII payloads
    // and crashed with "unexpected character at line 1 column 1".
    const binary = atob(dataEncoded);
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    const jsonStr = new TextDecoder().decode(bytes);
    reports = JSON.parse(jsonStr);
  } catch (e) {
    console.error("Failed to parse reports", e);
  }

  const renderNaturalLanguage = (tool: string, data: any) => {
    switch (tool.toLowerCase()) {
      case "consultaarca":
        return (
          <div className="space-y-4 text-sm text-black">
            <p>
              El CUIT <strong>{data.cuit}</strong> pertenece a{" "}
              <strong>{data.denominacion}</strong>, registrado actualmente como{" "}
              <strong>{data.condicionFiscal}</strong>.
            </p>
            <div>
              <p className="font-semibold mb-1">Obligaciones Impositivas:</p>
              <ul className="list-disc pl-5 space-y-1">
                {data.obligaciones.map((ob: any) => (
                  <li key={`obligacion-${ob.impuesto}-${ob.periodicidad}`}>
                    <strong>{ob.impuesto}</strong> ({ob.periodicidad}): Estado{" "}
                    <em>{ob.estado}</em>
                    {ob.vencimientoProximo && (
                      <span>
                        {" "}
                        — Próximo vencimiento el {ob.vencimientoProximo}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        );
      case "sistemaregistral":
        return (
          <div className="space-y-4 text-sm text-black">
            <p>
              La entidad <strong>{data.razonSocial}</strong> es una{" "}
              <strong>{data.formaJuridica}</strong> inscripta desde{" "}
              <strong>{data.fechaInscripcionAFIP}</strong>.
            </p>
            <div>
              <p className="font-semibold mb-1">Actividades Registradas:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>
                  <strong>Principal:</strong>{" "}
                  {data.actividadPrincipal.descripcion}
                </li>
                {data.actividadesSecundarias.map((act: any) => (
                  <li key={`actividad-${act.descripcion}`}>
                    <strong>Secundaria:</strong> {act.descripcion}
                  </li>
                ))}
              </ul>
            </div>
            <p>
              Su domicilio fiscal verificado se encuentra en{" "}
              <strong>
                {data.domicilioFiscal.calle} {data.domicilioFiscal.numero},{" "}
                {data.domicilioFiscal.localidad},{" "}
                {data.domicilioFiscal.provincia}
              </strong>
              .
            </p>
          </div>
        );
      case "misfacilidades":
        return (
          <div className="space-y-4 text-sm text-black">
            <p>Estado en el sistema de facilidades de pago:</p>
            {data.planesActivos.length > 0 ? (
              <ul className="space-y-3">
                {data.planesActivos.map((plan: any) => (
                  <li
                    className="bg-white p-3 rounded border border-gray-200"
                    key={`plan-${plan.nroPlan}`}
                  >
                    <p className="font-semibold">
                      {plan.regimen} (Plan N° {plan.nroPlan})
                    </p>
                    <p>
                      El plan se encuentra <strong>{plan.estadoPlan}</strong>.
                      Se ha pagado la cuota {plan.cuotasPagadas} de{" "}
                      {plan.cuotasTotales} ($
                      {plan.montoCuotaActual.toLocaleString()}).
                    </p>
                    <p>
                      El próximo vencimiento de cuota es el{" "}
                      <strong>{plan.proximoVencimientoCuota}</strong>.
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p>
                No se registran planes de facilidades activos en este momento.
              </p>
            )}
          </div>
        );
      case "deudavencimientos":
        return (
          <div className="space-y-4 text-sm text-black">
            <p>
              El saldo total de deuda registrado es de{" "}
              <strong>${data.saldoTotal.toLocaleString()}</strong>.
            </p>
            {data.deudasVencidas.length > 0 && (
              <div>
                <p className="font-semibold mb-1">Deudas ya vencidas:</p>
                <ul className="list-disc pl-5 space-y-1">
                  {data.deudasVencidas.map((deuda: any) => (
                    <li
                      key={`deuda-vencida-${deuda.impuesto}-${deuda.periodo}`}
                    >
                      {deuda.impuesto} ({deuda.periodo}):{" "}
                      <strong>${deuda.total.toLocaleString()}</strong> (Se
                      encuentra <em>{deuda.estadoCobranza}</em> desde{" "}
                      {deuda.fechaVencimiento})
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {data.deudasPendientes.length > 0 && (
              <div>
                <p className="font-semibold mb-1">
                  Obligaciones pendientes (no vencidas):
                </p>
                <ul className="list-disc pl-5 space-y-1">
                  {data.deudasPendientes.map((deuda: any) => (
                    <li
                      key={`deuda-pendiente-${deuda.impuesto}-${deuda.periodo}`}
                    >
                      {deuda.impuesto} ({deuda.periodo}):{" "}
                      <strong>${deuda.total.toLocaleString()}</strong> a vencer
                      el {deuda.fechaVencimiento}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        );
      case "rentascordoba":
        return (
          <div className="space-y-4 text-sm text-black">
            <p>
              En Rentas de la Provincia de Córdoba, el contribuyente figura bajo
              el <strong>{data.inscripcionIIBB.tipo}</strong> con estado{" "}
              <strong>{data.inscripcionIIBB.estado}</strong>.
            </p>
            <p>
              La última DDJJ informada corresponde a{" "}
              <strong>{data.declaracionesJuradas.ultimaDeclarada}</strong>,
              resultando en{" "}
              <strong>{data.declaracionesJuradas.estadoCuenta}</strong> con un
              saldo a favor de{" "}
              <strong>${data.declaracionesJuradas.saldoAFavor}</strong>.
            </p>
            {data.actividades.length > 0 && (
              <p>
                La actividad gravada es &quot;{data.actividades[0].descripcion}
                &quot; a una alícuota del {data.actividades[0].alicuota}.
              </p>
            )}
          </div>
        );
      case "calendariovencimientosarca":
        return (
          <div className="space-y-4 text-sm text-black">
            <p>
              Detalle de vencimientos para el periodo{" "}
              <strong>{data.periodo}</strong>:
            </p>
            <ul className="space-y-2">
              {data.vencimientos.map((venc: any) => (
                <li
                  className="flex justify-between items-center border-b border-gray-200 pb-2 last:border-0 last:pb-0"
                  key={`vencimiento-${venc.fecha}-${venc.obligacion}`}
                >
                  <span>
                    <strong>{venc.fecha}</strong> — {venc.obligacion}
                  </span>
                  <span className="text-xs px-2 py-1 rounded bg-gray-100 text-black">
                    {venc.estado}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        );
      default:
        return (
          <pre className="overflow-x-auto rounded-xl border border-gray-200 bg-white p-4 text-[11px] leading-snug text-black shadow-inner no-scrollbar">
            <code>{JSON.stringify(data, null, 2)}</code>
          </pre>
        );
    }
  };

  return (
    <div className="mt-4 flex flex-col gap-2">
      <button
        className="flex w-fit h-10 items-center justify-center gap-2 rounded-xl bg-black px-5 text-sm font-medium text-white transition-all hover:opacity-90 active:scale-95 border border-black"
        onClick={() => setOpen(!open)}
        type="button"
      >
        📋 {open ? "Ocultar Informe Fiscal" : "Ver Informe Fiscal Completo ..."}
      </button>

      {open && (
        <div className="mt-2 flex flex-col gap-6 rounded-2xl border border-gray-300 bg-white p-6 shadow-sm overflow-hidden animate-in slide-in-from-top-2 fade-in duration-200">
          <div className="flex items-center justify-between border-b border-gray-300 pb-4">
            <h3 className="text-xl font-semibold tracking-tight text-black">
              Informe Consolidado Completo
            </h3>
          </div>
          <div className="flex flex-col gap-6 max-h-[600px] overflow-y-auto no-scrollbar pr-2">
            {reports.map((report) => (
              <div
                className="rounded-2xl border border-gray-300 bg-white p-5 shadow-sm"
                key={`reporte-${report.tool}`}
              >
                <h4 className="mb-4 text-xs font-bold uppercase tracking-[0.15em] text-black border-b border-gray-200 pb-2">
                  {report.tool}
                </h4>
                {renderNaturalLanguage(report.tool, report.data)}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
