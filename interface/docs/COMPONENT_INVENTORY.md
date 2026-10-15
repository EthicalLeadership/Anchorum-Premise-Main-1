# COMPONENT_INVENTORY.md

**This is the artifact the shell reconciles against.**
Status: canonical for P0-A. Not a proposal. If the code diverges, either the code
changes or this file is amended in a recorded change never settled inline.

Sources: Interface Plan v2.0, Build Blueprint v1.1, SCREEN_MAP.md (full 16-screen
product; this file covers P0-A only). No AI features. No ninth screen.

Reconcile after every screen: diff what was built against this file, report drift,
amend here if the drift is accepted. Do not re-derive from SCREEN_MAP.md.

---

## 1. Locked conventions

These are settled. They are not reopened by a per-screen review.

### 1.1 Leaf-token convention (i18n)

- Fixture values are **leaf tokens**: lowercase, `snake_case`, **no dots**.
  Example: `"hash_mismatch_at_readback"`, not `"hash.mismatch_at_readback"`.
- Components add the namespace: `t(`reason.${value}`)`.
- Catalog key is the two joined by a dot: `reason.hash_mismatch_at_readback`.
- The catalog is **flat**. No nesting. No sentences built by joining strings.
- `i18n.test.ts` enforces: no duplicate keys (checked on raw text), same key set in
  both catalogs, same `{param}` set per key, no empty values, no edge whitespace,
  no `" + "` concatenation artefacts, and critically every `(entity, value)`
  pair the fixture can emit resolves in both catalogs.

### 1.2 Navigation (D-1)

Left rail, case-scoped. Not a top segmented control.
Reason: five case-scoped destinations plus permission-filtered visibility; hiding an
item in a rail does not reflow the others or shift keyboard order; the rail gives the
hold indicator and case identity a permanent home.
Administration is **not** in the rail. It lives in the user menu, visible only to case
administrators.

### 1.3 Overview verification tile (E-1)

The hero tile is a **verification checklist**, not a dashboard ring.
Four rows: `hash`, `signature`, `chain`, `anchor` each with a pass/fail glyph and a
text result. Failing step named when it fails. `verified at` timestamp shown.
The ring survives only as a **four-segment indicator inside the tile**, equal width,
square edges, **no numeral, no percentage, no standalone label**.

> The ring represents four discrete verification steps and nothing else. It is not a
> score, not a confidence value, and not an aggregate of case quality.

### 1.4 Build order (U2)

Case list → Create case → Overview. Overview depends on a case existing at
`/cases/:id`; Create case redirects there and is not blocked by Overview.
The Overview panel is a **shell composition**, not a ninth screen.

### 1.5 Global search

Deferred. Not rendered. The top bar does **not** reserve space for it.

---

## 2. Current build state

Reconcile this table after every screen.

| Artifact | State |
|---|---|
| `AppShell.tsx` | Built |
| `en.json` / `fr.json` | Built, leaf-token convention |
| `i18n.test.ts` | Built, strengthened |
| `AppShell.test.tsx` | Built |
| `types.ts` | Built |
| `CaseList.tsx` | Built |
| `CreateCase.tsx` | Built |
| `Overview.tsx` | Built |
| `VerificationTile.tsx` | Built |
| `RightDrawer.tsx` | Built in `AppShell.tsx` |
| `GatePanel.tsx` | Not built |
| `QuickLinks.tsx` | Built in `Overview.tsx` |
| `TimelineItem.tsx` | Built |
| `dupont-v-acme.ts` (fixture) | Built |
| `adapter.ts` / `adapter.test.ts` | Built |
| Search screen | Built |
| Timeline screen | Built |
| Administration screen | Built |
| Audit and exports screen | Partial audit and gate preview render; export generation is not implemented |

---

## 3. Fixture case

**Path:** `interface/src/fixtures/dupont-v-acme.ts`
**Status:** required before Case list, Create case and Overview. Not speculative this
file is named here and in the Build Blueprint as a U2 dependency. Every screen after
the shell renders against it until M1/M3/M5 are live.

**Seeded case:** `DUPONT v. ACME`, Quebec labour, taken from SCREEN_MAP's own example.
**Key:** `CASE-2024-018`.

**Must include, so failure states are visible from first render:**

- One **quarantined** file, reason shown, original kept.
  `E-1044`, reason `scan_unsupported_variant`.
- One **failed verification** with the failing step named on its own line.
  `E-1047`, failing step `hash_mismatch_at_readback`.
- One **integrity hold** on the same item, prominent, blocks export.
- One duplicate candidate (`E-1043`).
- One correction revision, prior value and reason preserved (`E-1043`).
- One blocked export with a named failing gate (`barreau` → `E-1047`).
- Timeline with all four date precisions, including one `unknown` with no date.

**Rules**
1. All leaf values follow §1.1. No dots inside string literals.
2. Keys are stable (`E-1042`, `CASE-2024-018`) so tests can assert on them.
3. The adapter returns the fixture unchanged when the backend is absent.
   No screen branches on "is fixture / is live."
4. Every `action`, `event`, `reason`, `label`, `status`, `role` and `precision` value
   is a leaf token resolvable through the catalog as `${entity}.${value}`.

---

## 4. Components

Each entry: purpose, states, screens, U-step, build state.
Anatomy and copy live in the plan; this file owns the contract.

### C1 TrustBadge · not built
- Types: Received, Preserved, Signed, Anchored, Quarantined, Integrity hold.
- Shown only when the corresponding check has passed (or, for hold/quarantine, failed).
- Failed or stale: warning treatment, failing step named. Never colour-only.
- Screens 3, 4, Overview · U1 (tokens) / U3, U4 (use)

