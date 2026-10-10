# ANCHORUM Logical Data Model

**Status:** Product specification, version 1.0  
**Purpose:** Define the authoritative records, provenance graph, and lifecycle contracts for the MVP. This is a logical model, not migration-ready DDL.

## 1. Modeling Invariants

1. Every tenant-owned record has an immutable `tenant_id`; every case-scoped record has a `case_id`. Parent scope is checked on every read, mutation, job, search, and export.
2. IDs are opaque stable identifiers. Human-readable case keys and evidence IDs are unique within an explicitly stated scope and are never authorization tokens.
3. Source evidence bytes are immutable. Re-upload, correction, OCR, normalization, thumbnail, redaction, and export are new objects or versions linked to parents, never replacement of an original.
4. Evidence identity is separate from a file name, extracted text, database row ID, or storage path.
5. Every state-changing operation records actor/service identity, time and time source, action, object/version, authorization decision, correlation/idempotency key where applicable, and reason when required.
6. Material AI outputs and operator-approved assertions carry provenance edges to exact evidence versions and source locations, or are explicitly labeled assumptions with an accountable author. A finding with no valid provenance cannot be approved or exported as fact.
7. AI confidence is metadata about a model output, not truth or a legal conclusion.
8. Corrections/reviews are new immutable revisions with transitions; previous values remain traceable subject to authorized retention/deletion policy.
9. Deletion, retention, legal hold, and archival are policy-governed domain events spanning primary data, derivatives, indexes, jobs, exports, and backups.
10. Audit events and evidence custody are different record classes with different access and integrity contracts.

## 2. Common Record Fields

Tenant-owned domain records generally include:

- `id`: opaque immutable ID.
- `tenant_id`: owning organization/tenant.
- `created_at`, `created_time_source`: server time and stated source.
- `created_by`: user/service principal.
- `updated_at` only for mutable projections/configuration; authoritative domain history remains event/version based.
- `record_version` or optimistic concurrency token.
- `status`: finite state-machine value, not free text.
- `deleted_at`/`tombstone_id` only when policy permits logical deletion; not a claim of physical erasure.
- `audit_correlation_id`: link to operation audit/event stream.

Case-scoped records include `case_id` and verify it belongs to the same tenant. Do not denormalize tenant ownership without constraints and consistency tests.

## 3. Core Identity And Case Control

### Organization / Tenant

`Tenant(id, display_name, status, policy_set_id, data_region, retention_profile_id, created_at)` owns members, cases, and configuration. Tenant status controls new work and access; suspension/recovery are audited.

### User And Membership

`User(id, identity_subject, display_name, status)` represents an identity from the configured provider. Credentials remain with the identity provider; no raw passwords or API secrets are stored here.

`Membership(id, tenant_id, user_id, tenant_role, status, invited_by, joined_at, revoked_at)` connects a user to a tenant. Unique active membership is enforced. Revocation is immediate for future requests/jobs/downloads and auditable.

### Case

`Case(id, tenant_id, case_key, title, matter_type, jurisdiction_id, description, timezone, status, opened_at, closed_at, owner_membership_id, retention_profile_id, version)` is the primary workspace. `case_key` is unique within tenant. Case closure does not automatically delete evidence. Jurisdiction/matter changes are versioned, audited, and may require re-evaluation of legal analyses.

### Case Membership / Permission

`CaseAssignment(id, tenant_id, case_id, membership_id, case_role, restrictions, status, granted_by, revoked_at)` grants case access. Authorization combines tenant membership, case role, evidence restriction, assignment, and policy; it is deny-by-default.

### Party And Entity

`Party(id, tenant_id, case_id, party_type, canonical_name, aliases, role, status, version)` represents a person or organization relevant to a case. Extracted mentions are not automatically merged into a party. Entity resolution is a reviewable relationship with source references, confidence, author, and history; merge/split preserves prior IDs and links.

### Objective, Note, Task, Deadline

`Objective(id, tenant_id, case_id, title, description, owner_membership_id, status, priority, provenance_id, version)` is an operator goal; AI may propose but not silently create/close it.

`CaseNote(id, tenant_id, case_id, author_membership_id, body_revision_id, sensitivity, created_at)` is author-attributed and immutable by revision. Notes can have provenance edges to evidence or other records.

