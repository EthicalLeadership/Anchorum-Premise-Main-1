# ANCHORUM System Architecture And Security Specification

**Status:** Product specification, version 1.0  
**Target:** Commercial-grade foundation; this document is not a production-readiness certification.

## 1. Architecture Principles

1. Evidence bytes and their custody are authoritative; AI providers, models, and analysis are replaceable.
2. Every material fact, finding, contradiction, strategy assertion, and exported statement has explicit provenance or is visibly marked as an operator-authored assumption.
3. Original evidence is immutable to application users and AI workers. Corrections create versioned derivatives/events; no mutation erases history.
4. Begin as a modular monolith with clear domain and adapter boundaries. Split independently scaling workers later only on measured need.
5. AI jobs are bounded, schema-constrained, policy-authorized, observable, and human-reviewed. Confidence is not truth.
6. Tenant isolation, security, audit, and recovery are platform foundations, not later enhancements.
7. Evidence content is hostile data. It is never system/developer instruction and has no authority to grant tools or permissions.
8. Product requirements, implemented repository behavior, and independently verified controls are documented separately.

## 2. Current Repository Baseline And Gaps

The repository now contains a React/TypeScript presentation shell in `interface/`, but still has no HTTP API or backend FastAPI application. The shell is not wired to case or evidence services. `pyproject.toml` presently includes SQLAlchemy and PyJWT, but not FastAPI. The existing SQLAlchemy schema has a small set of models and is not established as the runtime system of record.

`dossier_pipeline/evidence.py` stores canonicalized JSON packets/custody events in SQLite. It hashes packet JSON, chains packets, supports Merkle checkpoint records, and signs with HMAC-SHA256 using `GDC_EVIDENCE_SECRET`; an unset secret produces an unbound signer. Its input is structured dictionaries, not a streaming upload of original file bytes. It does not by itself enforce WORM object storage, trusted time, independent signing keys, tenant isolation, production key rotation, or protection from a privileged database/storage operator. These are useful integrity primitives, not proof of immutable uploaded originals.

Existing auth, trust-boundary, privacy, output-gate, registry, provenance, and governed-decision modules should be assessed and adapted behind application services. `README_RESIDENT_AI.md` describes a local RAG implementation, but the described package was not found in this repository during initial inspection; treat it as unavailable until reconciled. No reusable swarm service was found. Do not expose CLI code as HTTP handlers or silently introduce a second source of truth.

## 3. Proposed Modular Monolith

### Logical Components

- **Web client:** React + TypeScript; renders the War Room and operator workflows. It contains presentation and request coordination only, never authorization policy or evidence-integrity authority.
- **HTTP/API layer:** FastAPI; authentication middleware, request parsing, response schemas, rate limits, and transport mapping. Routes call application services and do not embed domain logic.
- **Application services:** case, membership/authorization, evidence intake, evidence query, review lifecycle, mission, legal lens, strategy, and export use cases. These own transaction boundaries, idempotency, and policy checks.
- **Domain modules:** case control, evidence identity/custody, provenance graph, intelligence/review, mission orchestration, legal plugins, and governance/audit. Core modules depend on ports, not specific cloud/model vendors.
- **Metadata database:** relational database; PostgreSQL is the recommended production candidate. Tenant/case ownership is enforced in services and reinforced with database constraints/row policies where feasible. SQLite may remain a local/test adapter only.
- **Object storage:** port for immutable originals, derivatives, and export artifacts. Production adapter must meet documented versioning/retention/immutability capability tests. Candidate implementations include self-hosted S3-compatible storage and managed object storage; choose concrete products only after deployment and procurement review.
- **Search:** separately managed lexical index and optional vector index built only from authorized derived text. Index data is disposable/rebuildable and never the evidence record.
- **Job execution:** worker process consumes typed, versioned jobs from a queue/outbox. The queue implementation is an adapter. Persist job intent and status in the relational store; retries are idempotent and observable.
- **AI Gateway:** one provider-neutral interface for model calls, embeddings, extraction, structured generation, and evaluation. It records provider/model/version, prompt/config hash, evidence scope, retrieval IDs, token/latency/error metadata, and output hash. Provider responses are untrusted.
- **Jurisdiction plugins:** versioned configuration/data and plugin interface isolated from general evidence and intelligence. Legal content has source, jurisdiction, effective date, license, update/version, and validation state.
- **Audit and observability:** append-only domain audit events, security events, mission/job telemetry, metrics, and traces. Operational telemetry is not the audit source of truth.

### Deployment Profiles

