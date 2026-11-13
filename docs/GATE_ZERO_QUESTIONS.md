# Gate Zero Questions — Required Human Decisions

**Status:** Blocking. No workstream may start until each item is recorded as decided
or explicitly blocked with an owner and date.
**Decided:** G0-1 (2026-11-12, amended to Option A the same day) and G0-6
(2026-11-12, Security Owner named, with a recorded segregation-of-duties residual).
**Still open:** G0-2 to G0-5, G0-7 to G0-10, and all of section B.
**Instructions:** Product Owner, Security Owner and Legal Counsel complete the
relevant items. Do not let an implementation agent invent answers.

## A. Gate Zero decisions (G0-1 through G0-10)

- [x] **G0-1 — Deployment model and adversary.**
  **DECIDED 2026-11-12: multi-user. AMENDED the same day — one OS account per user is
  required; a shared OS account is unsupported and must be refused at runtime
  (Option A).** Owner: Product Owner + Security Owner.
  Consequences in `docs/THREAT_MODEL.md` §2: the OS account is a trust boundary again
  (filesystem permissions, per-user keychain), but loopback is still not
  authentication, so CR-10.6 baseline controls stay mandatory in every mode. Raises
  the weight of **G0-3**.

- [ ] **G0-2 — Rule corpus ownership and approval.** Named legal content owner; citation, wording, effective dates; two-person approval for rule changes.
  Owner: Legal Content Owner. **Blocks CR-4.**

- [ ] **G0-3 — Confidentiality, privilege, PII, retention, legal hold, deletion.** Privileged material, third-party personal data, call recordings; retention and deletion policy; Law 25 flags.
  Owner: Counsel + Privacy Owner. Default: default-deny ingest/export of privileged/PII until policy is enforced. **Blocks CR-1, CR-2, CR-9, CR-12.** Raised in priority by G0-1.

- [ ] **G0-4 — Real source formats for texts/transcripts.** Anonymized samples for each format.
  Owner: Product/Content Owner. Default: no adapter without a real sample. **Blocks CR-2.**

- [ ] **G0-5 — Performance and usability targets.** Confirm or revise Section 12 defaults.
  Owner: Product Owner. **Blocks CR-6, CR-11.**

- [x] **G0-6 — Named Security Owner and security architecture sign-off.**
  **DECIDED 2026-11-12 — the Security Owner for v1 is Samuel Tessier.** A named
  individual, not a role.
  **Recorded residual: for v1, implementer = reviewer.** Samuel Tessier is sole
  author, owner and developer, and **no independent review exists for v1**. That is a
  segregation-of-duties gap, accepted for v1 development. It is **not** a satisfied
  control, and this entry must not be read as independent sign-off.
  Obligations accepted with the signature:
  - **Every sold deployment is individualized per client** — own keys, own audit
    chain, own data boundary — as a **v1 acceptance criterion**, not a v2
    aspiration. Tracked against CR-10 (authentication) and CR-12 (keys, retention).
  - **External security review is required before the first client deployment.**
  Both are recorded as shipping gates in §F.

- [ ] **G0-7 — Who may affirm/dismiss findings; second reviewer requirement.** Role definitions and segregation of duties.
  Owner: Product + Legal Owners. Default: single authorized reviewer initially; second reviewer where owners decide. **Blocks CR-5.**
  *Note:* G0-6 establishes a single reviewer and no independent review for v1. That
  matches the plan's default for an initial single reviewer but does not satisfy the
  "second reviewer where owners decide" half; where a second reviewer is required is
  still open.

- [ ] **G0-8 — Export and decision enablement criteria.** Including external penetration test result and policy sign-off.
  Owner: Product + Security + Legal Owners. Default: no export/decision enablement before pen test and policy sign-off. **Blocks CR-9, CR-5 enablement.**

- [ ] **G0-9 — Incident-response owner and abort/rollback authority.** Named owner; rollback exercised before release.
  Owner: Operations + Security Owners. **Blocks CR-11.**

- [ ] **G0-10 — Whether call recordings, not just transcripts, are ever stored.**
  Owner: Counsel. Default: no recordings. **Blocks CR-1, CR-12.**

## B. Reserved human decisions (H-1 through H-12)

- [ ] **H-1 — Deployment model and adversaries.** Owner: Product + Security Owner. Model decided by G0-1; the adversary set still needs sign-off in CR-0.
- [ ] **H-2 — Rule corpus ownership and approval.** Owner: Legal Content Owner.
- [ ] **H-3 — Who may affirm/dismiss; second reviewer.** Owner: Product + Legal Owners. See G0-7.
- [ ] **H-4 — Retention for messages, decisions, exports.** Owner: Counsel.
- [ ] **H-5 — Privileged material and third-party PII, Law 25 flags.** Owner: Counsel.
- [ ] **H-6 — Free-text search in shareable addresses.** Owner: Product Owner. Default: no.
- [ ] **H-7 — Performance and usability targets.** Owner: Product Owner.
- [ ] **H-8 — Call recordings storage.** Owner: Counsel.
- [ ] **H-9 — Production migration execution.** Owner: Operations Owner.
- [ ] **H-10 — Named Security Owner and threat-model sign-off.** Owner: Product + Security Owners. **Answered by G0-6** (Samuel Tessier, 2026-11-12), with the self-review residual recorded there.
- [ ] **H-11 — Export/decision enablement after pen test and policy.** Owner: Product + Security + Legal. Related to the external-review gate in §F.
- [ ] **H-12 — Incident-response and rollback authority.** Owner: Operations + Security.

