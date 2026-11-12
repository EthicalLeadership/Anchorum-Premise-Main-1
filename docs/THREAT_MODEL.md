# Threat Model — Conversation Ledger & Replay (CR-0)

**Status:** Draft for Gate Zero / CR-0 sign-off
**Deployment model (G0-1, amended 2026-11-12):** multi-user, **one OS account per
user required**. A shared OS account is **unsupported** — the product refuses
multi-user operation when it detects one (Security Owner, Option A).
**Security owner (G0-6):** **DECIDED 2026-11-12 — Samuel Tessier.** He is also the
sole author, owner, and developer of this software; there is no independent security
review for v1. Implementer = reviewer is recorded as a residual (see §8). Each sold
deployment is individualized per client (own keys, audit chain, data boundary) as a
v1 acceptance criterion (see §2).
**Scope:** CR-0 through CR-12 as defined in Revision 2. Nothing here authorizes code
or migration work.

## 1. Purpose

This document identifies the assets, trust boundaries, adversaries, abuse cases and
mitigations for the Conversation Ledger & Replay system, for CR-0 sign-off. It has
been through two decisions: G0-1 recorded multi-user deployment with a shared OS
account possible; the Security Owner refused the residual that implied; Option A was
then selected.

## 2. Trust boundaries under the decided model

**Decided (G0-1 as amended):** multi-user, one OS account per user, shared account
refused at runtime.

What Option A restores:

1. **The OS account is a user boundary again.** Per-user file permissions and
   keychain entries separate one user's database, sidecar text, exports and keys
   from another's. Reading the filesystem no longer reads another user's ledger.
2. **Per-user key storage is meaningful**, so encryption at rest is a real control
   rather than a formality.
3. **Session state belongs to a person again**, because browser profile, keychain
   and filesystem are all per account.

What it does **not** restore — the design may not assume any of these:

1. **Loopback is still not authentication.** Any local user can connect to a port on
   `127.0.0.1`; Host and Origin checks are not identity checks, because a local
   process sets both. The application must authenticate its own users in every mode
   (CR-10.6).
2. **A stolen application credential is still full impersonation.** OS separation
   says nothing about a borrowed passphrase.
3. **Malware in the victim's own account** reads what that account reads, including
   the keychain while unlocked.
4. **The account owner can always read their own data.** That is the product working
   as intended.

Boundaries, strongest first: the OS account (enforced by the operating system, not
by us); the application's authentication and authorization layer (the only boundary
for network origin and for within-account roles); application-enforced case scope;
the local server process; the local database and audit sink; untrusted ingest input;
the signed rule corpus; exports as high-risk egress; external anchoring as
tamper-evidence rather than storage.

**What Option A obliges, and what is not yet done:** the product must *detect* a
shared account and refuse to run multi-user on it — a README sentence is not a
control; the one-account-per-user requirement becomes a customer deployment
obligation and a support commitment; and existing shared-account installations need
a stated migration, because silently refusing to start is not a migration.

**Option B, rejected but retained.** A per-user secret the application never stores
would defend *within* a shared account, at the cost of unrecoverable data loss on a
forgotten passphrase and an unlocked session for every query, background task and
export. It is the analysed fallback if Option A proves unenforceable in practice,
and it would then need an escrow decision from G0-3 and Counsel.

**Per-client individualization (v1 acceptance criterion, decided 2026-11-12).** Each
sold deployment is a separate security domain: its own signing and anchoring keypair,
its own audit chain with independent continuity, its own data boundary (database,
sidecar text, exports, anchor directory), and no shared trust relationship with any
other client deployment. A compromise of one client's keys does not weaken another's;
an upgrade at one deployment does not touch another's data or keys. This is a
shipping gate for v1, tracked against CR-10 (authentication, key handling) and CR-12
(key storage, retention), not a future upgrade. Whether the deployment contacts a
vendor licensing service, and how that service affects the client's threat model, is
a separate decision to be recorded before the first client deployment.

## 3. Assets

