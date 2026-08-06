import { Activity, Bot, DollarSign, type LucideIcon } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import type { DashboardKpis } from "@/lib/dashboard/types";

interface KpiRowDict {
  agentRuns: string;
  browserSessions: string;
  totalSpend: string;
}

function KpiTile({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
}) {
  return (
    <div className="flex flex-col gap-1 border-border/50 sm:border-l sm:pl-5 first:sm:border-l-0 first:sm:pl-0">
      <div className="flex items-center gap-1.5 text-muted-foreground">
        <Icon className="size-3.5" />
        <span className="text-xs font-medium">{label}</span>
      </div>
      <span className="font-mono text-xl font-semibold tracking-tight text-foreground">
        {value}
      </span>
    </div>
  );
}

export function KpiRow({
  kpis,
  dict,
  isLoading = false,
}: {
  kpis: DashboardKpis;
  dict: KpiRowDict;
  isLoading?: boolean;
}) {
  return (
    <div className="grid grid-cols-3 gap-4 rounded-2xl border border-border/50 bg-card/60 p-5 shadow-sm sm:flex sm:items-start sm:gap-8">
      {isLoading ? (
        <>
          <Skeleton className="h-10 w-24" />
          <Skeleton className="h-10 w-24" />
          <Skeleton className="h-10 w-24" />
        </>
      ) : (
        <>
          <KpiTile
            icon={Bot}
            label={dict.agentRuns}
            value={String(kpis.agentRuns)}
          />
          <KpiTile
            icon={Activity}
            label={dict.browserSessions}
            value={String(kpis.browserSessions)}
          />
          <KpiTile
            icon={DollarSign}
            label={dict.totalSpend}
            value={`$${(kpis.totalSpendCents / 100).toFixed(2)}`}
          />
        </>
      )}
    </div>
  );
}
