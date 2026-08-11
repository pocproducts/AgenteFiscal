import { type Language, translations } from "./dictionary";

export type Dictionary = typeof translations.en;

/** Returns the full Translation["en"]-typed dictionary for a given locale. */
export function getDictionary(locale: Language): Dictionary {
  return translations[locale] as Dictionary;
}
