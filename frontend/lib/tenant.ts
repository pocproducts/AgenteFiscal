export function tenantKey(
  orgId: string | null | undefined,
  userId: string | null | undefined,
): string | null {
  if (orgId) {
    return orgId;
  }
  return userId ? `personal:${userId}` : null;
}

export const isPersonalTenant = (key: string | null): boolean =>
  !!key && key.startsWith("personal:");