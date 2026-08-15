"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";
import useSWR from "swr";
import { useTenantKey } from "@/hooks/use-tenant-key";
import type {
  Profile,
  ProfileStatus,
} from "@/lib/shared/db-types";

export type { Profile, ProfileStatus } from "@/lib/shared/db-types";

/**
 * Client-side API error thrown by the profile BFF calls. Carries the backend
 * error code (e.g. PROFILE_CUIT_EXISTS / INVALID_CUIT / PROFILE_HAS_RUNS) so
 * the UI can surface friendly, specific messages.
 */
export class ProfileApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ProfileApiError";
    this.status = status;
    this.code = code;
  }
}

const PROFILE_STORAGE_KEY = "active-profile-id";

function readStoredActiveProfileId(): string {
  if (typeof window === "undefined") {
    return "";
  }
  try {
    const raw = window.localStorage.getItem(PROFILE_STORAGE_KEY);
    if (!raw) {
      return "";
    }
    // Stored via JSON.stringify(id) (compatible with usehooks-ts useLocalStorage).
    const parsed = JSON.parse(raw);
    return typeof parsed === "string" ? parsed : "";
  } catch {
    return "";
  }
}

function writeStoredActiveProfileId(id: string) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(id));
  } catch {
    // Storage unavailable (private mode, quota) — the in-memory value still
    // works for this session, so the UI keeps functioning.
  }
}

// Tiny external store so every useProfiles() instance shares the same live
// active-profile value, keeps localStorage as the source of truth (which
// hooks/use-active-chat.tsx reads on every chat request), and stays in sync
// across tabs.
let activeProfileIdCache = readStoredActiveProfileId();
const activeProfileListeners = new Set<() => void>();

function notifyActiveProfileListeners() {
  for (const listener of activeProfileListeners) {
    listener();
  }
}

function setActiveProfileCache(next: string) {
  if (activeProfileIdCache !== next) {
    activeProfileIdCache = next;
    notifyActiveProfileListeners();
  }
}

function subscribeActiveProfile(listener: () => void): () => void {
  activeProfileListeners.add(listener);
  return () => {
    activeProfileListeners.delete(listener);
  };
}

if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key === PROFILE_STORAGE_KEY) {
      setActiveProfileCache(readStoredActiveProfileId());
    }
  });
}

