# Scope of Work Declaration

## §1 — Current position

Phase 2A is signed as complete, established by sub-gate 2.4 closure report (working tree state). Next phase: Phase 2B.

UNCITED — No prior commit for Phase 2A deliverables in working tree; all changes present.

## §2 — Phases remaining

- **Phase 2B:** Port crypto/audit/idempotency primitives from reference into platform
  - Objective: Bring forward non-duplicate primitives only
  - Deliverables: Implementation of missing cryptographic signing, audit chain, idempotency tokens, job queues
  - Acceptance criteria: Each primitive extends existing `dossier_pipeline/control.py` signer pattern without duplication
  - Rough duration: 2-3 gates

- **Phase 2C:** Gateway migration and anchoring integration
  - Objective: Wire gateway components to dossier pipeline
  - Deliverables: Gateway routes, anchorumzero-trust.com DNS propagation, evidence upload workflows
  - Acceptance criteria: Upload endpoints functional with custody recording
  - Rough duration: 3-4 gates

- **Phase 2D:** Production readiness and security hardening
  - Objective: Security review, CI expansion, deployment artifacts
  - Deliverables: Hardened configuration, secrets management, backup/restore procedures
  - Acceptance criteria: Passes internal security audit, CI green in staging
  - Rough duration: 4-5 gates

## §3 — Invariants carried forward

1. (a) No modifications to legacy `app/` package beyond documentation; (b) `v1-scope-deferral.md`, `app/README_LEGACY.md`
2. (a) SQLite single-writer model; no advisory locks, `SERIALIZABLE` isolation not required; (b) platform codebase
3. (a) Tenant tables deferred to OIDC project integration; (b) Phase 1 scope deferral record
4. (a) Signer guards mandatory on all evidence ingestion; (b) `dossier_pipeline/evidence.py`, `interface/anchorum_api.py`
5. (a) Chain-linked custody only for events suffix of anchored chain; (b) Phase 2A closure report
6. (a) WCAG 2.1 AA minimums in frontend UI; keyboard navigation first; (b) `interface/src/` TypeScript codebase

## §4 — Explicit exclusions

- Deployment to Azure production (use DeployToAzure agent instead)
- Modifications to `app/` package code beyond annotation documentation
- Tenancy implementation (defer to OIDC project phase)
- Authentication schema changes (`get_current_user`, `require_scope` deferred)
- Database migrations beyond Active-schema drop-and-recreate pattern
- CI pipeline expansion (existing `ci.yml` sufficient for now)
- New UI primitives in React frontend without Phase 2C authorization
- Background job queue implementation (use existing scheduler pattern)
- Encryption at rest implementation (host-disk encryption assumed)
- CVE scanning infrastructure (SBOM check exists, CVE scan deferred)

## §5 — Escalation triggers

1. If `app/` directory contains committed code beyond `README_LEGACY.md`, STOP and ask for deployment policy update
2. If Phase 2B primitive duplicates existing `dossier_pipeline/control.py` signer functionality, STOP and clarify boundary
3. If database migration requires locking write access during production hours, STOP and request maintenance window
4. If UI component introduces new keyboard traps or screen reader incompatibility, STOP and review before commit

## §6 — Dependencies on approver

1. Authorization to proceed with Phase 2B crypto/audit/idempotency implementation
2. Confirmation of invariants listed in §3 are understood and accepted
3. Explicit approval for any work item falling under §4 exclusions if required

## §7 — Attestation

This is my declared scope of work. I will not do work outside this scope without explicit written authorization. If I discover work outside this scope is required, I will stop and escalate.
