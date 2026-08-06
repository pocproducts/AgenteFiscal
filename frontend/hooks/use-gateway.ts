"use client";

import useSWR from "swr";
import type { GatewaySnapshot, RangeKey } from "@/lib/analytics/types";

type GatewayFetcher = (
  key: string
) => GatewaySnapshot | Promise<GatewaySnapshot>;

/**
 * Typed data-access hook for the LLM gateway panel. Today no backend fetcher
 * exists, so `data` is `null` (views render the empty state); a real fetcher
 * slots in per module with zero view changes. `isCustom` is kept in the cache
 * key so a future custom-range endpoint can be wired without breaking the
 * `RangeKey` union.
 */
export function useGateway(
  range: RangeKey,
  isCustom = false,
  fetcher?: GatewayFetcher
) {
  return useSWR<GatewaySnapshot | null>(
    `analytics-gateway:${range}:${isCustom}`,
    fetcher ?? null,
    { fallbackData: null }
  );
}
