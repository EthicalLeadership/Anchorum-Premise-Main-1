import en from "../locales/en.json";
import fr from "../locales/fr.json";
import enSource from "../locales/en.json?raw";
import frSource from "../locales/fr.json?raw";
import { describe, expect, it } from "vitest";

function rawKeys(locale: "en" | "fr"): string[] {
  const source = locale === "en" ? enSource : frSource;
  return [...source.matchAll(/^\s*"([^"]+)"\s*:/gm)].map((match) => match[1]);
}

function placeholders(message: string): string[] {
  return [...message.matchAll(/\{([A-Za-z0-9_]+)\}/g)]
    .map((match) => match[1])
    .sort();
}

function catalogValues(catalog: Record<string, string>) {
  return Object.entries(catalog);
}

describe("translation catalogs", () => {
  it("contains no duplicate keys", () => {
    for (const locale of ["en", "fr"] as const) {
      const keys = rawKeys(locale);
      expect(keys, `${locale} has duplicate catalog keys`).toHaveLength(
        new Set(keys).size,
      );
    }
  });

  it("has matching keys and interpolation placeholders", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(fr).sort());

    for (const key of Object.keys(en) as Array<keyof typeof en>) {
      expect(placeholders(en[key]), `${key} placeholder mismatch`).toEqual(
        placeholders(fr[key]),
      );
    }
  });

  it("contains non-empty, complete messages", () => {
    for (const [locale, catalog] of [
      ["en", en],
      ["fr", fr],
    ] as const) {
      for (const [key, value] of catalogValues(catalog)) {
        expect(value.trim(), `${locale}.${key} must not be empty`).not.toBe("");
        expect(value, `${locale}.${key} must not have edge whitespace`).toBe(
          value.trim(),
        );
        expect(value, `${locale}.${key} must not contain code concatenation`).not.toContain(
          " + ",
        );
      }
    }
  });
});
