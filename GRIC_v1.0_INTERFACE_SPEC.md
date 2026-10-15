# GRIC v1.0 Governance ↔ Runtime Interface Contract

## 0. Purpose

This document defines the only permitted coupling boundary between:

- **GOV** Dossier Intake Source governance/specification layer
- **RTM** `dossier_pipeline` runtime execution layer

The contract is intentionally strict:

- GOV defines what must be true.
- RTM executes and reports what happened.
- Neither side may redefine the other.

---

## 1. System Boundary

```text
[GOVERNANCE LAYER]
Dossier Intake Source
- case definitions
- templates
- evidence structure rules
- output constraints

        ↓ GRIC v1.0 ONLY

[RUNTIME LAYER]
dossier_pipeline
- ingestion engine
- state machine
- SQLite registries
- deduplication
- outbound tracking
- verification + replay
```

---

## 2. Design Principles

### 2.1 Directionality
**Invariant:** GOV → RTM only.

- GOV may submit constraints and artifact definitions.
- RTM may not write back into GOV state or semantics.

### 2.2 Determinism
**Invariant:** Same `(GOV spec + RTM version + input)` must produce the same result.

- RTM must ignore unspecified external state.
- RTM behavior must be replayable from the same declared inputs.

### 2.3 Non-Reinterpretation
**Invariant:** RTM must not infer governance rules.

RTM must not:
- guess missing constraints
- reinterpret templates
- alter case semantics dynamically

### 2.4 Execution Isolation
**Invariant:** GOV must not inspect RTM internal state for control flow.

GOV may receive:
- summary outputs
- reports
- exported artifacts

GOV may not receive:
- writable access to runtime SQLite state
- mutable state transitions
- control-chain internals as governance inputs

---

## 3. Interface Objects

## 3.1 `CaseSpec` GOV → RTM

`CaseSpec` is the only accepted governance input object.

### Schema

```json
{
  "schema_version": "1.0",
  "case_id": "string",
  "case_namespace": "string",
  "governance_version": "string",
  "evidence_manifest": [
    {
      "artifact_id": "string",
      "type": "pdf | docx | eml | image | video | json | txt",
      "path": "string",
      "hash": "string"
    }
  ],
  "processing_rules": {
    "deduplication_policy": "strict | relaxed",
    "quarantine_policy": "fail_closed | isolate",
    "validation_level": "standard | strict | forensic"
  },
  "output_contract": {
    "allowed_outputs": ["audit_report", "registry_summary", "document"],
    "template_id": "string",
    "language": "string"
  },
  "constraints": {
    "max_processing_time_ms": "integer",
    "max_memory_mb": "integer"
  }
}
```

### Purpose
Defines:
- the case identity
- the evidence corpus
- the output boundaries
- the allowed processing posture

### GOV guarantees
- hashes are stable
- paths are authoritative
- rules are declarative only

### RTM obligations
- consume the declared inputs
- not mutate the spec
- not infer unlisted policies

---

## 3.2 `PipelineResult` RTM → GOV

`PipelineResult` is the primary execution output object.

### Schema

```json
{
  "schema_version": "1.0",
  "case_id": "string",
  "runtime_version": "string",
  "execution_context_hash": "string",
  "status": "COMPLETED | FAILED | QUARANTINED | DUPLICATE",
  "outputs": {
    "audit_report": "path | null",
    "registry_summary": "path | null",
    "document": "path | null"
  },
  "metrics": {
    "records_processed": "integer",
    "duplicates_detected": "integer",
    "quarantined_items": "integer",
    "failed_items": "integer"
  },
  "trace": {
    "log_file": "path",
    "jsonl_events": "path"
  }
}
```

### Purpose
Communicates:
- what the runtime executed
- what artifacts were produced
- what the final execution status was

### Important constraint
This is a **derived artifact**, not a control input.

GOV may use it for review and reporting, but may not use it to rewrite governance semantics.

---

## 3.3 `ErrorEvent` RTM internal / optional export

### Schema

```json
{
  "schema_version": "1.0",
  "event_id": "string",
  "case_id": "string",
  "stage": "INGEST | VALIDATE | DEDUP | PROCESS | OUTBOUND",
  "error_type": "VALIDATION_ERROR | POLICY_REJECTION | RUNTIME_FAILURE | IO_ERROR",
  "severity": "LOW | MEDIUM | HIGH | CRITICAL",
  "message": "string",
  "execution_context_hash": "string",
  "artifact_id": "string | null",
  "timestamp": "RFC3339"
}
```

### Purpose
Represents a machine-readable failure or rejection condition.

### Constraint
Error events are **diagnostic outputs**, not governance inputs.

---

