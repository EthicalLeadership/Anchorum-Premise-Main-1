# ANCHORUM MVP Backlog

**Status:** Ordered product/engineering backlog, version 1.0  
**Scope:** First useful, production-minded case intelligence workflow; not a claim of production readiness.  
**Size:** 72 independently reviewable tickets. Dependencies flow top-to-bottom within and across phases unless stated otherwise.

## MVP Outcome

A professional operator can create a Quebec/Canada labour case, manage parties/objectives/tasks, ingest and preserve 50–500 representative PDFs, DOCX, images, and supported email files, search and review source-linked chronology/intelligence, run bounded Blue/Red missions, approve/reject results, and produce a provenance-complete export/audit package. Security, tenant isolation, evidence integrity, and audit are foundational acceptance conditions, not stretch tasks.

Ticket acceptance is not complete until its automated/manual verification evidence is recorded. `AI GENERATED`, confidence, or a visible hash alone does not satisfy human review, truth, or immutable-storage requirements.

## Phase 0: Product And Security Foundation (FND)

- [ ] **FND-01 Domain boundaries and glossary.** Define bounded modules, ownership, forbidden dependencies, and canonical terms for evidence, artifact, claim, finding, verified fact, strategy, mission, and audit. **Accept:** architecture and data model use terms consistently; domain review signs off.
- [ ] **FND-02 Threat model.** Model tenants, users, admins, API, workers, AI providers, parsers, storage, search, and exports; cover listed hostile inputs and privileged threats. **Accept:** each threat has owner, control, residual risk, and test.
- [ ] **FND-03 Permission matrix.** Define actions/resource scopes for tenant admin, case manager, operator, reviewer, legal reviewer, auditor, and workers. **Accept:** deny-by-default matrix covers UI/API/jobs/search/export and separation-of-duties cases.
- [ ] **FND-04 Review and lifecycle state machines.** Specify evidence, mission, finding, timeline, strategy, export, retention, and review transitions. **Accept:** illegal transitions, correction, rejection, retraction, supersession, concurrency, and actor/reason requirements are testable.
- [ ] **FND-05 Persistence and migration decision.** Select metadata DB and schema migration strategy; PostgreSQL is the recommended production candidate. **Accept:** local/test/production profiles, tenant constraints, migration/rollback, and existing-model coexistence are documented.
- [ ] **FND-06 Immutable-storage capability contract.** Define object-store port and mandatory version, retention, readback, access-control, legal-hold, recovery, and deletion capabilities. **Accept:** adapter conformance test plan and local-vs-production auditables are explicit.
- [ ] **FND-07 Hash, signer, and timestamp model.** Define raw-byte digest, signing key separation/rotation, checkpoint witnessing, time-source semantics, and verification. **Accept:** threat assumptions and independent-verification limits are documented; unset keys fail closed in production.
- [ ] **FND-08 Durable event/job delivery.** Define transactional outbox, idempotency scope, retry policy, leases, cancellation, and reconciliation for DB/object-store/queue operations. **Accept:** crash points and recovery behavior have integration test cases.
- [ ] **FND-09 Retention/deletion/legal-hold policy model.** Define data categories and behavior across originals, derivatives, indexes, caches, provider data, exports, logs, backups. **Accept:** legal hold precedence and verifiable destruction semantics approved by security/counsel.
- [ ] **FND-10 Legal-content sourcing plan.** Choose first plugin scope, official/authoritative source hierarchy, licensing, updates, validation owner, and stale-content behavior for Quebec/Canada labour. **Accept:** no invented citation path; source/version requirements are reviewable.
- [ ] **FND-11 AI evaluation and adversarial corpus plan.** Define representative de-identified or synthetic fixtures, expected structured outputs, citation checks, prompt-injection cases, and regression thresholds. **Accept:** datasets have provenance/licensing and release gate ownership.
- [ ] **FND-12 MVP acceptance and performance protocol.** Define representative 50–500 file corpus, hardware/provider conditions, task measures, and target meaning for “within minutes.” **Accept:** measured baseline and performance target approval; no unsupported latency promise.

## Phase 1: Application And Governance Platform (PLT)