`Task(id, tenant_id, case_id, title, description, assignee_id, status, priority, due_at, timezone, source_id, created_by, version)` tracks work. Any AI-proposed task remains a candidate until operator-confirmed.

`Deadline(id, tenant_id, case_id, label, due_at, timezone, source_type, source_reference, jurisdiction_id, verified_by, status, version)` distinguishes user-entered from rule-derived dates and preserves calculation/source/version. Legal deadline calculations require explicit rule provenance and qualified review.

## 4. Evidence Fabric

### Evidence Object And Immutable Original

`EvidenceObject(id, tenant_id, case_id, evidence_id, source_kind, original_filename, media_type_claimed, media_type_detected, byte_count, digest_algorithm, digest, received_at, received_time_source, uploader_id, upload_session_id, duplicate_of_id, retention_profile_id, restriction, status, storage_ref, storage_version, version)` identifies the preserved original. `digest` is SHA-256 over exact original bytes as received, before parsing/normalization. `storage_ref` is opaque and must not be exposed as a public URL.

`EvidenceId` is a human-readable display identifier scoped and allocated to a case/tenant; it does not replace the opaque primary ID. Exact duplicate bytes may have a duplicate relationship but remain separate submissions if source/context differs.

Original lifecycle: `UPLOAD_PENDING → QUARANTINED → PRESERVATION_PENDING → PRESERVED → PROCESSING → AVAILABLE`, with `REJECTED`, `INTEGRITY_HOLD`, `PRESERVATION_FAILED`, `RESTRICTED`, and `RETENTION_PENDING` outcomes. State transitions are audited and idempotent. Never mark `PRESERVED` until storage readback/version and hash contract pass. Failure after storage write is reconciled, not silently rolled back by deleting the original.

### Derivative Artifact

`Artifact(id, tenant_id, case_id, evidence_object_id, parent_artifact_id, artifact_type, digest_algorithm, digest, byte_count, storage_ref, storage_version, tool_name, tool_version, config_hash, created_at, status, restriction)` represents extracted text, OCR, metadata, thumbnail, redaction, normalized email component, or export. Each artifact records parentage and tool/config. Reprocessing creates a new artifact; do not update the old artifact in place.

### Custody Event

`CustodyEvent(id, tenant_id, case_id, evidence_object_id, actor_id, action, occurred_at, time_source, authorization_decision_id, reason, request_id, previous_event_hash, event_hash, signature_ref)` records ingest, view, download, verification, transfer, export, restriction, legal hold, or approved lifecycle action. Custody events are append-only; any correction is a superseding event with explicit reason. `signature_ref` may be absent only under a documented local/test profile; production signing requirements are specified in the architecture.

### Integrity Check And Anchor

`IntegrityCheck(id, tenant_id, case_id, evidence_object_id, checked_at, checker_identity, algorithm, expected_digest, observed_digest, storage_version, outcome, report_ref)` records repeatable byte verification. Failure moves the object to `INTEGRITY_HOLD` and blocks affected use per policy.

`EvidenceCheckpoint(id, tenant_id, chain_id, range_start, range_end, merkle_root, tail_hash, created_at, time_source, signing_key_id, external_witness_ref)` records checkpoints. A checkpoint without protected signing and independent retention is only a local consistency signal, not independent proof.

## 5. Provenance And Intelligence

### Provenance Edge

`ProvenanceEdge(id, tenant_id, case_id, subject_type, subject_id, subject_version, relation, source_type, source_id, source_version, locator, created_at, created_by, method, confidence, rationale)` is a directed typed edge. Supported relations include `EXTRACTED_FROM`, `SUPPORTED_BY`, `CONTRADICTED_BY`, `DERIVED_FROM`, `CITED_AUTHORITY`, `CORRECTS`, `SUPERSEDES`, `REVIEWED_BY`, and `INCLUDED_IN`. A source reference includes the immutable EvidenceObject or Artifact version and a page/offset/timecode or an explicit locator-unavailable reason.

### Claim And Fact

`Claim(id, tenant_id, case_id, statement, claim_type, subject_party_id, predicate, object_value, time_scope, polarity, status, revision, origin, confidence, created_at, created_by)` captures a proposition, not verified truth. Extracted facts/claims begin as AI candidates. A verified claim links to exact provenance and reviewer transition. Preserve contradictory claims instead of collapsing them.