The logical architecture supports a hosted multi-tenant service, single-tenant/self-hosted deployments, private AI, and restricted/air-gapped deployments. The first implementation should provide local developer/test composition and a production reference profile; it must not claim air-gap compliance until outbound calls, updates, telemetry, and dependency/artifact distribution are constrained and tested.

White-labeling is a tenant/theme/branding boundary, not a fork of domain logic. Configuration and plugins are versioned, allow-listed, and audited. Deployment-specific secrets and keys are injected by a secret manager or operator-managed protected store, never committed or shipped in frontend bundles.

## 4. Trust Boundaries And Data Flow

### Evidence Intake

1. Authorize the user for tenant and case; issue a short-lived, scoped upload session with size/type limits and a unique idempotency key.
2. Stream bytes into a quarantine location while calculating SHA-256 over the exact byte sequence received. Record filename and user-supplied metadata separately from verified content facts.
3. Preserve the exact original in the configured immutable storage adapter. Read back or otherwise verify stored bytes against the calculated hash before marking preservation successful. Record storage object/version ID, algorithm, byte count, hash, and timestamp source.
4. Write the evidence identity and custody event using an idempotent state transition/outbox protocol. If storage or metadata commit partially fails, retain a recoverable state and reconcile; never report success until both preservation and registry commit are verified.
5. Scan and parse in a restricted worker. Reject/quarantine malicious, unsupported, encrypted, malformed, oversized, archive-bomb, or resource-exhausting inputs. Do not execute macros, embedded scripts, links, or active content. Network egress is denied by default.
6. Store extraction, OCR, normalized text, thumbnails, and other derivatives as separately identified artifacts, each hashed, versioned with tool/config versions, and linked to parent evidence. A parser correction creates a new derivative; it never alters original bytes.
7. Index only authorized derivatives. Index failures do not invalidate preserved evidence; stale/partial state is visible and retryable.

Email/container ingestion must define what constitutes each original unit, preserve container bytes when supplied, and record extraction relationships. Folder ingestion must produce per-file outcomes and deterministic retry/deduplication semantics. Duplicate detection is advisory until the exact-byte hash is compared; identical bytes do not imply identical legal context.

### Intelligence And Output

1. The mission service checks tenant/case access, role, allowed mission type, evidence scope, data residency, provider policy, quotas, and required human approvals.
2. The orchestrator resolves a frozen list of evidence versions/passages and prompt/config versions. It passes evidence only as quoted/typed data, never as executable instructions.
3. Workers have read-only access to explicitly authorized evidence derivatives and write access only to their own job/result namespace. They cannot change case permissions, custody records, originals, retention rules, or publish exports.
4. Responses are parsed against versioned schemas; citation IDs must be members of the retrieval allow-list and resolve to stable evidence versions/passages. Invalid, uncited, out-of-scope, or policy-violating output is quarantined and not exposed as a finding.
5. Every result records model/provider/version, prompt/config hash, evidence scope, retrieval IDs, execution timestamps, output hash, validation results, and status. Confidence is labeled as model confidence with calibration/version where available.
6. Results enter `AI_GENERATED` / `NEEDS_REVIEW`. Only an authorized operator can correct, verify, approve, reject, retract, or supersede according to transition policy. No AI result directly triggers an external communication or authoritative legal decision.
7. Strategy and exports snapshot approved inputs and version references. Re-export after source supersession creates a new artifact and manifest; previous output remains auditable subject to retention policy.

## 5. Integrity, Audit, And Lifecycle Requirements

### Evidence Integrity Contract

For each original, record at minimum: stable evidence ID; tenant/case scope; original filename as received; exact byte count; SHA-256 algorithm and digest over raw received bytes; receipt timestamp plus trusted-time source/uncertainty; uploader identity; upload session/idempotency key; immutable storage identifier/version; storage retention/object-lock policy; custody events; integrity verification results; and each derivative's parent, content hash, parser/tool/config version, and creation event.

Required controls:

- Application permissions cannot overwrite/delete an original. Production storage enforces versioning and configured retention/object-lock controls against application credentials.
- Hash verification can be rerun against retrieved original bytes. Periodic integrity jobs report mismatches and fail closed for affected exports/analysis.
- Hash chaining/Merkle checkpoints are tamper-evidence aids; checkpoints need protected signing keys and an independently retained or externally witnessed record to resist privileged rewrite. HMAC alone is symmetric and does not provide independent public verification.
- Timestamp claims identify whether they come from the application clock, a synchronized trusted time service, or an independent timestamp authority. Do not imply legal-grade trusted time without that authority.
- Custody actions identify actor/service identity, action, target, timestamp source, authorization decision, correlation ID, and signature/record hash. Failed attempts and administrative exceptions are auditable.
- Retention/legal hold is policy-enforced across originals, derivatives, indexes, exports, backups, and replicas. Legal deletion is a controlled, authorized destruction event with scope and verification; audit records retain only information permitted by policy/law. Tombstoning is not a claim that bytes were destroyed.

