"use client";

import { useAuth } from "@clerk/nextjs";

/**
 * Namespaces a client-local SWR cache key by the active Clerk organization.
 * SWR's default cache is a single global Map for the whole tab; switching
 * tenants via OrganizationSwitcher is a client-side transition (no full
 * reload), so an un-namespaced key would keep serving the previous tenant's
 * cached data until its own revalidation fires. Returns null while the org
 * isn't resolved yet, which defers the read/fetch (SWR convention) instead of
 * flashing stale or wrong-tenant data.
 */
export function useTenantKey(key: string | null): string | null {
  const { orgId, isLoaded } = useAuth();

  if (!(isLoaded && orgId && key)) {
    return null;
  }

  return `${orgId}:${key}`;
}
