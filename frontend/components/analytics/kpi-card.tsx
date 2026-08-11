import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface KpiCardProps {
  label: string;
  value: string;
  sub?: string;
  icon?: LucideIcon;
  iconClassName?: string;
  valueClassName?: string;
}

export function KpiCard({
  label,
  value,
  sub,
  icon: Icon,
  iconClassName,
  valueClassName,
}: KpiCardProps) {
  return (
    <div className="rounded-2xl border border-border/50 bg-card/60 p-5 shadow-sm hover:border-primary/30 hover:shadow-md transition-all duration-300">
      <div className="flex items-start justify-between gap-3">
        <span className="uppercase tracking-wider text-[11px] font-bold text-muted-foreground">
          {label}
        </span>
        {Icon ? (
          <span
            className={cn(
              "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted/60 border border-border/40",
              iconClassName
            )}
          >
            <Icon className="h-4 w-4" />
          </span>
        ) : null}
      </div>
      <div
        className={cn(
          "mt-2 text-xl font-mono font-extrabold tracking-tight text-foreground",
          valueClassName
        )}
      >
        {value}
      </div>
      {sub ? (
        <div className="mt-1 text-xs text-muted-foreground">{sub}</div>
      ) : null}
    </div>
  );
}