### Audit And Review

Audit events are append-only from application behavior, include before/after version references or a safe diff, actor, policy decision, timestamp, and reason for privileged transitions. A failed required audit write fails the governed operation closed. Trace/metrics may fail open only when they are explicitly non-authoritative and the audit event succeeded.

Review state transitions are server-enforced and versioned: `AI_GENERATED → NEEDS_REVIEW → HUMAN_VERIFIED → APPROVED`, with alternate `REJECTED`, `RETRACTED`, and `SUPERSEDED` outcomes. Define allowed transitions by role, two-person review rules for selected actions, re-review after source/model/prompt changes, correction semantics, reason requirements, and optimistic concurrency. Approval attaches to an exact output version and provenance snapshot; changing it creates a new version requiring review.

## 6. Security Requirements And Threat Model

| Threat | Required controls | Verification evidence |
| --- | --- | --- |
| Cross-tenant/case data access | Tenant-scoped queries, object-level authorization, opaque IDs are not security, consistent checks in APIs/search/storage/export/jobs, DB constraints/RLS defense-in-depth | Automated negative tests across every object route, background worker, search, and export; independent review |
| Prompt injection in PDF/email/web-derived text | Treat content as untrusted data; instruction/data separation; no evidence-granted tools; allow-listed job tools; output/citation validation; hostile evaluation corpus | Red-team fixtures that attempt secret exfiltration, tool invocation, privilege changes, and fabricated citations; prove no authority/state change |
| Malicious parser input | Quarantine, malware scan, sandbox/container, no network by default, resource/time/size limits, patched parsers, archive-depth/expansion controls, content-type detection | Malformed/oversized/archive-bomb/macro tests; sandbox escape review; recovery tests |
| Poisoned evidence or duplicate ambiguity | Hash exact bytes; track uploader/source and duplicate relation; preserve conflicting submissions; no automatic replacement or merge | Same-name/different-byte and same-byte/different-context tests; chain verification |
| AI hallucination/unsupported claim | Schema-constrained output, retrieval allow-list, citations to exact evidence version/location, abstention, human approval, evaluation sets | Citation-resolution and unsupported-claim evaluation; regression gates; reviewer usability tests |
| Privilege escalation/agent overreach | Separate user, API, worker, storage, and signing identities; least privilege; explicit policy engine; no agent permission changes or original-write capability | Threat tests and credential/capability review; audit denied attempts |
| Credential/key compromise | Managed secret/key storage, scoped identities, rotation/revocation, envelope encryption, separated signing and storage keys, no secrets in logs/client | Rotation/revocation drill, secret scanning, key access audit, recovery test |
| Export leakage/tampering | Reauthorize at generation and download, content manifest, signed/hash-verified artifact, short-lived scoped links, watermark/classification policy, audit | Cross-tenant, expiry, revoked-access, partial-processing and tamper tests |
| Retention/deletion conflict | Legal hold, retention policy precedence, controlled destruction, backup/index/export scope, approval and audit | End-to-end retention/deletion drill including backup restore and legal hold |
| Resource exhaustion/abuse | Upload/mission quotas, rate limits, bounded concurrency, cancellation, timeout, queue isolation, circuit breakers | Load/soak and abuse tests; bounded 500-document acceptance scenario |
| Audit repudiation or rewrite | Restricted append-only audit writer, sequence/hash validation, protected key, external/independent checkpoint policy, privileged-action audit | Tamper test, restore/reconcile drill, security review of trust assumptions |

## 7. Authorization And Identity

Use organization/tenant membership plus case-level roles and attributes. Initial role vocabulary should distinguish tenant admin, case manager, operator/investigator, reviewer, legal reviewer, auditor/read-only, and service worker; exact grants are specified in the permission matrix. ABAC attributes include tenant, case, matter sensitivity, evidence restriction, jurisdiction, assignment, and export classification where needed.

All access is deny-by-default and checked on every server-side operation. Background jobs carry a signed/validated initiating principal and authorization snapshot; execution rechecks current policy before sensitive reads/writes. Revocation stops future work and prevents result access/download. Service identities are separate and scoped. SSO/MFA are integration requirements for production profiles; local dev authentication cannot be enabled in production.

