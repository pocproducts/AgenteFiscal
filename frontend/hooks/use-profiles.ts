"use client";

import { useCallback, useMemo } from "react";
import useSWR from "swr";
import { useTenantKey } from "@/hooks/use-tenant-key";

export interface Profile {
  id: string;
  name: string;
  createdAt: string;
  cookiesDomains: string[];
  isAuthenticated?: boolean;
}

export function useProfiles() {
  const key = useTenantKey("execution-profiles");
  const { data: profiles, mutate: setProfiles } = useSWR<Profile[]>(key, null, {
    fallbackData: [],
  });

  const addProfile = useCallback(
    (name: string, domains: string[] = []) => {
      const newProfile: Profile = {
        id: `prof_${Math.random().toString(36).slice(2, 7)}`,
        name,
        createdAt: new Date().toISOString().split("T")[0],
        cookiesDomains: domains,
        isAuthenticated: false,
      };

      setProfiles((prev) => {
        const current = prev ?? [];
        return [...current, newProfile];
      }, false);

      return newProfile;
    },
    [setProfiles]
  );

  const updateProfileName = useCallback(
    (id: string, newName: string) => {
      setProfiles((prev) => {
        const current = prev ?? [];
        return current.map((p) => (p.id === id ? { ...p, name: newName } : p));
      }, false);
    },
    [setProfiles]
  );

  const deleteProfile = useCallback(
    (id: string) => {
      setProfiles((prev) => {
        const current = prev ?? [];
        return current.filter((p) => p.id !== id);
      }, false);
    },
    [setProfiles]
  );

  const setProfileAuth = useCallback(
    async (id: string, isAuthenticated: boolean) => {
      await setProfiles((prev) => {
        const current = prev ?? [];
        return current.map((p) =>
          p.id === id ? { ...p, isAuthenticated } : p
        );
      }, false);
    },
    [setProfiles]
  );

  return useMemo(
    () => ({
      profiles: profiles ?? [],
      addProfile,
      updateProfileName,
      deleteProfile,
      setProfileAuth,
    }),
    [profiles, addProfile, updateProfileName, deleteProfile, setProfileAuth]
  );
}
