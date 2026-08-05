"use client";

import { useCallback, useMemo } from "react";
import useSWR from "swr";

export interface Profile {
  id: string;
  name: string;
  createdAt: string;
  cookiesDomains: string[];
  isAuthenticated?: boolean;
}

export function useProfiles() {
  const { data: profiles, mutate: setProfiles } = useSWR<Profile[]>(
    "execution-profiles",
    null,
    { fallbackData: [] }
  );

  const addProfile = useCallback(
    (name: string, domains: string[] = []) => {
      const newProfile: Profile = {
        id: `prof_${Math.random().toString(36).substring(2, 7)}`,
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
    (id: string, isAuthenticated: boolean) => {
      setProfiles((prev) => {
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
