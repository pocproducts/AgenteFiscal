"use client";

import { enUS, esES } from "@clerk/localizations";
import { ClerkProvider } from "@clerk/nextjs";
import type { ReactNode } from "react";
import { useLanguage } from "@/lib/i18n";

/**
 * Keeps Clerk's own widget copy (SignIn/SignUp/OrganizationSwitcher, etc.) in
 * sync with the app's EN/ES toggle. Must render inside <LanguageProvider>.
 */
export function ClerkLocaleProvider({ children }: { children: ReactNode }) {
  const { language } = useLanguage();

  return (
    <ClerkProvider localization={language === "en" ? enUS : esES}>
      {children}
    </ClerkProvider>
  );
}
