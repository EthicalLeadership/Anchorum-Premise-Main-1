# Gate Zero Questions — Required Human Decisions

**Status:** Blocking. No workstream may start until each item is recorded as decided
or explicitly blocked with an owner and date.
**Decided so far:** G0-1 (2026-11-12, amended the same day to Option A), and G0-6
(2026-11-12, Security Owner named, with a recorded segregation-of-duties residual).
**Still open:** G0-2 to G0-5, G0-7 to G0-10, and all of section B.
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

- [x] **G0-6 — Named Security Owner and security architecture sign-off.**
  **DECIDED 2026-11-12 — the Security Owner for v1 is Samuel Tessier.** A named
  individual, not a role.
  **Recorded residual: for v1, implementer = reviewer.** Samuel Tessier is sole
  author, owner and developer, and **no independent review exists for v1**. That is
  a segregation-of-duties gap, recorded as accepted for v1 development — it is not
  a satisfied control, and no later reader should read this entry as independent
  sign-off.
  Obligations accepted with the signature:
  - **Every sold deployment is individualized per client** — its own keys, its own
    audit chain, its own data boundary — as a **v1 acceptance criterion**, not a v2
    aspiration. Tracked against CR-10 (authentication) and CR-12 (keys, retention).
  - **External security review is required before the first client deployment.**
  See §F for these as trackable gates.

- [ ] **G0-7 — Who may affirm/dismiss findings; second reviewer requirement.** Role definitions and segregation of duties.
  Owner: Product + Legal Owners. Default: single authorized reviewer initially; second reviewer where owners decide. **Blocks CR-5.**
  *Note:* the G0-6 answer establishes that v1 has a single reviewer and no independent review. That matches the plan's default for an initial single reviewer, but it does not satisfy the "second reviewer where owners decide" half, and the decision on where a second reviewer is required is still open.

- [ ] **G0-8 — Export and decision enablement criteria.** Including external penetration test result and policy sign-off.
  Owner: Product + Security + Legal Owners. Default: no export/decision enablement before pen test and policy sign-off. **Blocks CR-9, CR-5 enablement.**

- [ ] **G0-9 — Incident-response owner and abort/rollback authority.** Named owner; rollback exercised before release.
  Owner: Operations + Security Owners. **Blocks CR-11.**

- [ ] **G0-10 — Whether call recordings, not just transcripts, are ever stored.**
  Owner: Counsel. Default: no recordings. **Blocks CR-1, CR-12.**
