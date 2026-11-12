# Gate Zero Questions — Required Human Decisions

**Status:** Blocking. No workstream may start until each item is recorded as decided
or explicitly blocked with an owner and date.
**Decided so far:** G0-1 on 2026-11-12, amended the same day by the Security Owner's
refusal of the shared-account residual and the selection of **Option A** (see §E).
**Still blocking:** G0-6. No Security Owner has been named. Everything else in
sections A and B is open.
**Instructions:** Product Owner, Security Owner and Legal Counsel complete the
relevant items. Do not let an implementation agent invent answers.

## A. Gate Zero decisions (G0-1 through G0-10)

- [x] **G0-1 — Deployment model and adversary.**
  **DECIDED 2026-11-12 — multi-user. AMENDED the same day: one OS account per user
  is required; a shared OS account is unsupported and must be refused at runtime
  (Option A).**
  Owner: Product Owner + Security Owner.
  Consequences are recorded in `docs/THREAT_MODEL.md` §2. The OS account is a trust
  boundary again, so filesystem permissions and per-user keychain entries separate
  users; but loopback is still not authentication (any local user can reach the
  port), so CR-10.6 baseline controls remain mandatory in every mode. This raises
  the weight of **G0-3**: retention and redaction are what bound exposure when
  authentication is defeated.

- [ ] **G0-2 — Rule corpus ownership and approval.** Named legal content owner; citation, wording, effective dates; two-person approval for rule changes.
  Owner: Legal Content Owner. **Blocks CR-4.**

- [ ] **G0-3 — Confidentiality, privilege, PII, retention, legal hold, deletion.** Privileged material, third-party personal data, call recordings; retention and deletion policy; Law 25 flags.
  Owner: Counsel + Privacy Owner. Default: default-deny ingest/export of privileged/PII until policy is enforced. **Blocks CR-1, CR-2, CR-9, CR-12.** Raised in priority by G0-1.

- [ ] **G0-4 — Real source formats for texts/transcripts.** Anonymized samples supplied for each format.
  Owner: Product/Content Owner. Default: no adapter without a real sample. **Blocks CR-2.**

- [ ] **G0-5 — Performance and usability targets.** Confirm or revise Section 12 defaults.
  Owner: Product Owner. **Blocks CR-6, CR-11.**

- [ ] **G0-6 — Named Security Owner and security architecture sign-off.** Threat model and control matrix signed.
  Owner: Product Owner + Security Owner. **Blocks CR-10, CR-9, CR-5, and all
  workstreams via CR-0.**
  **Still blocked, and now the only thing blocking CR-0 on the security side.** A
  posture has been recorded (the shared-account residual was refused; Option A
  selected), but no person has been named: every entry received contained the
  literal placeholder `[person and title]`. CR-0 cannot be signed by a role, and an
  agent may not sign on a person's behalf.

- [ ] **G0-7 — Who may affirm/dismiss findings; second reviewer requirement.** Role definitions and segregation of duties.
  Owner: Product + Legal Owners. Default: single authorized reviewer initially; second reviewer where owners decide. **Blocks CR-5.**

- [ ] **G0-8 — Export and decision enablement criteria.** Including external penetration test result and policy sign-off.
  Owner: Product + Security + Legal Owners. Default: no export/decision enablement before pen test and policy sign-off. **Blocks CR-9, CR-5 enablement.**

- [ ] **G0-9 — Incident-response owner and abort/rollback authority.** Named owner; rollback exercised before release.
  Owner: Operations + Security Owners. **Blocks CR-11.**

- [ ] **G0-10 — Whether call recordings, not just transcripts, are ever stored.**
  Owner: Counsel. Default: no recordings. **Blocks CR-1, CR-12.**

## B. Reserved human decisions (H-1 through H-12)

- [ ] **H-1 — Deployment model and adversaries.** Owner: Product + Security Owner. Deployment model decided by G0-1; the adversary set still needs sign-off in CR-0.
- [ ] **H-2 — Rule corpus ownership and approval.** Owner: Legal Content Owner.
- [ ] **H-3 — Who may affirm/dismiss; second reviewer.** Owner: Product + Legal Owners.
- [ ] **H-4 — Retention for messages, decisions, exports.** Owner: Counsel.
- [ ] **H-5 — Privileged material and third-party PII, Law 25 flags.** Owner: Counsel.
- [ ] **H-6 — Free-text search in shareable addresses.** Owner: Product Owner. Default: no.
- [ ] **H-7 — Performance and usability targets.** Owner: Product Owner.
- [ ] **H-8 — Call recordings storage.** Owner: Counsel.
- [ ] **H-9 — Production migration execution.** Owner: Operations Owner.
- [ ] **H-10 — Named Security Owner and threat-model sign-off.** Owner: Product + Security Owners. **Same blocker as G0-6.**
- [ ] **H-11 — Export/decision enablement after pen test and policy.** Owner: Product + Security + Legal.
- [ ] **H-12 — Incident-response and rollback authority.** Owner: Operations + Security.
## C. Views by owner