- [ ] **PLT-01 App workspace skeleton.** The React/TypeScript shell now exists in `interface/`; complete the workspace by wiring it to a FastAPI application in modular-monolith structure, with independent local/test commands. **Accept:** health/readiness checks work; CI builds both; no domain logic in routes.
- [ ] **PLT-02 Configuration and secrets.** Add typed environment/config profiles, secret injection, startup validation, and production prohibition of dev defaults. **Accept:** missing production secrets/config fail closed and never appear in logs or client bundles.
- [ ] **PLT-03 Identity adapter.** Integrate production OIDC/SSO/MFA boundary and local-only developer identity mode. **Accept:** issuer/audience/signature/expiry are checked; dev mode is impossible in production configuration.
- [ ] **PLT-04 Tenant and membership services.** Implement tenant, member invitation/status/revocation, and scoped identity lookup. **Accept:** revoked users lose API/job/result/export access; cross-tenant negative tests pass.
- [ ] **PLT-05 Authorization policy service.** Implement centralized role/attribute checks for tenant/case/object/action. **Accept:** all endpoints and worker access paths call policy; deny-by-default and audit denial tests pass.
- [ ] **PLT-06 Database migrations and transaction base.** Implement migration tooling, constraints, transaction handling, and safe test fixtures. **Accept:** fresh install and upgrade path work; production never relies on `create_all`.
- [ ] **PLT-07 Audit event service.** Record actor, scope, action, decision, time source, reason, correlation, object version, and safe before/after hashes. **Accept:** required write failure blocks governed mutation; content/secrets are not dumped into events.
- [ ] **PLT-08 Audit access and verification.** Provide restricted query/export and chain/checkpoint verification for audit events. **Accept:** tamper test detects changed/missing sequence; UI distinguishes audit from custody and ordinary telemetry.
- [ ] **PLT-09 Durable outbox and queue adapter.** Publish persisted jobs/events with bounded at-least-once delivery. **Accept:** crash/replay test creates no duplicate domain result and no lost job intent.
- [ ] **PLT-10 Worker identity and isolation.** Give workers scoped credentials, per-job context, resource limits, and no original-write/admin capabilities. **Accept:** capability tests deny cross-tenant reads, role changes, original mutation, and unapproved tools.
- [ ] **PLT-11 Observability baseline.** Add structured logs, metrics, traces, correlation IDs, redaction, and operational health indicators. **Accept:** processing, integrity, auth, queue and mission states observable without logging document content or credentials.
- [ ] **PLT-12 API and client security baseline.** Add request validation, CSRF/CORS policy as applicable, rate/size limits, pagination, safe errors, and security headers. **Accept:** automated API security checks and malformed request tests pass.

## Phase 2: Case Control And Evidence Fabric (CASE / EVD)

