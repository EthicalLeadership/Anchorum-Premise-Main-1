import en from "../locales/en.json";
import fr from "../locales/fr.json";
import type { Locale } from "./types";

const catalogs: Record<Locale, typeof en> = { en, fr };

export type MessageKey = keyof typeof en;
export type MessageParameters = Record<string, string | number>;

/**
 * Look up a message.
 *
 * `key` is typed as `MessageKey`, but screens also build keys from
 * server-supplied vocabulary — `evidence.status.${status}`, `badge.${badge}`,
 * `error.${code}`, `custody.${action}`, `export.gate.${gate.id}`. Those call
 * sites cast a template literal, so the type system cannot promise the catalog
 * contains the result.
 *
 * A value the catalog has no message for is a *data* condition, not a bug in
 * the caller. It must not abort the render: React unmounts the whole tree when
 * a render throws, which turns a missing string into a blank page. Echoing the
 * key back keeps the page usable and makes the gap obvious on screen.
 *
 * A message that exists but is asked for without one of its declared
 * placeholders is a different thing — a malformed call site — and still throws.
 */
export function translate(
  locale: Locale,
  key: MessageKey,
  parameters: MessageParameters = {},
): string {
  const catalog: Partial<Record<MessageKey, string>> = catalogs[locale];
  const message = catalog[key];
  if (message === undefined) {
    return key;
  }
  return message.replace(/\{([A-Za-z0-9_]+)\}/g, (_, name: string) => {
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
