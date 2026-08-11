"use client";

import type React from "react";
import { createContext, useContext, useEffect, useState } from "react";
import { type Language, type Translations, translations } from "./dictionary";

export type { Language, Translations } from "./dictionary";
export type LanguageContextValue = {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: Translations["en"];
};

// Keeps <title> in sync with the locale. Static metadata is defined in
// app/layout.tsx (es) because reading cookies() in generateMetadata breaks
// prerenderable routes in Next 16; the toggle updates the title client-side.
const DOCUMENT_TITLES: Record<Language, string> = {
  en: "Fiscal Assistant",
  es: "Asistente Fiscal",
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

export type LanguageProviderProps = {
  children: React.ReactNode;
  /** Locale resolved on the server (defaults to "es"). Avoids a client-only flash. */
  initialLocale?: Language;
};

export function LanguageProvider({
  children,
  initialLocale = "es",
}: LanguageProviderProps) {
  // The root layout inlines a locale script that reads the optimus-lang cookie
  // and exposes it as <html data-locale>. On the client, prefer that value so
  // the UI language matches the persisted cookie on first render. On the server
  // (hydration phase) fall back to the server-seeded initialLocale.
  const resolveInitial = (): Language => {
    if (typeof document !== "undefined") {
      const fromDom = document.documentElement.getAttribute(
        "data-locale"
      ) as Language | null;
      if (fromDom === "en" || fromDom === "es") {
        return fromDom;
      }
    }
    return initialLocale;
  };

  const [language, setLanguageState] = useState<Language>(resolveInitial);

  // One-time hydration sync for legacy landing visitors who stored
  // `optimus-lang` in localStorage before the cookie layer existed. If it
  // differs from the server-seeded cookie locale, adopt it and persist both.
  useEffect(() => {
    const stored = window.localStorage.getItem(
      "optimus-lang"
    ) as Language | null;
    if ((stored === "en" || stored === "es") && stored !== initialLocale) {
      setLanguageState(stored);
      // biome-ignore lint/suspicious/noDocumentCookie: allowlist-enforced locale persistence; value is only "en"/"es", never attacker-controlled.
      document.cookie = `${encodeURIComponent("optimus-lang")}=${encodeURIComponent(stored)}; path=/; max-age=${60 * 60 * 24 * 365}`;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once on hydration
  }, [initialLocale]);

  const setLanguage = (lang: Language) => {
    setLanguageState(lang);
    window.localStorage.setItem("optimus-lang", lang);
    document.documentElement.lang = lang;
    document.documentElement.setAttribute("data-locale", lang);
    document.title = DOCUMENT_TITLES[lang];

    // Persist the locale server-side so SSR (html lang, metadata,
    // server-rendered strings) stays in sync with the toggle (design D3).
    // Fire-and-forget: never block the UI on the fetch. Respects the
    // NEXT_PUBLIC_BASE_PATH used by other API fetches (IS_DEMO=1 -> /demo).
    const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
    fetch(`${basePath}/api/locale`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lang }),
    })
      .then(() => undefined)
      .catch(() => {
        // Ignore network failures — localStorage + documentElement already applied.
      });
  };

  useEffect(() => {
    document.documentElement.lang = language;
    document.documentElement.setAttribute("data-locale", language);
    document.title = DOCUMENT_TITLES[language];
  }, [language]);

  const value: LanguageContextValue = {
    language,
    setLanguage,
    t: translations[language] as Translations["en"],
  };

  return (
    <LanguageContext.Provider value={value}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  const ctx = useContext(LanguageContext);
  if (!ctx) {
    throw new Error("useLanguage must be used within a LanguageProvider");
  }
  return ctx;
}