## 3.4 `OutboundEvent` RTM → external system

### Schema

```json
{
  "schema_version": "1.0",
  "event_id": "string",
  "case_id": "string",
  "payload_type": "report | registry | document",
  "payload_uri": "string",
  "status": "PENDING | SENT | FAILED | RETRYING",
  "retry_count": "integer",
  "idempotency_key": "string",
  "created_at": "RFC3339"
}
```

### Purpose
Describes delivery or publication actions initiated by runtime.

### Constraint
Outbound events must be idempotent and append-only.

---

## 4. Allowed Operations Matrix

| Operation | GOV → RTM | RTM → GOV | Notes |
|---|---:|---:|---|
| Submit CaseSpec | YES | NO | Primary entry point |
| Return PipelineResult | NO | YES | Primary output |
| Return ErrorEvent summary | NO | YES | Aggregated only |
| Inspect raw runtime logs | NO | LIMITED | JSONL trace only, not runtime state |
| Modify CaseSpec | NO | NO | Forbidden |
| Modify runtime state | NO | NO | Forbidden |
| Override state machine | NO | NO | Forbidden |

---

## 5. RTM State Transition Model

RTM owns the only runtime transition model.

```text
RECEIVED
  ↓
INGESTED
  ↓
VALIDATED
  ↓
DEDUPED
  ↓
PROCESSED
  ↓
(QUARANTINED | FAILED | COMPLETED)
  ↓
OUTBOUND_QUEUED
  ↓
DELIVERED
```

### Terminal states
- `COMPLETED`
- `FAILED`
- `QUARANTINED`

### Constraint
GOV may define constraints that influence whether RTM enters a terminal state, but GOV may not define new runtime transitions.

---

## 6. Prohibited Couplings

### Hard forbidden for RTM
- reading GOV templates dynamically during execution decisions
- modifying CaseSpec
- inferring missing governance rules
- depending on runtime UI or CLI state for logic
- redefining state transitions based on observed outputs

### Hard forbidden for GOV
- reading runtime SQLite state
- depending on deduplication logic
- defining execution transitions
- inspecting ErrorEvent streams for control flow
- mutating execution state via exported reports

---

## 7. Versioning Rules

### Required fields
- `governance_version`
- `runtime_version`
- `schema_version`

### Compatibility rule
A `CaseSpec` is valid only if:

```text
governance_version ∈ supported_runtime_governance_matrix
```

### Recommendation
Version compatibility should be validated before runtime execution begins.

---

## 8. Failure Handling Contract

### RTM behavior
| Failure Type | Behavior |
|---|---|
| validation error | QUARANTINE |
| duplicate detection | DUPLICATE |
| processing failure | FAILED |
| policy rejection | QUARANTINE (fail-closed) |

### GOV expectation
GOV must assume:
- failures are explicit
- failures are structured
- no silent drops exist

---

## 9. Auditability Requirements

RTM must emit:
- deterministic `execution_context_hash`
- append-only JSONL trace
- reproducible `PipelineResult`

GOV may use:
- `PipelineResult` for reporting
- summary error exports for review

GOV may not use:
- raw runtime internals for control logic

---

## 10. Integrity Boundary

### Integrity rule
All RTM outputs must be reproducible from:

- `CaseSpec`
- `runtime_version`
- input corpus
- declared runtime configuration

### Tamper-resistance expectations
- all artifacts hashed
- outbound events idempotent
- execution traces append-only

---

## 11. Extension Model

### Allowed future extensions
- new `processing_rules` fields in `CaseSpec`
- new `metrics` fields in `PipelineResult`
- new diagnostic fields in `ErrorEvent`

### Forbidden future extensions
- redefining runtime state transitions
- adding bidirectional GOV ↔ RTM coupling
- making runtime logic depend on governance file mutation timing

---

## 12. Anti-Drift Invariants

These rules prevent accidental collapse of the two-layer stack.

### A1 Governance does not execute
GOV defines constraints only.

### A2 Runtime does not govern
RTM executes and reports only.

### A3 Identity may cross the boundary
Case IDs, hashes, and artifact names may be shared.

### A4 Behavior may not cross the boundary
Execution semantics, deduplication, quarantine, and transition logic may not be shared.

### A5 Derived outputs are not control inputs
Reports are for review, not for redefining governance.

---

## 13. Executive Summary

- **GOV = declarative governance specification layer**
- **RTM = deterministic execution engine**
- **Interface = strict `CaseSpec` → `PipelineResult` flow**
- **Boundary rule = lossless identity, lossy behavior**
- **Core invariant = governance defines what must be true; runtime defines what was executed**

This contract is the only legal coupling surface between Dossier Intake Source and `dossier_pipeline`.