### C2 BadgeRow · not built
- Canonical order: hold badge first if present; otherwise
  Received → Preserved → Signed → Anchored.
- Wraps on narrow screens. Never truncates badge text.
- Screens 3, 4, Overview · U1

### C3 CaseHeader · built (in shell)
- Pinned. Case key + title · jurisdiction · status · integrity indicator.
- Integrity indicator is text: "All clear" or "N items on hold", holds link to
  filtered evidence.
- Not rendered on Case list (no case selected).
- Screens: all case-scoped · U1

### C4 LeftRail · built (in shell)
- Overview, Evidence, Timeline, Audit and exports, Case settings.
- Case-scoped. Permission-filtered. Hidden items are **not rendered**, not greyed out.
- Active item uses text + shape, not colour alone.
- Screens: all case-scoped · U1 · see §1.2

### C5 RightDrawer · not built
- Four canonical sections, in order: Custody history · Provenance · Verification ·
  Correction history.
- Verification section carries `Verify now`.
- Opening, downloading and verifying each write a custody event.
- Screens 4 · U4

### C6 DataTable · not built
- Loading uses skeleton rows, not a spinner over blank space.
- Empty: one sentence + one action. Partial: show loaded, mark failed.
- Screens 1, 4 · U2 (Case list), U4 (Register)

### C7 FileDropZone · not built
- Files and folders. Retention policy shown before upload.
- Per-file rows created immediately. A failed file never blocks the rest.
- Screens 3 · U3

### C8 ProgressStrip · not built
- Stages: Received → Preserved → Scanned → Indexed.
- Per-file states: pending, active, done, failed, quarantined. Failure names the step.
- Completed row shows Evidence ID and SHA-256 of the exact bytes received.
- Screens 3 · U3

### C9 StateBlock · built (in shell)
- Eight states: Loading, Empty, Partial, Error, Processing, Quarantined,
  Integrity hold, Permission-limited.
- Rules are verbatim from the plan. Do not paraphrase.
- Screens: all · U1

### C10 SearchBox & FilterBar · built in Search screen
- Scope: current case. Global search deferred (§1.5).
- FR and EN stemming both apply in the fixture search implementation.
- Screens 5 · U5

### C11 TimelineItem · built
- Date · event · people · source link · date precision (always visible).
- Correction creates a new revision; prior value and reason preserved.
- Screens 6 · U6

### C12 AuditLogRow & ChainIndicator · built in AuditExports
- Chain indicator: linked · broken · not checked. Text, not colour alone.
- Screens 7, Overview (limited) · U7a owner, U2c limited use

### C13 ExportPanel & GatePanel · partial in AuditExports
- Export types: evidence index, signed audit package.
- Gates: restriction, disclaimer, Barreau check each pass/fail.
- A failing gate blocks export and names the item.
- Gate preview is wired; there is no export-generation adapter method, so no export
  file or signed package is produced.
- Screens 7 · U7b

### C14 AdminMembersTable & InviteForm · built
- Members table and invite form. Case assignments.
- Screens 8 · U8

### C15 FormField · built (in shell)
- Label, help, error, required marker. Errors name the field and the problem.
- Screens 2, 3, 8 · U1

### C16 ConfirmWithReasonDialog · built
- Sensitive changes only: role changes, restrictions, holds, exports with disclaimers.
- Requires reason, confirms again, audited.
- Inline confirm patterns are removed where C16 applies.
- Screens 8 and anywhere a sensitive change occurs · U8

---

## 5. Screen → component map

| Screen | Components |
|---|---|
| 1 Case list | C4, C6, C15 |
| 2 Create case | C15 |
| 3 Evidence intake | C7, C8, C9 |
| 4 Register and viewer | C1, C5, C6 |
| 5 Search | C10 |
| 6 Timeline | C11 |
| 7 Audit and exports | C12, C13 |
| 8 Administration | C14, C16 |
| Overview (shell panel) | C1, C2, C3, C4, C12 |

---

## 6. Reconciliation checklist

Run after every screen. Report which items pass; do not fix silently.

1. No inline colours. Grep for `#`, `oklch(`, `rgb(` outside `tokens.css` returns
   nothing.
2. Fixture leaf values contain no dots (§1.1).
3. Every `(entity, value)` pair the fixture can emit resolves in both catalogs.
4. `en.json` and `fr.json` have identical key sets; no duplicate keys on raw text.
5. No sentence built by joining strings. No `" + "` in catalog values.
6. Left rail (§1.2) is a `<nav>` column, not a top segmented control.
7. Administration appears only in the user menu, only for case administrators.
8. Rail hides items the user cannot see; nothing greyed out.
9. Case header shows integrity as text; holds link to filtered evidence.
10. Drawer hidden when no selection; does not overlap primary action at 1280px+.
11. Keyboard order: skip link → top bar → case header → rail → main → drawer.
12. `:focus-visible` uses `--focus-ring`; every interactive element reachable.
13. `Escape` closes drawer and menus; focus returns to the trigger.
14. Every state in §C9 renders, including Error, Partial, Quarantined and
    Integrity hold not just the happy path.
15. `SYSTEM_ARCHITECTURE.md` and `MVP_BACKLOG.md` diffs reviewed; milestone
    definitions unchanged or the change recorded as an amendment.

---

## 7. Open items

| Item | Status | Blocks |
|---|---|---|
| Reuse decision (T0.3) | Open | U1 onward |
| PDF library + redaction placement (T0.4) | Open | U0 testing, U4 |
| French label review | Flagged | U9 |
| Tablet-at-launch decision | Open | U9 or defer |
| Global search | Closed deferred (§1.5) | |
| COUNSEL pack in checkout | Open | every visual review |

---

*End of file. Amendments are recorded here with a date and a reason. Divergences are
never settled inline in a screen review.*
