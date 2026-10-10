#!/usr/bin/env node
// scripts/fr-review.js
//
// Generates docs/FR_REVIEW.md — the French catalog review sheet sent to
// the Quebec lawyer.
//
// Do not regenerate while a review is in flight.
//
// The sheet carries a catalog hash in its header. If you regenerate it after
// sending, the file the lawyer is reading no longer matches the file on disk,
// and their notes land against a stale version. The hash cannot protect
// against this — it only reports it after the fact, and only if someone
// compares.
//
// If you need to regenerate for an unrelated reason (catalog changed,
// another fix landed), pass --force and tell the reviewer the hash moved.
// Otherwise, wait for the review to come back.
//
// Flags:
//   --force          Overwrite an existing FR_REVIEW.md without warning.
//   --priority-only  Emit only the priority section.

import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { readFile, writeFile } from "node:fs/promises";

const output = new URL("../docs/FR_REVIEW.md", import.meta.url);
const outputName = "docs/FR_REVIEW.md";
const force = process.argv.includes("--force");
const priorityOnly = process.argv.includes("--priority-only");

if (existsSync(output) && !force) {
  console.error(
    `refusing to overwrite ${outputName}.\n\n` +
    `This file is the French catalog review sheet. It may be out with\n` +
    `the Quebec lawyer right now. Replacing it may invalidate notes\n` +
    `in flight. Generated sheets include a catalog hash for comparison.\n\n` +
    `If you are sure the review is not in progress, re-run with --force.`,
  );
  process.exit(1);
}

const enRaw = await readFile(new URL("../locales/en.json", import.meta.url), "utf8");
const frRaw = await readFile(new URL("../locales/fr.json", import.meta.url), "utf8");
const en = JSON.parse(enRaw);
const fr = JSON.parse(frRaw);
const hash = createHash("sha256").update(enRaw + frRaw).digest("hex").slice(0, 12);
const generatedOn = new Date().toISOString().slice(0, 10);

const enKeys = Object.keys(en).sort();
const frKeys = Object.keys(fr).sort();
if (JSON.stringify(enKeys) !== JSON.stringify(frKeys)) {
  throw new Error("English and French catalogs have different keys.");
}

const screens = [
  "Shared interface",
  "Cases",
  "Create case",
  "Overview",
  "Evidence intake",
  "Evidence register",
  "Evidence viewer",
  "Search",
  "Timeline",
  "Audit and exports",
  "Administration",
];

const priority = [
  ["badge.anchored", "Gender agreement. If the referent is a checkpoint: « ancré ». If a proof: « ancrée »."],
  ["badge.quarantined", "Confirm the standard Quebec term, not just a literal translation."],
  ["badge.integrity_hold", "Reads as « integrity block ». Confirm it matches practice — not « suspension » or another term."],
  ["state.integrity_hold", "Same term as the badge. Keep the two consistent."],
  ["nav.audit", "Deliberate domain label, not a literal translation of « Audit and exports »."],
  ["export.gate.barreau", "Confirm the firm's / Barreau's own wording."],
  ["timeline.event.grievance_filed", "« Grief déposé ». Confirm the firm's usage."],
  ["member.role.reviewer", "« Réviseur ». Alternative: « Avocat réviseur » or « Paralégal réviseur »."],
  ["member.role.auditor", "« Vérificateur ». Alternative: « Auditeur » if the loanword is preferred."],
];

