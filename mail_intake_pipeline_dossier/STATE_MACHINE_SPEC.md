# DOSSIER-PIPELINE State Machine and Replay Spec

## Purpose
This document defines the runtime state machine, replay capture contract, and the concurrency assumptions for the evidence governance pipeline.

## Runtime States
The pipeline uses the following ordered states:

1. `RECEIVED`
2. `PARSED`
3. `DEDUP_CHECKED`
4. `CLASSIFIED`
5. `PROVENANCE_ASSIGNED`
6. `ADAPTER_BUILT`
7. `POLICY_EVALUATED`
8. `CONTROL_RECORDED`
9. `SEEN_COMMITTED`
10. `EXPORTED`

Terminal / alternate states:

- `REJECTED_POLICY`
- `DUPLICATE`
- `FAILED_RUNTIME`
- `QUARANTINED`

### State transition rules
- `RECEIVED` is always the first state for a new `process_email()` call.
- `CONTROL_RECORDED` must occur before `SEEN_COMMITTED`.
- `REJECTED_POLICY` must short-circuit control execution.
- `FAILED_RUNTIME` is only emitted from the exception path around the inner pipeline.
- `DUPLICATE` is terminal for duplicate intake cases.

## Replay Contract
The pipeline records canonical replay events in `*_replay.jsonl`.

### Recorded event sequence
For a successful processed message, the expected event types are:

1. `pipeline.received`
2. `intake.parsed`
3. `intake.dedup_checked`
4. `classification.completed`
5. `provenance.completed`
6. `adapter.completed`
7. `policy.completed`
8. `control.recorded`
9. `seen.committed`

### Rejection path
For policy-rejected messages, the replay log must include:

- `pipeline.received`
- `intake.parsed`
- `intake.dedup_checked`
- `classification.completed`
- `provenance.completed`
- `adapter.completed`
- `policy.completed`
- `policy.rejected`

and must not include `control.recorded` or `seen.committed`.

### Duplicate path
For duplicate messages, the replay log must include:

- `pipeline.received`
- `intake.parsed`
- `intake.dedup_checked`
- `intake.duplicate`

and must not include classification or downstream control events.

## Determinism Requirements
Replay capture is intended to be deterministic with respect to:

- event order
- event type sequence
- stable identifiers
- payload contents that influence audit state

Replay logs are append-only JSONL files. Sequence numbers must be monotonically increasing.

## Concurrency Assumption
The current pipeline assumes a **single-writer-per-dossier** model for deterministic replay and control-chain ordering.

### Why this matters
- SQLite transactions serialize writes, but the system does not yet implement a full distributed concurrency contract.
- Replay determinism depends on a stable ordering boundary at ingestion.
- If multiple workers process the same dossier, they must be partitioned so only one writer can advance the audit chain at a time.

### Operational implication
Until a stricter concurrency coordinator is introduced, the safe model is:

- one active writer per dossier
- deterministic input ordering
- no concurrent mutation of the same audit chain from multiple workers

## Verification Rules
Replay verification should fail if:

- event sequence numbers are non-contiguous
- timestamps are out of order
- expected event types are missing
- control-recorded events appear on a rejected policy path
- a duplicate path advances into downstream processing

## Test Coverage Targets
The invariant suite should verify:

- duplicate suppression remains stable
- policy rejection blocks control writes
- control writes precede seen commits
- replay logs reflect the exact transition sequence
- replay logs remain valid after duplicate and rejection scenarios

## Practical Guidance
If a future change adds a new pipeline stage, update:

- `dossier_pipeline/pipeline.py`
- `tests/invariants/test_state_machine_invariants.py`
- this spec

If a future change modifies the concurrency model, the replay contract must be revisited at the same time.
