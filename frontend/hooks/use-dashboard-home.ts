"use client";

import { useMemo } from "react";
import useSWR from "swr";
import { useAgentSidebar } from "@/hooks/use-agent-sidebar";
import {
  buildVolumeSeries,
  deriveKpisFromSessions,
} from "@/lib/dashboard/derive";
import type { DashboardHomeSnapshot } from "@/lib/dashboard/types";

/**
 * Ready-state snapshot for the dashboard home view. KPIs, volume and recent
 * activity are derived synchronously from the real client-local agent sessions
 * (`useAgentSidebar`); the SWR key reserves the slot for a future backend
 * fetcher that would override the derivation.
 */
export function useDashboardHome() {
  const { allSessions } = useAgentSidebar();

  const { data, error } = useSWR<DashboardHomeSnapshot | null>(
    "dashboard-home",
    null,
    { fallbackData: null }
  );

  const derived = useMemo<DashboardHomeSnapshot | null>(() => {
    if (allSessions.length === 0) {
      return null;
    }
    return {
      kpis: deriveKpisFromSessions(allSessions),
      volume: buildVolumeSeries(allSessions, "7d"),
      recent: allSessions,
    };
  }, [allSessions]);

  return { data: data ?? derived, isLoading: false, error };
}
