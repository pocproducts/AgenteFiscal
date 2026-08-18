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
  en: "Fiscal Agent",
  es: "Agente Fiscal",
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

export type LanguageProviderProps = {
  children: React.ReactNode;
  /** Locale resolved on the server (defaults to "es"). Avoids a client-only flash. */
  initialLocale?: Language;
};

export function LanguageProvider({ children }: LanguageProviderProps) {
  // Spanish is the only supported language. Always start in Spanish,
  // regardless of cookie/localStorage/<html data-locale> legacy values.
  const resolveInitial = (): Language => "es";

  const [language, setLanguageState] = useState<Language>(resolveInitial);

  const setLanguage = (_lang: Language) => {
    // Spanish-only: ignore any attempt to switch away from "es".
    const next: Language = "es";
    setLanguageState(next);
    document.documentElement.lang = next;
    document.documentElement.setAttribute("data-locale", next);
    document.title = DOCUMENT_TITLES[next];
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