## C. Views by owner

An item under more than one owner is not decided until **every** listed owner has
recorded a position.

| Owner | Claims | Co-owns |
|---|---|---|
| Product Owner | G0-4, G0-5, H-6, H-7 | G0-1 *(decided)*, G0-6 *(decided)*, G0-7, G0-8; H-1, H-3, H-10, H-11 |
| Security Owner — **Samuel Tessier** | G0-6 *(decided)* | G0-1, G0-8, G0-9; H-1, H-10, H-11, H-12 |
| Legal Counsel | G0-3, G0-10; H-4, H-5, H-8 | G0-2, G0-7, G0-8; H-2, H-3, H-11 |
| Operations Owner | G0-9; H-9, H-12 | — |
| Privacy Owner | — | G0-3 with Counsel |
| Legal Content Owner | G0-2; H-2 | — |

Law 25, privilege and consent flags are Counsel's to close, not the product's to
assume. The Security Owner cannot be a role placeholder, and for v1 the named person
is also the implementer — see the G0-6 residual.

### How to record an answer

Replace the checkbox with `DECIDED — <decision> — <owner name> — <YYYY-MM-DD>` or
`BLOCKED — <what is missing> — <owner name> — <YYYY-MM-DD>`. "BLOCKED" is a valid
outcome and must be recorded as one: an item left blank is indistinguishable from an
item nobody read.

## D. Sign-off record

| Item | Decision | Owner | Date | Notes |
|---|---|---|---|---|
| G0-1 | DECIDED, then AMENDED — multi-user; one OS account per user required, shared account unsupported | Product Owner + Security Owner | 2026-11-12 | Threat model rewritten for Option A. OS account is a boundary again; loopback still is not. Shared-account detection is required and has no owner yet |
| G0-2 | | | | |
| G0-3 | | | | Raised in priority by G0-1 |
| G0-4 | | | | |
| G0-5 | | | | |
| G0-6 | DECIDED — Security Owner for v1 is Samuel Tessier, also sole author, owner and developer; no independent review exists for v1. Each sold deployment must be individualized per client (own keys, own audit chain, own data boundary) as a v1 acceptance criterion, not a v2 aspiration | Samuel Tessier | 2026-11-12 | Named individual, not a role. Implementer = reviewer for v1, recorded as a residual. Per-client individualization is a shipping gate tracked against CR-10 and CR-12. External security review required before the first client deployment |
| G0-7 | | | | Partly answered by G0-6 (single reviewer for v1); where a second reviewer is required is open |
| G0-8 | | | | |
| G0-9 | | | | |
| G0-10 | | | | |

## E. How the shared-account residual is closed

The Security Owner's position was a **refusal**, not an acceptance: a user of a shared
OS account being able to read the ledger database, sidecar text and key files directly
is **not accepted**.

- [x] **Option A — separate OS accounts are required. SELECTED 2026-11-12.**
  One account per user; the product refuses multi-user operation when a shared account
  is detected. *Restores:* the OS account as a trust boundary, filesystem permissions,
  per-user key storage in the OS keychain. *Costs:* a deployment and support
  commitment rather than a code change; a shared account becomes unsupported; this
  amends the "not guaranteed" half of G0-1. *Obliges:* detection and refusal (a README
  sentence is not a control), a customer deployment requirement, and a migration for
  existing shared-account installs.
- [ ] **Option B — a per-user secret the application never stores. REJECTED
  2026-11-12**, retained as the analysed fallback. It would defend within a shared
  account by encrypting per user, at the cost of unrecoverable data loss on a
  forgotten passphrase and an unlocked session for every query, background task and
  export — and would need a key-escrow decision from G0-3 and Counsel.

Option A removes the primary adversary by removing the shared account. It does **not**
make loopback a boundary, so application authentication (CR-10.6) stays mandatory.
Whether Option A is enforceable in deployment, and who owns the detection requirement,
remain open.

## F. v1 shipping gates recorded at Gate Zero

Accepted with G0-6 on 2026-11-12. These are conditions on shipping v1 to a client at
all, not aspirations.

- [ ] **Per-client individualization.** Every sold deployment gets its own keys, its
  own audit chain and its own data boundary. No shared keys, no shared chain across
  clients. Tracked against **CR-10** (authentication) and **CR-12** (keys, retention).
  Status: not started, no owner assigned.
- [ ] **External security review before the first client deployment.** Because v1 has
  no independent review (G0-6 residual), an external review of this threat model, the
  control set and the deployment procedure is a gate, not a recommendation. Related:
  **G0-8** (pen test) and **H-11**.
- [ ] **Self-review residual accepted and dated.** Accepted for v1 development only. It
  does not extend to sold deployments, which is why the two gates above exist.