## 8. API, Transactions, And Jobs

- Version APIs and use explicit request/response schemas; do not expose ORM models directly.
- Mutations require actor, tenant/case scope, idempotency key where retry is possible, and an audit record.
- Use relational transactions for metadata and an outbox for durable job/event publication. External storage writes require a recoverable saga/state machine, reconciliation, and visible partial states; a DB transaction cannot atomically commit an object store.
- Job states: `QUEUED`, `RUNNING`, `NEEDS_INPUT`, `SUCCEEDED`, `PARTIAL`, `FAILED`, `CANCEL_REQUESTED`, `CANCELLED`. Persist attempts, retry policy, deadline, lease/heartbeat, error class, and outputs. Retry transient failures with bounded backoff; do not retry policy failures indefinitely.
- At-least-once delivery is assumed; handlers are idempotent. Exactly-once execution is not promised.
- Enforce request/file/page limits, timeouts, pagination, rate quotas, and safe error responses. Never return raw parser/model exceptions or secrets.

## 9. Observability, Resilience, And Operations

Structured logs use correlation, tenant/case references where safe, actor/service identity, job and evidence IDs; avoid raw document contents, credentials, and unnecessary sensitive personal information. Separate security/audit events from ordinary logs and define access/retention. Metrics cover upload outcomes, processing latency/failures, queue age, integrity checks, citation validation, mission cost/latency, retries, export outcomes, and authorization denials without leaking content.

Define service-level targets and RPO/RTO before production launch. Provide encrypted backups, tested restore, key recovery, object-store retention checks, index rebuild, queue recovery, migration/rollback, incident response, and evidence-integrity incident procedures. A successful backup is not verified until restoration and hash-chain/object checks pass.

For 50–500 representative documents, benchmark ingest, OCR/parsing, indexing, semantic search, chronology, and mission completion separately; define the user-visible “within minutes” target only after representative hardware, corpus, and model are measured. Preserve partial progress and per-document outcomes under failure.

## 10. Architecture Decisions And Gates

| Decision | Current recommendation / requirement | Gate before production |
| --- | --- | --- |
| Application shape | React/TypeScript + FastAPI modular monolith | Validate team/toolchain and deployment profile |
| Metadata DB | PostgreSQL candidate; explicit tenant constraints and migrations | Select managed/self-hosted product, HA, encryption, backup and RLS strategy |
| Original storage | Immutable object-storage port with versioning/retention lock | Prove retention controls, admin threat model, readback verification, restore and deletion behavior |
| Evidence signing/time | Separate signing key; independent checkpoint/time option | Select KMS/HSM/signature and trusted timestamp/witness model; rotate/revoke drill |
| Queue | Durable adapter plus DB outbox; at-least-once/idempotent workers | Select broker and outage/replay operational model |
| Identity | OIDC/SSO + MFA production integration; local-only dev auth | Select provider, lifecycle, tenant mapping, break-glass and incident recovery |
| AI | Provider-neutral gateway, allow-list, data-boundary policy, private/local option | Approve provider, residency, training/retention terms, key/secrets and offline mode |
| Search | Rebuildable lexical index; optional vector adapter | Select product and authorization/filter strategy; index deletion/rebuild validation |
| Legal content | Versioned jurisdiction plugin and sourced authorities | Confirm licensing, official source hierarchy, currency/update owner, validation/review workflow |
| Retention/deletion | Policy per tenant/matter and legal hold | Counsel/security approval for originals, derived data, backups, exports, logs and deletion proof |
| Self-host/air-gap | Architecture constraint, not MVP release claim | Inventory every egress/dependency/update/telemetry path and test offline operation |

## 11. Test And Release Gates

- Unit/property tests for state machines, hashing/canonicalization, idempotency, provenance resolution, policy and review transitions.
- Database/object-store integration tests for partial failures, duplicate requests, readback, versioning, retention lock, restore, and deletion.
- API tests for authorization on all object types, tenant isolation, audit failure closed, and safe errors.
- Browser tests for intake, War Room, review, correction, mission, and export; accessibility checks for primary workflows.
- Adversarial document and prompt-injection regression suite; parser sandbox resource/egress tests.
- AI evaluation set for extraction, citations, abstention, contradictions, and calibration; model/prompt version changes require regression review.
- Load/soak, queue restart, outage, backup restore, key rotation, and disaster recovery exercises.
- Security assessment and independent threat-model review before production claims.

Existing tests/CI remain part of the repository baseline. Passing unit tests alone does not establish commercial readiness. Release notes state which controls are implemented, configuration-dependent, externally enforced, and independently verified.
