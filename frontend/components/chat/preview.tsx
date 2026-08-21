"use client";

import { useRouter } from "next/navigation";

type LoginCard = {
  title: string;
  isNew?: boolean;
  action?: string;
};

const loginCards: LoginCard[] = [
  { title: "Consulta directa con ARCA" },
  { title: "Automatizacion directa en Mis Faculidades" },
  { title: "Obtencion de datalles en Sistema Registral" },
  { title: "Informacion sobre Deudas y Vecimientos" },
  { title: "Ver informe completo", isNew: true, action: "informefiscal" },
  { title: "Enviar mail", isNew: true, action: "enviarmail" },
];

export function Preview() {
  const router = useRouter();

  const handleAction = (query?: string) => {
    const url = query ? `/?query=${encodeURIComponent(query)}` : "/";
    router.push(url);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-tl-2xl bg-background">
      <div className="flex flex-1 flex-col items-center justify-center gap-8 px-8">
        <div className="text-center">
          <h2 className="text-xl font-semibold tracking-tight">
            Genera un Reporte Fiscal
          </h2>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Detalles de impuestos, vencimientos, deudas, planes de pago,
            registro tributario, IIBB Cordoba
          </p>
        </div>

        <div
          className="grid w-full max-w-md grid-cols-2 gap-2"
          data-testid="suggested-actions"
        >
          {loginCards.map((card) => {
            const readOnly = !card.action;
            return (
              <button
                key={card.title}
                type="button"
                disabled={readOnly}
                onClick={readOnly ? undefined : () => handleAction(card.action)}
                className={[
                  "relative rounded-xl border border-border/30 bg-card/20 px-3 py-2.5 text-left text-[11px] leading-relaxed text-muted-foreground/70 transition-all duration-200",
                  readOnly
                    ? "cursor-default"
                    : "hover:border-border/60 hover:bg-card/40 hover:text-muted-foreground",
                  card.isNew ? "ring-1 ring-primary/40" : "",
                ].join(" ")}
              >
                {card.title}
                {card.isNew ? (
                  <span className="absolute -right-1.5 -top-1.5 rounded-full bg-primary px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-primary-foreground">
                    nuevo
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
