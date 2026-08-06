"use client";

import { KpiRow } from "@/components/dashboard/kpi-row";
import { RecentActivityTable } from "@/components/dashboard/recent-activity-table";
import { VolumeChart } from "@/components/dashboard/volume-chart";
import { useDashboardHome } from "@/hooks/use-dashboard-home";
import type {
  DashboardHomeSnapshot,
  DashboardKpis,
} from "@/lib/dashboard/types";
import { useLanguage } from "@/lib/i18n";

const ZERO_KPIS: DashboardKpis = {
  agentRuns: 0,
  browserSessions: 0,
  totalSpendCents: 0,
};

export function DashboardView({
  data,
  isLoading,
}: {
  data?: DashboardHomeSnapshot | null;
  isLoading?: boolean;
}) {
  const { t } = useLanguage();
  const dict = t.panel.pages.home;
  const home = useDashboardHome();

  const snapshot = data ?? home.data;
  const loading = isLoading ?? home.isLoading;
  const sessions = snapshot?.recent ?? [];
  const kpis = snapshot?.kpis ?? ZERO_KPIS;

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-6">
      <KpiRow dict={dict.kpis} isLoading={loading} kpis={kpis} />
      <VolumeChart dict={dict.volume} isLoading={loading} sessions={sessions} />
      <RecentActivityTable
        dict={dict.recentActivity}
        isLoading={loading}
        sessions={sessions}
      />
    </div>
  );
}