- [ ] **CASE-01 Tenant-scoped case model.** Implement case identity, metadata, status, jurisdiction, timezone, assignment, and optimistic version. **Accept:** tenant-scoped key uniqueness, audited create/update/close, and cross-tenant constraints pass.
- [ ] **CASE-02 Case list and War Room shell.** Implement case search/list and decision-oriented War Room structure. **Accept:** empty, loading, error, permission, processing, and integrity-alert states work responsively.
- [ ] **CASE-03 Parties and entity registry.** Add people/organization records, aliases, roles, and reviewable entity resolution. **Accept:** merge/split is versioned and source mentions remain traceable.
- [ ] **CASE-04 Objectives and notes.** Add objectives and author-attributed note revisions with optional provenance. **Accept:** edits create revisions/audit and access follows case policy.
- [ ] **CASE-05 Tasks and deadlines.** Add assignment, status, due date/timezone, source, and reminder-ready query. **Accept:** AI suggestions require operator confirmation; source/calculation and timezone remain visible.
- [ ] **EVD-01 Upload session API.** Create scoped/resumable upload sessions with limits, expiry, and idempotency key. **Accept:** unauthorized, oversized, expired, duplicate, and interrupted sessions have deterministic outcomes.
- [ ] **EVD-02 Streaming raw-byte hash.** Compute SHA-256 and byte count over the exact received original stream. **Accept:** known test vectors, chunk boundaries, retry, and empty/large files verify exact digest.
- [ ] **EVD-03 Quarantine and malware pipeline.** Quarantine before parsing; scan and isolate active/malicious files. **Accept:** positive/unknown scan results block processing and are visible without discarding preserved bytes where safe.
- [ ] **EVD-04 Immutable storage adapter.** Store original under version/retention controls; read back and compare digest before `PRESERVED`. **Accept:** overwrite/delete attempts fail under app identity; partial-write/reconcile and retention tests pass.
- [ ] **EVD-05 Evidence identity and custody.** Allocate Evidence ID and append upload/view/download/verify custody events. **Accept:** stable IDs, actor/time source, authorization, hash, and event audit are queryable; ordinary users cannot mutate history.
- [ ] **EVD-06 Folder intake orchestration.** Import folders with per-file status and resumable retries. **Accept:** one failed file does not corrupt others; retry is idempotent and summary reports every outcome.
- [ ] **EVD-07 Supported file classification.** Safely detect PDF, DOCX, supported image, and supported email/container formats. **Accept:** claimed/detected media types, unsupported/encrypted/corrupt states, and parser version are recorded.
- [ ] **EVD-08 Sandboxed parsing and metadata.** Extract bounded metadata/text in isolated workers without network or active-content execution. **Accept:** parser time/memory/archive limits and malicious fixture tests pass.
- [ ] **EVD-09 Derivative artifact registry.** Store extracted text/OCR/thumbnail as hashed, versioned children of evidence. **Accept:** reprocessing creates new artifact; original and old extraction remain addressable.
- [ ] **EVD-10 Duplicate and version relationships.** Detect exact-byte duplicates and model new submissions/replacements as explicit relations. **Accept:** same-name/different-bytes and same-bytes/different-context are not conflated.
- [ ] **EVD-11 Evidence register and viewer.** Show original, derivatives, metadata, status, source/hash, and custody. **Accept:** original is read-only; view/download are permissioned and audited; integrity warning blocks restricted actions.
- [ ] **EVD-12 Integrity verification and checkpoint.** Re-read stored bytes, validate event chain, produce checkpoint/report, and trigger hold on mismatch. **Accept:** bit-flip, missing version, and tampered event tests detect failures; report states proof limits.

## Phase 3: Search, Timeline, And Intelligence (INT)

- [ ] **INT-01 Full-text projection.** Index authorized derived text with source/version/location links. **Accept:** index is rebuildable, deletion/retention propagates, and no cross-tenant result appears.
- [ ] **INT-02 Search UX and filters.** Implement query, facets, and sorting by person/date/document/type/source. **Accept:** results identify exact evidence version and passage; partial index is indicated.
- [ ] **INT-03 Embedding/search adapter.** Add provider-neutral embeddings and semantic retrieval behind authorization filters. **Accept:** lexical search survives vector outage; vector data has source versions and can be rebuilt/deleted.
- [ ] **INT-04 Retrieval provenance contract.** Return stable evidence/artifact IDs and exact locators with every retrieval candidate. **Accept:** stale/deleted/unauthorized source is excluded and citation validation rejects unresolved IDs.
- [ ] **INT-05 AI Gateway contract.** Define typed provider interfaces, allow-list, timeout, data handling, model/config version, and safe failure. **Accept:** fake provider contract tests cover malformed output, timeout, retry, and provider swap.
- [ ] **INT-06 Summary mission.** Generate structured document/case summaries with citations and abstention. **Accept:** citations resolve to source passages and unsupported text is flagged by evaluation fixtures.
- [ ] **INT-07 Fact/claim extraction.** Extract claims, dates, subjects, polarity, and source locator into versioned schema. **Accept:** output remains candidate-only; schema and citation checks pass on regression set.
- [ ] **INT-08 Entity and people extraction.** Create source-linked mentions and candidate party resolution. **Accept:** no automatic merge into canonical party without review; aliases and confidence retain source.
- [ ] **INT-09 Timeline extraction.** Extract events with date precision, timezone uncertainty, and source links. **Accept:** exact/range/relative/unknown dates are represented without fabricated precision.
- [ ] **INT-10 Timeline review and correction.** Enable operator correction, reject, and source navigation. **Accept:** correction creates revision and audit event; original extraction remains inspectable.
- [ ] **INT-11 Contradiction candidates.** Compare claims and return both sides, source passages, and conflict type. **Accept:** evaluated against labeled cases; candidate never silently resolves which source is true.
- [ ] **INT-12 Evidence gaps and investigation questions.** Generate structured missing-support/questions with supporting rationale/citations. **Accept:** candidate status and source basis visible; operator confirmation required before task creation.
- [ ] **INT-13 Confidence and evaluation instrumentation.** Store confidence kind, calibration version, model/prompt, and evaluation result. **Accept:** UI labels confidence as non-truth; regression report gates model/prompt changes.

