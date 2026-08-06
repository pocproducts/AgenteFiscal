"use client";

import useSWR from "swr";
import type { OverviewSnapshot, RangeKey } from "@/lib/analytics/types";

type OverviewFetcher = (
  key: string
) => OverviewSnapshot | Promise<OverviewSnapshot>;

/**
 * Typed data-access hook for the analytics overview panel. Today no backend
 * fetcher exists, so `data` is `null` (views render the empty state); a real
 * fetcher slots in per module with zero view changes.
 */
export function useAnalyticsOverview(
  range: RangeKey,
  fetcher?: OverviewFetcher
) {
  return useSWR<OverviewSnapshot | null>(
    `analytics-overview:${range}`,
    fetcher ?? null,
    { fallbackData: null }
  );
}