### Finding

`Finding(id, tenant_id, case_id, finding_type, title, statement, status, revision, origin, confidence_value, confidence_kind, model_ref, prompt_hash, config_hash, created_at, created_by, supersedes_id)` holds a summary, supported/unsupported assessment, gap, contradiction, question, or analysis result. Findings may reference multiple claims/evidence items through ProvenanceEdge. It cannot be `APPROVED` without resolvable provenance or explicit approved-assumption classification.

### Entity Mention And Resolution

`EntityMention(id, tenant_id, case_id, artifact_id, locator, surface_form, entity_type, extraction_job_id, confidence)` records a mention in a derivative. `EntityResolution(id, tenant_id, case_id, mention_id, party_id, status, reviewed_by, rationale, version)` maps mentions to parties through a reviewable decision.

### Timeline Event

`TimelineEvent(id, tenant_id, case_id, event_text, date_start, date_end, date_precision, timezone, status, revision, origin, created_by, supersedes_id)` links through provenance to source passages and involved party IDs. Human correction creates a new revision; preserve extracted value and reason.

### Review Transition

`ReviewTransition(id, tenant_id, case_id, subject_type, subject_id, subject_version, from_state, to_state, actor_id, reviewer_role, occurred_at, reason, policy_decision_id, provenance_snapshot_hash)` records explicit review. States include `AI_GENERATED`, `NEEDS_REVIEW`, `HUMAN_VERIFIED`, `APPROVED`, `REJECTED`, `RETRACTED`, and `SUPERSEDED`; not every transition is allowed from every state. Approval attaches to an exact version/snapshot. Author/reviewer separation is policy-configurable.

## 6. Missions, AI, Legal Lens, And Strategy

### Mission And Job

`Mission(id, tenant_id, case_id, mission_type, requested_by, question, scope_snapshot, policy_decision_id, status, created_at, completed_at, idempotency_key, parent_mission_id)` is a bounded operator-authorized analysis request. `scope_snapshot` names exact evidence/artifact versions and excludes unapproved scope expansion.

`JobAttempt(id, tenant_id, mission_id, attempt_no, worker_identity, provider_id, model_id, model_version, prompt_hash, config_hash, started_at, ended_at, status, error_class, token_usage, cost_estimate, output_hash, validation_report_id)` captures execution metadata. No API keys or raw sensitive prompts are duplicated in general logs; governed prompt/context hashes and retention are policy-defined.

`MissionResult(id, tenant_id, case_id, mission_id, result_type, schema_version, content_ref, output_hash, validation_status, citation_validation_status, created_at, review_status)` is a machine-generated candidate until reviewed. Output is schema-validated, provenance-linked, and isolated from source evidence.

### Legal Lens

`JurisdictionPlugin(id, plugin_key, version, jurisdiction_code, matter_types, config_hash, status, effective_from, effective_to, approved_by)` identifies an allow-listed, versioned legal module.

`AuthoritySource(id, tenant_id, plugin_id, authority_type, citation_key, title, jurisdiction, court_or_body, decision_or_effective_date, source_uri_or_identifier, license, source_hash, retrieved_at, corpus_version, validation_status)` records source and licensing/currency. Legal text is itself versioned evidence-like source material under applicable licensing.

`LegalIssue(id, tenant_id, case_id, plugin_id, issue_code, suggested_classification, status, source_finding_id, reviewer_id, version)` separates issue suggestion from legal conclusion.

`Citation(id, tenant_id, case_id, authority_source_id, locator, cited_text_hash, verified_at, verified_by, status)` must resolve to the exact authority version and locator. Generated citations are rejected when absent from the configured source corpus.

### Strategy

`StrategyItem(id, tenant_id, case_id, item_type, content_revision_id, status, author_id, reviewer_id, version, supersedes_id, created_at)` stores operator strategy, options, assumptions, and proposed action. Each material assertion links through provenance to approved Finding/Claim and then evidence, or is marked as an assumption with author, rationale, and review. Strategy output is never confused with evidence or legal authority.

## 7. Governance, Retention, And Exports