## Phase 4: Validation, Controlled Swarm, And Legal Lens (VAL / SWM / LAW)

- [ ] **VAL-01 Provenance graph service.** Resolve typed, versioned evidence-to-claim/finding/strategy edges. **Accept:** broken, cross-tenant, stale, cyclic-disallowed, and missing provenance cases are rejected or flagged.
- [ ] **VAL-02 Review transition service.** Enforce AI-generated/needs-review/verified/approved/rejected/retracted/superseded states. **Accept:** role, reviewer separation, reason, exact-version snapshot, and concurrency tests pass.
- [ ] **VAL-03 Operator review queue.** Present candidates with sources, confidence metadata, and review actions. **Accept:** approve/edit/reject/hold actions are audited and keyboard/screen-reader accessible.
- [ ] **VAL-04 Correction and supersession semantics.** Preserve old values and re-review dependents on material change. **Accept:** downstream strategy/export identifies stale source and cannot silently retain approval.
- [ ] **SWM-01 Mission policy and scope snapshot.** Authorize bounded job type, case/evidence scope, provider, and quota. **Accept:** worker cannot expand scope; policy change/revocation is rechecked before output access.
- [ ] **SWM-02 Blue Team mission.** Answer support/missing/contradiction questions from explicit evidence scope. **Accept:** structured cited result, abstention, and non-autonomous behavior pass evaluation.
- [ ] **SWM-03 Red Team mission.** Assess opposing arguments, unsupported assumptions, and undermining facts. **Accept:** distinguishes sourced facts from hypotheses; citations resolve; no external action is possible.
- [ ] **SWM-04 Red DART mission controller.** Recommend/schedule allow-listed analyses from user request or approved gap. **Accept:** human confirms high-impact scope; policy blocks tool escalation and autonomous publication.
- [ ] **SWM-05 Job lifecycle, cancel, retry, and recovery UX.** Expose queue/running/partial/failure/cancel state and safe retry. **Accept:** duplicate delivery yields one logical result; cancel/outage recovery is tested.
- [ ] **SWM-06 Prompt-injection defense suite.** Test instructions embedded in PDFs/emails attempting tool use, data leakage, or policy bypass. **Accept:** model output cannot alter authorization, originals, audit, or scope; failures quarantine result.
- [ ] **LAW-01 Jurisdiction plugin interface.** Version and validate plugin config independently from general AI. **Accept:** plugin enable/disable/version rollback is audited and case analysis records exact version.
- [ ] **LAW-02 Quebec/Canada labour source corpus.** Import approved source metadata/text under license and provenance requirements. **Accept:** source/version/effective date/license are tracked; stale or unverified source is labeled.
- [ ] **LAW-03 Jurisdiction and issue classification.** Suggest legal issue classifications based on case and evidence. **Accept:** suggestions are reviewed, cite evidence and applicable jurisdiction data, and do not present as legal advice.
- [ ] **LAW-04 Citation resolver.** Resolve generated authority references to configured corpus item and locator. **Accept:** nonexistent, wrong-version, or wrong-jurisdiction citation is rejected from approved output.
- [ ] **LAW-05 Legal analysis review boundary.** Separate legal-source text, AI analysis, operator verification, and counsel approval. **Accept:** export labels each class and follows configured reviewer policy.

## Phase 5: Strategy And Audit-Ready Output (STR / EXP)

