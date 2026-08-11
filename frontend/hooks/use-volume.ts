"use client";

import { useMemo } from "react";
import useSWR from "swr";
import { useAgentSidebar } from "@/hooks/use-agent-sidebar";
import { useTenantKey } from "@/hooks/use-tenant-key";
import { buildVolumeSeries } from "@/lib/dashboard/derive";
import type { DashboardRange, VolumePoint } from "@/lib/dashboard/types";

/**
 * Per-range volume/spend series for the dashboard volume chart, bucketed
 * synchronously from real agent sessions. The SWR key reserves the slot for a
 * future backend fetcher that would override the derivation.
 */
export function useVolume(range: DashboardRange) {
  const { allSessions } = useAgentSidebar();
  const key = useTenantKey(`dashboard-volume:${range}`);

  const { data, error } = useSWR<VolumePoint[] | null>(key, null, {
    fallbackData: null,
  });

  const volume = useMemo(
    () => buildVolumeSeries(allSessions, range),
    [allSessions, range]
  );

  return { data: data ?? volume, isLoading: false, error };
}
