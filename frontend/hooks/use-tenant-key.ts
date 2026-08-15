"use client";

import { useAuth } from "@clerk/nextjs";

/**
 * Namespaces a client-local SWR cache key by the active Clerk organization.
 * SWR's default cache is a single global Map for the whole tab; switching
 * tenants via OrganizationSwitcher is a client-side transition (no full
 * reload), so an un-namespaced key would keep serving the previous tenant's
 * cached data until its own revalidation fires. Returns null while auth isn't
 * resolved yet, which defers the read/fetch (SWR convention) instead of
 * flashing stale or wrong-tenant data.
 *
 * Personal space: when auth is loaded but no organization is selected (the
 * "/tenant → continuar con mi espacio personal" path), the backend
 * auto-provisions the personal tenant from the user token, so cache keys fall
 * back to a stable `personal` namespace instead of staying null (which would
 * permanently disable tenant-scoped hooks like useProfiles).
 */
export function useTenantKey(key: string | null): string | null {
  const { orgId, isLoaded } = useAuth();

  if (!(isLoaded && key)) {
    return null;
  }

  return `${orgId ?? "personal"}:${key}`;
}