function screenFor(key) {
  if (key.startsWith("case.list.")) return "Cases";
  if (key.startsWith("case.create.") || key === "error.case_key_taken") return "Create case";
  if (
    key.startsWith("overview.") ||
    key.startsWith("verification.") ||
    key === "reason.hash_mismatch_at_readback" ||
    key === "error.hash_mismatch_at_readback" ||
    key === "error.signature_invalid" ||
    key === "error.chain_broken" ||
    key === "error.anchor_unverified"
  ) return "Overview";
  if (
    key.startsWith("evidence.intake.") ||
    key === "reason.scan_unsupported_variant" ||
    key === "error.storage_write_failed" ||
    key === "error.readback_failed"
  ) return "Evidence intake";
  if (key.startsWith("evidence.register.") || key.startsWith("custody.")) return "Evidence register";
  if (
    key.startsWith("evidence.viewer.") ||
    key.startsWith("drawer.") ||
    key.startsWith("provenance.") ||
    key.startsWith("correction.") ||
    key === "error.correction_reason_required"
  ) return "Evidence viewer";
  if (
    key.startsWith("search.") ||
    key === "error.index_building" ||
    key === "error.search_unavailable"
  ) return "Search";
  if (key.startsWith("timeline.") || key === "error.source_link_missing") return "Timeline";
  if (
    key.startsWith("audit.") ||
    key.startsWith("export.") ||
    key.startsWith("chain.") ||
    key.startsWith("custody.column.") ||
    key === "error.gate_failed" ||
    key === "error.export_blocked"
  ) return "Audit and exports";
  if (
    key.startsWith("administration.") ||
    key.startsWith("member.") ||
    key === "error.member_already_exists" ||
    key === "error.role_change_requires_reason"
  ) return "Administration";
  return "Shared interface";
}

const sampleValues = {
  count: ["3", "3"],
  when: ["Oct 10, 2026 at 10:00 AM", "10 oct. 2026 à 10 h"],
  loaded: ["2", "2"],
  total: ["3", "3"],
  failed: ["1", "1"],
  done: ["2", "2"],
  reason: ["Unsupported file variant", "Variante de fichier non prise en charge"],
  step: ["hash", "empreinte"],
  policy: ["7 years", "7 ans"],
  id: ["E-1044", "E-1044"],
  hash: ["a1b2c3…", "a1b2c3…"],
  evidenceId: ["E-1044", "E-1044"],
  pageOrOffset: ["page 2", "page 2"],
  gate: ["signature", "signature"],
  item: ["1 item", "1 élément"],
  name: ["A. Roy", "A. Roy"],
};

function renderString(value, locale) {
  return value.replace(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g, (token, name) => {
    const samples = sampleValues[name];
    if (!samples) throw new Error(`No display sample defined for ${token}.`);
    return samples[locale === "en" ? 0 : 1];
  });
}

function cell(value) {
  return String(value).replaceAll("\\", "\\\\").replaceAll("|", "\\|").replace(/\r?\n/g, " ");
}

const grouped = Object.fromEntries(screens.map((screen) => [screen, []]));
for (const key of enKeys) {
  grouped[screenFor(key)].push([
    renderString(en[key], "en"),
    renderString(fr[key], "fr"),
  ]);
}

const lines = [];
lines.push(
  "# French catalog review",
  "",
  `Catalog hash: \`${hash}\` · ${generatedOn}`,
  "",
  "If the hash changes, this review is against a different version of the catalog.",
  "",
  "Read the English and French together. When you flag a row, quote the English text so we can find it in the catalog.",
  "",
  "You may see values like “1 items” or “3 days” — those numbers come from the app at runtime. Don't correct the grammar of the number; the app handles it.",
  "",
  "## Priority review",
  "",
  "These terms have higher legal or domain significance. Please review the French wording and the note for each pair.",
  "",
  "| English | Français | Why we're unsure |",
  "|---|---|---|",
);

for (const [key, why] of priority) {
  if (!(key in en) || !(key in fr)) {
    throw new Error(`Priority key is missing from a catalog: ${key}`);
  }
  lines.push(
    `| ${cell(renderString(en[key], "en"))} | ${cell(renderString(fr[key], "fr"))} | ${cell(why)} |`,
  );
}
lines.push("");

if (!priorityOnly) {
  for (const screen of screens) {
    const rows = grouped[screen];
    if (rows.length === 0) continue;
    lines.push(
      `## ${screen}`,
      "",
      "| English | Français |",
      "|---|---|",
      ...rows.map(([english, french]) => `| ${cell(english)} | ${cell(french)} |`),
      "",
    );
  }
}

await writeFile(output, `${lines.join("\n").trimEnd()}\n`);
console.log(
  `Generated ${output.pathname} (${priorityOnly ? "priority-only" : `${enKeys.length} catalog strings`}; catalog ${hash}).`,
);