- [ ] **STR-01 Strategy records and versions.** Create operator-owned theories/options/assumptions with provenance. **Accept:** every material assertion is linked or labeled assumption; revisions are immutable/audited.
- [ ] **STR-02 Strategy drafting mission.** Draft analysis from approved findings and selected authorities. **Accept:** output shows unresolved assumptions/conflicts and cannot cite unapproved sources as facts.
- [ ] **STR-03 Next-step recommendations.** Propose investigation tasks tied to gaps and objectives. **Accept:** operator approves before task creation/assignment; recommendation provenance is shown.
- [ ] **EXP-01 Case memo export.** Generate versioned memo from approved strategy/findings. **Accept:** source trace and review labels are included; missing citation policy blocks or labels draft.
- [ ] **EXP-02 Evidence index export.** Produce evidence list with ID, filename, type, hash, date, and custody/verification references. **Accept:** every row resolves to exact original version; sensitive metadata follows policy.
- [ ] **EXP-03 Chronology export.** Export reviewed timeline with event sources, date precision, and correction state. **Accept:** no hidden AI-only event is represented as verified.
- [ ] **EXP-04 Intelligence report export.** Export findings, claims, contradictions, gaps, and mission provenance. **Accept:** confidence and machine/human states are explicit; unsupported content is excluded or marked.
- [ ] **EXP-05 Audit package manifest.** Assemble exact input/output versions, hashes, policy, actor, time source, model/config, custody and review transitions. **Accept:** manifest can independently verify included hashes and provenance graph closure.
- [ ] **EXP-06 Secure export and access.** Authorize generation/download, encrypt/package, expiry, and record custody/audit. **Accept:** revoked user, expired link, cross-tenant access, tampering, and partial-processing tests pass.

## Phase 6: Commercial Hardening And Release Gate (HARD)

- [ ] **HARD-01 Tenant isolation suite.** Exercise all APIs, search/indexes, workers, storage references, exports, and admin paths across tenants. **Accept:** automated negative suite passes in CI and security review signs off.
- [ ] **HARD-02 Hostile file/parser suite.** Exercise malware, macro, malformed structures, archive bombs, image/PDF resource exhaustion, and parser crash. **Accept:** isolation, limits, quarantine, and per-file failure recovery are demonstrated.
- [ ] **HARD-03 AI adversarial and citation suite.** Run prompt injection, poisoned evidence, fabricated citations, unsupported conclusions, and model regression fixtures. **Accept:** thresholds and fail-closed output behavior meet approved evaluation gate.
- [ ] **HARD-04 50–500-document performance test.** Benchmark intake, extraction, indexing, search, timeline, and missions on the representative corpus. **Accept:** target metrics approved and met; partial/failure states are measured separately.
- [ ] **HARD-05 Reliability and idempotency test.** Kill API/worker/queue/storage at transaction boundaries and replay jobs. **Accept:** no silent evidence loss, duplicate authoritative transitions, or untracked orphan object.
- [ ] **HARD-06 Backup, restore, and disaster recovery.** Restore metadata, originals, keys, audit/checkpoints, and rebuildable indexes in an isolated environment. **Accept:** approved RPO/RTO met and hash/custody verification passes.
- [ ] **HARD-07 Retention and legal-hold drill.** Apply, release, and execute retention/deletion across all data copies. **Accept:** hold prevents scoped destruction; destruction receipts and residual exceptions are reported.
- [ ] **HARD-08 Key rotation and incident response.** Rotate/revoke encryption/signing/provider credentials; exercise integrity incident containment. **Accept:** old signatures remain verifiable under documented key history; compromised-key impact is bounded.
- [ ] **HARD-09 Accessibility and operator usability review.** Test keyboard, screen reader, responsive review/intake, and error recovery. **Accept:** high-impact workflows meet agreed accessibility criteria with no blocking issue.
- [ ] **HARD-10 Security assessment and production gate.** Independent review of threat model, dependency/supply chain, authorization, storage, AI, legal workflow, and operations. **Accept:** critical/high findings closed or explicitly accepted by accountable owner; deployment-specific controls evidenced.
- [ ] **HARD-11 Self-hosted/private-AI profile.** Package configuration and private-provider interface for controlled single-tenant deployment. **Accept:** documented network/data boundaries and install/upgrade/backup process pass deployment test.
- [ ] **HARD-12 Air-gap feasibility gate.** Inventory model/runtime/licensing/update/telemetry/outbound dependencies. **Accept:** do not advertise air-gapped operation unless offline install, updates, revocation, and audit are exercised end-to-end.

## Cross-Cutting Definition Of Done

Every ticket includes: tenant/case authorization; typed and versioned contracts; required audit/provenance; safe failure and retry semantics; unit plus integration/negative tests appropriate to risk; observability without sensitive-content leakage; migration/retention impact; accessible UI behavior when user-facing; and documentation of residual assumptions. Production security claims additionally require the external/storage/provider control and verification evidence named in the architecture.
