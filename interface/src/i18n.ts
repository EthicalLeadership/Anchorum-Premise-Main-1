import en from "../locales/en.json";
import fr from "../locales/fr.json";
import type { Locale } from "./types";

const catalogs: Record<Locale, typeof en> = { en, fr };

export type MessageKey = keyof typeof en;
export type MessageParameters = Record<string, string | number>;

export function translate(
  locale: Locale,
  key: MessageKey,
  parameters: MessageParameters = {},
): string {
  return catalogs[locale][key].replace(/\{([A-Za-z0-9_]+)\}/g, (_, name: string) => {
    if (!(name in parameters)) {
      throw new Error(`Missing translation parameter "${name}" for "${key}".`);
    }
    return String(parameters[name]);
  });
}

export function formatDateTime(locale: Locale, value: string, timeZone: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone,
  }).format(new Date(value));
}