An item under more than one owner is not decided until **every** listed owner has
recorded a position. The three roles below are the ones the plan names; Operations
and Privacy appear where the plan assigns them a specific decision.

### Product Owner

- **Claims:** G0-4, G0-5, H-6, H-7.
- **Co-owns:** G0-1 *(decided)*, G0-6, G0-7, G0-8; H-1, H-3, H-10, H-11.

### Security Owner

- **Claims:** G0-6 (named owner and architecture sign-off).
- **Co-owns:** G0-1 *(decided)*, G0-8, G0-9; H-1, H-10, H-11, H-12.
- **Cannot be delegated to an implementing agent.** A named person is required, and
  G0-6 is the one item still missing one.
- **Posture already recorded:** the shared-account residual was refused and Option A
  selected (§E).
### Legal Counsel

- **Claims:** G0-3, G0-10; H-4, H-5, H-8.
- **Co-owns:** G0-2, G0-7, G0-8; H-2, H-3, H-11.
- **Law 25, privilege and consent flags are Counsel's to close**, not the product's
  to assume. G0-1 makes G0-3 more urgent: retention and redaction bound what an
  impersonation reaches.
### Other owners the plan names

- **Operations Owner:** G0-9; H-9, H-12.
- **Privacy Owner:** G0-3 with Counsel.
- **Legal Content Owner:** G0-2; H-2.
### How to record an answer

Replace the checkbox with one of:

- `DECIDED — <decision> — <owner name> — <YYYY-MM-DD>`
- `BLOCKED — <what is missing> — <owner name> — <YYYY-MM-DD>`

"BLOCKED" is a valid outcome and must be recorded as one. An item left blank is
indistinguishable from an item nobody read, and the point of this gate is that no
workstream starts against an unread assumption.
## D. Sign-off record

| Item | Decision | Owner | Date | Notes |
|---|---|---|---|---|
| G0-1 | DECIDED, then AMENDED — multi-user; one OS account per user required, shared account unsupported | Product Owner + Security Owner | 2026-11-12 | Threat model rewritten for Option A. OS account is a boundary again; loopback still is not. Detection of a shared account is a required control and has no owner yet |
| G0-2 | | | | |
| G0-3 | | | | Raised in priority by G0-1 |
| G0-4 | | | | |
| G0-5 | | | | |
| G0-6 | DECIDED — Security Owner for v1 is Samuel Tessier, also sole author, owner, and developer; no independent review exists for v1. Each sold deployment must be individualized per client (own keys, own audit chain, own data boundary) as a v1 acceptance criterion, not a v2 aspiration. | Samuel Tessier | 2026-11-12 | Named individual, not a role. Implementer = reviewer for v1 development, recorded as a residual. Per-client individualization is a shipping gate tracked against CR-10 (authentication) and CR-12 (keys, retention). External security review required before the first client deployment. |
| G0-7 | | | | |
| G0-8 | | | | |
| G0-9 | | | | |
| G0-10 | | | | |
## E. How the shared-account residual is closed

Recorded 2026-11-12. The Security Owner's position was a **refusal**, not an
acceptance:

> The residual that a user of a shared OS account can read the ledger database,
> sidecar text and key files directly is not accepted. Scope must change.

Two options were tabled; both are recorded, one is chosen.

- [x] **Option A — separate OS accounts are required. SELECTED 2026-11-12.**
      One account per user; the product refuses multi-user operation when a shared
      account is detected.
      *Restores:* the OS account as a trust boundary, filesystem permissions,
      per-user key storage in the OS keychain.
      *Costs:* a deployment and support commitment rather than a code change; a
      shared account becomes unsupported. This amends the "not guaranteed" half of
      G0-1.
      *Obliges:* detection and refusal (not documentation), a customer deployment
      requirement, and a stated migration for existing shared-account installs.

- [ ] **Option B — a per-user secret the application never stores. REJECTED
      2026-11-12**, retained as the analysed fallback if Option A proves
      unenforceable. It would defend within a shared account by encrypting per user,
      at the cost of unrecoverable data loss on a forgotten passphrase and an
      unlocked session for every query, background task and export — and would need
      a key-escrow decision from G0-3 and Counsel.

**Effect.** CR-0's scope changed, and `docs/THREAT_MODEL.md` has been rewritten
against Option A. Option A removes the primary adversary by removing the shared
account; it does **not** make loopback a boundary, so application authentication
(CR-10.6) stays mandatory.

**Not decided here.** Whether Option A is enforceable in deployment, and who owns the
detection requirement, are open. If detection turns out to be unenforceable, Option B
is the analysed fallback and must be revisited before any workstream starts.
