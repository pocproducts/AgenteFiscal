// server-only: never import this from client components.
// Typed, envelope-unwrapping helpers for the backend /v1/profiles API. Import
// them only from server code (BFF route handlers); they rely on callBackend,
// which holds the Clerk JWT and must never reach the browser.

import { BackendError, callBackend } from "@/lib/backend/client";

export type BackendProfileStatus = "active" | "inactive";

/** Profile as returned by the backend (snake_case, UnifiedResponse `result`). */
export interface BackendProfile {
  id: string;
  tenant_id: string;
  created_by: string | null;
  name: string;
  cuit: string | null;
  status: BackendProfileStatus;
  config: Record<string, unknown>;
  created_at: string;
}

interface UnifiedResult<T> {
  status: string;
  result: T | null;
}

function requireResult<T>(res: UnifiedResult<T>, path: string): T {
  if (res.result === null) {
    throw new BackendError("Empty backend result", 502, "EMPTY_RESULT");
  }
  return res.result;
}

export async function listProfiles(
  status?: BackendProfileStatus
): Promise<BackendProfile[]> {
  const query = status ? `?status=${status}` : "";
  const res = await callBackend<UnifiedResult<BackendProfile[]>>(
    `/v1/profiles${query}`,
    { timeoutMs: 60_000 }
  );
  return res.result ?? [];
}

export interface CreateProfileInput {
  name: string;
  cuit?: string | null;
  config?: Record<string, unknown>;
}

export async function createProfile(
  input: CreateProfileInput
): Promise<BackendProfile> {
  const res = await callBackend<UnifiedResult<BackendProfile>>("/v1/profiles", {
    method: "POST",
    body: {
      name: input.name,
      cuit: input.cuit ?? null,
      config: input.config ?? {},
    },
    timeoutMs: 60_000,
  });
  return requireResult(res, "/v1/profiles");
}

export interface UpdateProfilePatch {
  name?: string;
  cuit?: string | null;
  status?: BackendProfileStatus;
  config?: Record<string, unknown>;
}

export async function updateProfile(
  id: string,
  patch: UpdateProfilePatch
): Promise<BackendProfile> {
  const res = await callBackend<UnifiedResult<BackendProfile>>(
    `/v1/profiles/${id}`,
    { method: "PATCH", body: patch, timeoutMs: 60_000 }
  );
  return requireResult(res, `/v1/profiles/${id}`);
}

export async function deleteProfile(id: string): Promise<void> {
  // DELETE returns a 204 with an empty body; callBackend handles that.
  await callBackend<void>(`/v1/profiles/${id}`, { method: "DELETE" });
}

/** Error code taxonomy the backend uses (surfaced via BackendError.code). */
export const PROFILE_ERROR_CODES = {
  INVALID_CUIT: "INVALID_CUIT",
  PROFILE_CUIT_EXISTS: "PROFILE_CUIT_EXISTS",
  PROFILE_NOT_FOUND: "PROFILE_NOT_FOUND",
  PROFILE_HAS_RUNS: "PROFILE_HAS_RUNS",
  EMPTY_UPDATE: "EMPTY_UPDATE",
  INVALID_PROFILE_STATUS: "INVALID_PROFILE_STATUS",
} as const;