| Asset | Why it matters | Primary controls |
|---|---|---|
| Message Ledger | Faithful record of communications | CR-1 append-only, source hashes, case scope, file permissions |
| Bitemporal clocks / as-of tokens | Reproducible replay | CR-1, CR-6 snapshot isolation |
| Audit Chain | Proof of who did what, when | CR-10.7 separate sink, keyed, fail-closed, anchored |
| Identity Map | Correct attribution of people | CR-3 case-scoped, confirmed, append-only |
| Application identity and session | Boundary between service users | CR-10.6 authentication, session binding, re-auth |
| Credentials and keychain entries | Gate to one user's ledger | CR-10.6, CR-12; per-user keychain under Option A |
| Rule Corpus | Trustworthy findings | CR-4.6 signed, immutable, two-person approval |
| Decision Ledger | Human decisions and reasons | CR-5 append-only, idempotent, fail-closed audit |
| Exports / evidence packs | Shareable provenance | CR-9 signed manifest, one-time download, approval |
| Privileged / PII data | Legal and privacy exposure | CR-12 classification, default-deny, redaction, retention |
| Secrets and keys | Integrity and confidentiality | CR-10, CR-12; no secrets in logs |

## 4. Adversaries

| Adversary | Capability | Abuse case | Mitigation |
|---|---|---|---|
| Another OS user on the machine | Cannot read another account's files; **can** reach the loopback port and set Host/Origin | Call the API unauthenticated; replay a leaked token; guess a weak credential | Authentication on every request regardless of interface; no unauthenticated route touching case data; rate limiting (CR-10.6) |
| Malicious insider (account owner) | Full control of their own files, DB, audit, exports | Alter their own decisions; rewrite their own audit chain | CR-10.7 keyed audit + anchoring; append-only tables. Limit: the owner is trusted with their own data |
| Hostile email/text sender | Crafted bodies, filenames, transcripts, attachments, control characters | Parser compromise, XSS, formula injection, resource exhaustion | CR-2 parser isolation and bounds; CR-10 escaped rendering, sandboxed sources; CR-9 injection-safe export |
| Compromised dependency | Supply chain | Backdoor, exfiltration, integrity bypass | CR-10.9 approval, pinning, SBOM, advisory and secret scans |
| Accidental insider | Wrong case, wrong export, session left unlocked | Over-share within entitlement | CR-10.1/10.5 case isolation; CR-12 redaction; CR-9 approval and one-time download; idle lock |
| Local malware | Reads memory and files of its own account | Steal credentials or keys, alter audit locally | Key handling, audit anchoring (CR-10, CR-12); documented residual |
| Network attacker (if the bind widens) | Network access to the service | Unauthorized access, CSRF, origin abuse | CR-10.6 baseline; TLS for any non-loopback mode; refuse non-loopback without auth |

## 5. Key abuse cases

1. **Unauthenticated local access** — loopback is never authentication; no default-user fallback when a credential is absent (CR-10.6).
2. **Cross-case exposure** — server-side case scoping on every query; foreign identifiers answer as nonexistent ones (CR-10.1, 10.5).
3. **Silent record alteration** — append-only at DB level; corrections supersede; audit sink separate and keyed (CR-1.9, CR-5, CR-10.3/10.7).
4. **Replay shows future knowledge** — occurred, captured and decision time; as-of token for snapshot consistency (CR-6).
5. **Rule tampering changes past meaning** — rules signed and immutable; finding identity includes rule version, detector, algorithm version and evidence (CR-4.6–4.8).
6. **Export exfiltration** — signed manifest, one-time authorized download, privilege exclusion, audit (CR-9).
7. **Privileged/PII leakage** — default-deny ingest and export until CR-12 policy is enforced; redaction in UI, logs, exports (CR-12).
8. **Audit outage allows action** — decisions and exports fail closed if the audit write fails (CR-5.9, CR-10.7).
9. **Hostile content execution** — content rendered as escaped text only; sources sandboxed; attachments refused unless approved (CR-2, CR-10).
10. **Replay/UI flooding** — throttled announcements, windowed rendering, reduced motion (CR-6, CR-8).

## 6. How CR-10 and CR-12 mitigate these

CR-10 asks whether the system can be trusted to record what happened — authentication,
authorization, integrity, audit, supply chain. CR-12 asks what it may hold and for how
long — classification, privilege, redaction, retention, keys. Neither substitutes for
the other: a tamper-evident ledger holding material it should never have ingested is
still a failure.