### Audit Event

`AuditEvent(id, tenant_id, case_id, actor_id, action, object_type, object_id, object_version, occurred_at, time_source, authorization_decision_id, request_id, reason, before_hash, after_hash, event_hash, signature_ref)` is the application action record. Required governed operations fail closed if audit persistence fails. Audit access is separately permissioned; avoid placing full document contents or secrets in event details.

`AuthorizationDecision(id, tenant_id, actor_id, action, resource_type, resource_id, policy_version, result, reason_code, evaluated_at, request_id)` supports decision audit and diagnostics. Denials are logged under privacy/retention policy.

### Retention And Legal Hold

`RetentionProfile(id, tenant_id, name, rules_version, duration, trigger, deletion_mode, approved_by)` defines policy. `LegalHold(id, tenant_id, case_id, scope, authority, placed_by, placed_at, released_by, released_at, status)` overrides ordinary deletion for scoped records. `DestructionEvent(id, tenant_id, scope, policy_version, requested_by, approved_by, executed_at, storage_receipt, verification_status)` records authorized destruction without retaining content that policy requires erased. Apply consistently to backups, indexes, caches, derivatives, exports, and provider-side retained data where contractually controllable.

### Export Package

`ExportPackage(id, tenant_id, case_id, export_type, requested_by, status, content_ref, manifest_ref, digest, signature_ref, policy_decision_id, created_at, expires_at, source_snapshot_hash)` references exact included object/claim/finding/authority versions. `ExportItem(id, export_id, object_type, object_id, object_version, source_hash, inclusion_reason, review_state)` lists contents. An export is blocked or marked incomplete according to policy if provenance, approval, integrity, or authorization is unresolved. Re-exports produce new packages; downloads are audited.

## 8. Key Relationships

- Tenant 1:N Membership, Case, TenantPolicy, RetentionProfile.
- Case 1:N CaseAssignment, Party, Objective, Note, Task, Deadline, EvidenceObject, Mission, Claim, Finding, TimelineEvent, StrategyItem, ExportPackage.
- EvidenceObject 1:N Artifact, CustodyEvent, IntegrityCheck; Artifact may have a parent Artifact and always resolves to an EvidenceObject root for source material.
- ProvenanceEdge links versioned subjects to versioned evidence/artifacts/claims/findings/authorities/strategy/exports; enforce same-tenant and case compatibility.
- Mission 1:N JobAttempt and MissionResult; MissionResult can yield candidate Finding/Claim/TimelineEvent only through validation/review lifecycle.
- Party 1:N EntityResolution and links to TimelineEvent/Claim through explicit relationship records.
- Finding/Claim/StrategyItem/TimelineEvent/ExportItem use exact versions and review snapshots, not mutable “latest” pointers, for citations.

## 9. Database And Integrity Constraints

- Use schema migrations; no runtime `create_all` as production migration strategy.
- Unique constraints: `(tenant_id, case_key)`, `(tenant_id, evidence_id)`, membership uniqueness, idempotency scope, and relevant version sequence.
- Foreign keys include tenant/case scope where feasible (composite constraints) to prevent cross-tenant relationships. Test all service paths even with DB row-level security.
- Use append-only events/versions for custody, review, audit, and approved outputs; deny UPDATE/DELETE to ordinary service roles at DB/storage level where feasible.
- Store content in object storage, not relational text/blob fields, except tightly bounded metadata. Sensitive text and embeddings have explicit encryption, retention, and access policies.
- Search/vector indexes are derived projections, carry source IDs/versions, and can be deleted/rebuilt without altering authoritative records.
- Immutable original means exact stored object version plus independently verifiable digest and enforced retention policy; a database flag alone is insufficient.

## 10. Migration And Implementation Notes

The current `Case`, `Document`, `User`, `AuditLog`, and `JurisdictionStamp` ORM models are insufficient for this domain and should not be expanded in place without a migration plan. The existing `EvidenceStore` packet/custody model can inform event semantics, but its JSON packet hash is not the raw-file digest and SQLite/HMAC does not meet the production storage/signature contract. Introduce explicit ports/adapters and migration/compatibility tests before connecting legacy records to new EvidenceObject identities. Legacy provenance gaps remain visible; never synthesize missing source history.
