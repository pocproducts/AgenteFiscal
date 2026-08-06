"use client";

import { useMemo } from "react";
import { KpiRow } from "@/components/dashboard/kpi-row";
import { RecentActivityTable } from "@/components/dashboard/recent-activity-table";
import { VolumeChart } from "@/components/dashboard/volume-chart";
import { useAgentSidebar } from "@/hooks/use-agent-sidebar";
import { deriveKpisFromSessions } from "@/lib/dashboard/derive";
import { useLanguage } from "@/lib/i18n";

export function DashboardView() {
  const { t } = useLanguage();
  const dict = t.panel.pages.home;
  const { allSessions } = useAgentSidebar();

  const kpis = useMemo(
    () => deriveKpisFromSessions(allSessions),
    [allSessions]
  );

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-6">
      <KpiRow dict={dict.kpis} kpis={kpis} />
      <VolumeChart dict={dict.volume} sessions={allSessions} />
      <RecentActivityTable dict={dict.recentActivity} sessions={allSessions} />
    </div>
  );
}
