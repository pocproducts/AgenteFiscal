"use client";

import {
  Calendar,
  ClipboardList,
  Database,
  FileSearch,
  FileText,
  Handshake,
  Mail,
  MapPin,
  Zap,
} from "lucide-react";
import { type ReactNode, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

export type SlashCommand = {
  name: string;
  description: string;
  icon: ReactNode;
  action: string;
  shortcut?: string;
};

export const slashCommands: SlashCommand[] = [
  {
    name: "Todo",
    description: "Ejecutar todas las herramientas fiscales a la vez",
    icon: <Zap className="size-3.5 text-amber-500 fill-amber-500/20" />,
    action: "todo",
  },
  {
    name: "ConsultaArca",
    description: "Obligaciones impositivas en ARCA (ex-AFIP)",
    icon: <FileSearch className="size-3.5" />,
    action: "consultaarca",
  },
  {
    name: "SistemaRegistral",
    description: "Datos de inscripción y constancias registrales",
    icon: <Database className="size-3.5" />,
    action: "sistemaregistral",
  },
  {
    name: "MisFacilidades",
    description: "Planes de pago y moratorias vigentes",
    icon: <Handshake className="size-3.5" />,
    action: "misfacilidades",
  },
  {
    name: "DeudaVencimientos",
    description: "Deuda vencida y próximos vencimientos ARCA",
    icon: <ClipboardList className="size-3.5" />,
    action: "deudavencimientos",
  },
  {
    name: "RentasCordoba",
    description: "Estado de IIBB en Rentas Córdoba",
    icon: <MapPin className="size-3.5" />,
    action: "rentascordoba",
  },
  {
    name: "CalendarioVencimientosArca",
    description: "Calendario fiscal de vencimientos ARCA",
    icon: <Calendar className="size-3.5" />,
    action: "calendariovencimientosarca",
  },
  {
    name: "InformeFiscal",
    description: "Concentrar todas las herramientas ejecutadas",
    icon: <FileText className="size-3.5" />,
    action: "informefiscal",
  },
  {
    name: "EnviarMail",
    description: "Enviar reporte consolidado por mail",
    icon: <Mail className="size-3.5" />,
    action: "enviarmail",
  },
];

type SlashCommandMenuProps = {
  query: string;
  context: string;
  onSelect: (command: SlashCommand) => void;
  onClose: () => void;
  selectedIndex: number;
};

export function SlashCommandMenu({
  query,
  context,
  onSelect,
  onClose: _onClose,
  selectedIndex,
}: SlashCommandMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const filtered = slashCommands.filter((cmd) => {
    const alreadySelected = context
      .toLowerCase()
      .includes(cmd.name.toLowerCase());
    const matchesQuery = cmd.name.toLowerCase().startsWith(query.toLowerCase());
    return !alreadySelected && matchesQuery;
  });

  useEffect(() => {
    const selected = menuRef.current?.querySelector("[data-selected='true']");
    if (selected) {
      selected.scrollIntoView({ block: "nearest" });
    }
  }, []);

  if (filtered.length === 0) {
    return null;
  }

  return (
    <div
      className="absolute top-full left-0 right-0 z-50 mt-2 overflow-hidden rounded-xl border border-border/50 bg-card/95 shadow-[var(--shadow-float)] backdrop-blur-xl"
      ref={menuRef}
    >
      <div className="px-4 py-2.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/40">
        Commands
      </div>
      <div className="max-h-64 overflow-y-auto pb-1 no-scrollbar">
        {filtered.map((cmd, index) => (
          <button
            className={cn(
              "flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors",
              index === selectedIndex ? "bg-muted/70" : "hover:bg-muted/40"
            )}
            data-selected={index === selectedIndex}
            key={cmd.name}
            onClick={() => onSelect(cmd)}
            onMouseDown={(e) => e.preventDefault()}
            type="button"
          >
            <div className="flex size-6 shrink-0 items-center justify-center text-muted-foreground/60">
              {cmd.icon}
            </div>
            <span className="font-mono text-[13px] text-foreground">
              /{cmd.name}
            </span>
            <span className="text-[12px] text-muted-foreground/50">
              {cmd.description}
            </span>
            {cmd.shortcut && (
              <span className="ml-auto text-[11px] text-muted-foreground/30">
                {cmd.shortcut}
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
