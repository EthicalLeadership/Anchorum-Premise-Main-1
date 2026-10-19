import en from "../locales/en.json";
import fr from "../locales/fr.json";
import enSource from "../locales/en.json?raw";
import frSource from "../locales/fr.json?raw";
import { describe, expect, it } from "vitest";
import { translate } from "./i18n";

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
// The status and badge vocabularies the API can put into a dynamic key. Every
// one of these must resolve to a real message, or a register row would show a
// dotted key instead of a word.
const EVIDENCE_STATUSES = [
  "received",
  "preserved",
  "quarantined",
  "integrity_hold",
  "indexed",
  "scanned",
  "stored",
  "extracted",
  "processed",
  "unsupported",
  "empty",
  "skipped_oversize",
  "failed",
] as const;

const EVIDENCE_BADGES = [
  "received",
  "preserved",
  "indexed",
  "signed",
  "anchored",
  "quarantined",
  "integrity_hold",
  "scanned",
  "stored",
  "extracted",
  "processed",
  "unsupported",
  "empty",
  "skipped_oversize",
  "failed",
] as const;

describe("translate", () => {
  it("echoes the key when the catalog has no message for it", () => {
    // Screens build keys from server data. An unforeseen status must render as
    // something, and must never throw: a throwing render unmounts the whole
    // tree and leaves the operator with a blank page.
    expect(translate("en", "evidence.status.brand_new_status" as never)).toBe(
      "evidence.status.brand_new_status",
    );
    expect(translate("fr", "badge.brand_new_badge" as never)).toBe(
      "badge.brand_new_badge",
    );
    expect(translate("en", "error.http_501" as never)).toBe("error.http_501");
  });

  it("still interpolates declared parameters", () => {
    expect(
      translate("en", "state.partial", { loaded: 8, total: 12, failed: 1 }),
    ).toBe("8 of 12 loaded. 1 failed.");
    expect(
      translate("fr", "state.partial", { loaded: 8, total: 12, failed: 1 }),
    ).toBe("8 sur 12 chargés. 1 en échec.");
  });

  it("still throws when a declared placeholder is not supplied", () => {
    // A message that exists but is called without its placeholder is a
    // malformed call site, not unforeseen data, and stays loud.
    expect(() => translate("en", "state.partial")).toThrow(
      /Missing translation parameter/,
    );
  });

  it("has a message for every evidence status in both locales", () => {
    for (const status of EVIDENCE_STATUSES) {
      const key = `evidence.status.${status}`;
      expect(translate("en", key as never), key).not.toBe(key);
      expect(translate("fr", key as never), key).not.toBe(key);
    }
  });

  it("has a message for every evidence badge in both locales", () => {
    for (const badge of EVIDENCE_BADGES) {
      const key = `badge.${badge}`;
      expect(translate("en", key as never), key).not.toBe(key);
      expect(translate("fr", key as never), key).not.toBe(key);
    }
  });
});