| Adversary | CR-10 | CR-12 | Residual |
|---|---|---|---|
| Another OS user | Auth on every request, identity-bound sessions, re-auth for decisions and exports, fail-closed audit (10.1, 10.5, 10.6, 10.7) | Retention and redaction bound what an impersonation reaches; privileged exports denied by default | A stolen credential is indistinguishable from its owner; filesystem separation does not authenticate the network path |
| Malicious insider (owner) | Keyed audit sink outside the app role, fail-closed writes, anchoring, append-only tables (10.3, 10.7) | Retention shortens exposure; export authorization | Detection, not prevention; anchoring bounds undetected rewriting to the last anchor interval |
| Hostile sender | Content never executed, sources sandboxed, attachments refused by default, parser bounds (CR-10) | Default-deny ingest of privileged/PII until classification exists | Controls are structural, not semantic: a privileged message from an authorised source is ingested and flagged, not blocked |
| Compromised dependency | Pinning, approval, SBOM, secret and advisory scans (10.9) | No signing keys reachable from dependency code paths | Approval is a human step and can be wrong; the SBOM records what was approved, not that it was safe |
| Accidental insider | Case scoping, indistinguishable foreign ids, export authorization, idle lock (10.1, 10.5) | Default-deny export of privileged or PII packs; redaction at the boundary | A user entitled to two cases can read both; segregation of duties is a role decision |
| Local malware | Anchoring makes rewriting detectable; audit fails closed so tampering leaves a gap | Keychain keys are the boundary; unlocked-session exposure is not defended | Malware in the session reads what the session reads, including typed credentials |
| Network attacker | TLS for non-loopback, mandatory auth, CSRF and Origin, baseline unconditional (10.6) | Export egress authorized, encrypted, audited; retention bounds the yield | Widening the bind is a deployment change: re-sign CR-0 first |

**Why the baseline is unconditional.** The platform cannot verify that every
deployment is one account per user. The refusal (§2) is the control for what it can
see; the baseline controls are for what it cannot. Host and Origin are checked, CORS
is never wildcard, CSRF tokens protect state-changing routes, and the application
authenticates its own users rather than trusting the OS session.

**What CR-12 cannot do.** It cannot decide whether a document is privileged. That is
a human judgement recorded as a flag; the control enforces default-deny on documents
carrying it. Where classification is wrong, the system faithfully protects the wrong
set — a G0-3 policy failure, not one code closes.

## 7. Residual risks

- **Loopback is not a security boundary even with separate accounts.** Any local user
  can reach the port; application authentication is what stops them, in every mode.
- **Credential compromise defeats everything above it.**
- **The account owner is trusted with their own ledger.** Tamper-evidence detects
  alteration; it does not prevent it within an account.
- **Encryption at rest now means something** against other users and stolen media; it
  is not protection against malware in the unlocked session.
- **The shared-account refusal is only as good as its detection.** A deployment that
  bypasses it lies outside this model.
- **Completeness is not guaranteed** — the ledger holds what was ingested.
- **Candidate findings can be wrong.** Review, exact evidence and human decisions are
  the control.
- **The rule corpus is a governance weak point** without maintained, cited, approved
  rules.
- **No legal conclusions are made here.** Privilege, consent, retention and Law 25 are
  flagged for qualified people.

## 8. Sign-off

Recorded:

- **G0-1** — DECIDED 2026-11-12, multi-user; **amended** by the Security Owner's
  refusal of the shared-account residual and selection of **Option A**: one OS account
  per user required, shared account unsupported and refused at runtime.
- **Option B** — rejected 2026-11-12, retained in §2 as the analysed fallback.

Still open and blocking:

- **G0-6 — DECIDED 2026-11-12.** Security Owner: **Samuel Tessier**. He is also the
  sole author, owner, and developer; there is no independent security review for v1.
  Implementer = reviewer is recorded as a residual, not a control.
- **Per-client individualization — DECIDED 2026-11-12 as a v1 acceptance criterion.**
  Each sold deployment is a separate security domain (own keys, audit chain, data
  boundary, anchor directory). Has no workstream yet; must be assigned before the
  first client is deployed. Tracked against CR-10 and CR-12.
- **G0-3 — privilege, PII, retention.** Now the next control that matters: with OS
  separation restored, retention and redaction bound exposure when authentication is
  defeated.
- **Control matrix review.** The traceability matrix must be signed with this model
  and is still entirely `Uncovered`.
- **The detection requirement in §2 has no owner or workstream.** Until it does,
  Option A is a statement of intent rather than a control.

No workstream may proceed until CR-0 is signed.
