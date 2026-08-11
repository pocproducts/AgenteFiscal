"use client";

import useSWR from "swr";
import { useTenantKey } from "@/hooks/use-tenant-key";
import type { RemoteBrowserRow } from "@/lib/remote-browser/types";

type RemoteBrowsersFetcher = (
  key: string
) => RemoteBrowserRow[] | Promise<RemoteBrowserRow[]>;

/**
 * Typed data-access hook for the remote-browser table. Today no backend
 * fetcher exists, so `data` is `null` (the table renders a skeleton then the
 * empty card); a real fetcher slots in per module with zero view changes.
 */
export function useRemoteBrowsers(fetcher?: RemoteBrowsersFetcher) {
  const key = useTenantKey("remote-browsers");
  return useSWR<RemoteBrowserRow[] | null>(key, fetcher ?? null, {
    fallbackData: null,
  });
}