async function parseResponse(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

async function profilesApi<TPayload>(
  url: string,
  init: { method?: string; body?: unknown } = {}
): Promise<TPayload> {
  const res = await fetch(url, {
    method: init.method ?? "GET",
    headers:
      init.body === undefined
        ? undefined
        : { "Content-Type": "application/json" },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    cache: "no-store",
  });
  const payload = (await parseResponse(res)) as
    | { profile?: Profile; profiles?: Profile[]; error?: { code?: string; message?: string } }
    | null;
  if (!res.ok) {
    const error = payload?.error;
    throw new ProfileApiError(
      error?.message ?? res.statusText,
      res.status,
      error?.code
    );
  }
  return payload as TPayload;
}

const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

async function profilesFetcher(): Promise<Profile[]> {
  const res = await fetch(`${basePath}/api/profiles`, { cache: "no-store" });
  if (!res.ok) {
    throw new ProfileApiError(res.statusText, res.status);
  }
  const body = (await parseResponse(res)) as { profiles?: Profile[] } | null;
  return body?.profiles ?? [];
}

function revalidateAfterMutation(mutate: () => Promise<unknown>) {
  // Fire-and-forget background refetch to reconcile server-side attributes
  // (id, created_at) and ordering; never blocks the caller.
  void mutate();
}

export function useProfiles() {
  const key = useTenantKey("profiles");
  const { data, isLoading, error, mutate: setProfiles } = useSWR<Profile[]>(
    key,
    profilesFetcher,
    { fallbackData: [], revalidateOnFocus: false }
  );
  const profiles = data ?? [];

  const activeProfileId = useSyncExternalStore(
    subscribeActiveProfile,
    () => activeProfileIdCache,
    () => "" // SSR: nunca hay localStorage en el server; el post-hydration
    // useEffect reconcilia con el valor real.
  );

  const setActiveProfileId = useCallback((id: string) => {
    writeStoredActiveProfileId(id);
    setActiveProfileCache(id);
  }, []);

  // Once profiles actually load, reconcile the stored active profile with
  // reality: clear it when it no longer exists or is inactive (a profile that
  // can't generate reports must not stay "selected"), and pre-select the first
  // active profile when nothing is stored yet (matches the historical default).
  useEffect(() => {
    if (isLoading || profiles.length === 0) {
      return;
    }
    const current = activeProfileIdCache;
    if (current && !profiles.some((p) => p.id === current && p.status === "active")) {
      writeStoredActiveProfileId("");
      setActiveProfileCache("");
      return;
    }
    if (!current) {
      const firstActive = profiles.find((p) => p.status === "active");
      if (firstActive) {
        writeStoredActiveProfileId(firstActive.id);
        setActiveProfileCache(firstActive.id);
      }
    }
  }, [isLoading, profiles]);

  const addProfile = useCallback(
    async (
      name: string,
      cuit?: string | null,
      config?: Record<string, unknown>
    ) => {
      const payload = await profilesApi<{ profile: Profile }>(
        `${basePath}/api/profiles`,
        { method: "POST", body: { name, cuit: cuit ?? null, config: config ?? {} } }
      );
      const created = payload.profile;
      await setProfiles((prev) => [...(prev ?? []), created], false);
      revalidateAfterMutation(setProfiles);
      return created;
    },
    [setProfiles]
  );

  const updateProfile = useCallback(
    async (
      id: string,
      patch: {
        name?: string;
        cuit?: string | null;
        status?: ProfileStatus;
        config?: Record<string, unknown>;
      }
    ) => {
      const payload = await profilesApi<{ profile: Profile }>(
        `${basePath}/api/profiles/${id}`,
        { method: "PATCH", body: patch }
      );
      const updated = payload.profile;
      await setProfiles(
        (prev) =>
          (prev ?? []).map((p) => (p.id === id ? { ...p, ...updated } : p)),
        false
      );
      // If the edited profile was deactivated, it can't keep being the active
      // profile for reports.
      if (updated.status === "inactive" && activeProfileIdCache === id) {
        writeStoredActiveProfileId("");
        setActiveProfileCache("");
      }
      revalidateAfterMutation(setProfiles);
      return updated;
    },
    [setProfiles]
  );

  const updateProfileName = useCallback(
    (id: string, newName: string) => updateProfile(id, { name: newName }),
    [updateProfile]
  );

  const setProfileStatus = useCallback(
    (id: string, status: ProfileStatus) => updateProfile(id, { status }),
    [updateProfile]
  );

  // Legacy consumer kept for API stability: "auth" doesn't exist anymore, the
  // closest semantic is an active (usable) profile.
  const setProfileAuth = useCallback(
    (id: string) => setProfileStatus(id, "active"),
    [setProfileStatus]
  );

  const deleteProfile = useCallback(
    async (id: string) => {
      await profilesApi<void>(`${basePath}/api/profiles/${id}`, {
        method: "DELETE",
      });
      await setProfiles((prev) => (prev ?? []).filter((p) => p.id !== id), false);
      if (activeProfileIdCache === id) {
        writeStoredActiveProfileId("");
        setActiveProfileCache("");
      }
      revalidateAfterMutation(setProfiles);
    },
    [setProfiles]
  );

  const refetch = useCallback(() => setProfiles(), [setProfiles]);

  return {
    profiles,
    isLoading,
    error,
    refetch,
    addProfile,
    updateProfileName,
    updateProfile,
    deleteProfile,
    setProfileStatus,
    setProfileAuth,
    activeProfileId,
    setActiveProfileId,
  };
}

// Re-export helper so consumers can type their catches without reaching into
// this module twice.
export function isProfileApiError(err: unknown): err is ProfileApiError {
  return err instanceof ProfileApiError;
}