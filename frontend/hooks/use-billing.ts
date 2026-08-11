"use client";

import { useCallback, useMemo } from "react";
import useSWR from "swr";
import { useTenantKey } from "@/hooks/use-tenant-key";
import type { BillingPlanId, BillingState } from "@/lib/billing/types";

/**
 * Single source of truth for token balance + contracted plan, shared by the
 * chat header widgets and the billing settings page. Today no backend fetcher
 * exists, so `data` is `null` (widgets render `—`); a real fetcher slots in
 * with zero view changes.
 *
 * `ZERO_BILLING_STATE` is only ever used as the base for optimistic
 * `setPlan`/`addTokens` cache mutations — it is never rendered.
 */
const ZERO_BILLING_STATE: BillingState = {
  tokenBalance: 0,
  usdBalance: 0,
  currentPlan: "Free",
};

type BillingFetcher = (key: string) => BillingState | Promise<BillingState>;

export function useBilling(fetcher?: BillingFetcher) {
  const key = useTenantKey("billing-state");
  const { data, isLoading, error, mutate } = useSWR<BillingState | null>(
    key,
    fetcher ?? null,
    { fallbackData: null }
  );

  const setPlan = useCallback(
    (currentPlan: BillingPlanId) => {
      mutate(
        (prev) => ({ ...(prev ?? ZERO_BILLING_STATE), currentPlan }),
        false
      );
    },
    [mutate]
  );

  const addTokens = useCallback(
    (amount: number) => {
      mutate(
        (prev) => ({
          ...(prev ?? ZERO_BILLING_STATE),
          tokenBalance: (prev ?? ZERO_BILLING_STATE).tokenBalance + amount,
        }),
        false
      );
    },
    [mutate]
  );

  return useMemo(
    () => ({
      data,
      tokenBalance: data?.tokenBalance ?? null,
      usdBalance: data?.usdBalance ?? null,
      currentPlan: data?.currentPlan ?? null,
      isLoading,
      error,
      setPlan,
      addTokens,
    }),
    [data, isLoading, error, setPlan, addTokens]
  );
}
