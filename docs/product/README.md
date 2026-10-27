# ANCHORUM Product Specification

These documents define the initial product and engineering contract before application implementation:

- [Screen map](SCREEN_MAP.md): War Room navigation, workflows, and user-visible states.
- [System architecture and security](SYSTEM_ARCHITECTURE.md): modular monolith, trust boundaries, integrity auditables, threats, deployment gates, and verification requirements.
- [Logical data model](DATA_MODEL.md): system-of-record entities, provenance graph, immutable lifecycle, review, audit, and retention.
- [MVP backlog](MVP_BACKLOG.md): 90 dependency-ordered tickets with acceptance outcomes and cross-cutting definition of done.

## Product Contract

Workflow: Case → Evidence → Intelligence → Validation → Strategy → Audit-ready Output

Evidence is authoritative; derived intelligence is replaceable. Nothing material is treated as a finding without provenance. AI jobs are bounded and reviewable. Evidence is untrusted input and cannot mutate originals or expand its own authority. Human verification/approval is distinct from model output. The MVP's first Legal Lens vertical is Quebec/Canada labour matters; jurisdiction logic remains modular.

## Readiness Notice

This is a specification, not evidence that controls have been implemented or independently verified. The current repository has no web/API application. Existing SQLite/HMAC evidence primitives do not by themselves provide immutable original-file storage, trusted timestamps, or independent verification. Production-readiness claims require the implementation and test evidence called out in the architecture and backlog.
