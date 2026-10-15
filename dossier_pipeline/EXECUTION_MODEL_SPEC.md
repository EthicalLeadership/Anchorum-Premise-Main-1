# DOSSIER-PIPELINE Execution Model Spec

## Purpose
This document defines the system-level execution model for the pipeline as a verifiable state-transition system over an append-only event log. It is intentionally stricter than the runtime pipeline state machine: it captures the operating assumptions required for deterministic behavior under concurrency, retry, and failure.

## Model Overview
The pipeline should be treated as a message-scoped execution engine with the following conceptual stages:

1. `RECEIVED`
2. `CLAIMED`
3. `CLASSIFIED`
4. `POLICYED`
5. `COMMITTED`
6. `ANCHORED`

These stages are not merely code-path labels. They define the contract that the runtime must satisfy.

## Stage Definitions

### RECEIVED
The raw message bytes have entered the system boundary.

Required properties:
- raw payload is immutable after receipt
- a stable message fingerprint is available immediately
- receipt is recorded before any downstream mutation

### CLAIMED
The system has established ownership of the message for processing.

Required properties:
- exactly one active writer may claim a given dossier key at a time
- claim acquisition must be deterministic
- duplicate or conflicting claims must resolve without corrupting persisted state

### CLASSIFIED
The message has been deterministically categorized.

Required properties:
- classification must be based only on message content and stable metadata
- classification must not depend on arrival timing
- classification output must be replayable from the same input bytes

### POLICYED
Policy evaluation has been applied and a disposition has been selected.

Required properties:
- policy outcome must be explainable from prior state
- rejected messages must not advance to commit
- policy decisions must preserve the audit trail of why a message was blocked

### COMMITTED
The audit record has been appended durably to the control chain.

Required properties:
- control write is append-only
- commit must be ordered before any seen-registry finalization
- commit must have a stable hash-link to the previous record

### ANCHORED
The committed state has been made externally verifiable by a terminal consistency checkpoint.

Required properties:
- anchored state must reference a verifiable tail hash or equivalent root
- anchoring must not mutate prior chain records
- anchoring must be reproducible from persisted state

## Execution Contract
The system is considered valid only if all of the following are true:

- every message follows a single logical transition path
- no transition is inferred from wall-clock timing alone
- all committed records are append-only
- duplicate handling is deterministic
- rejected messages do not produce commit-side effects
- replay from raw input produces the same final record chain

## Concurrency Contract

### Required model
The safe operating model is **single-writer per dossier key**.

This means:
- one active writer may advance the control chain for a dossier at a time
- parallel readers are allowed
- retry workers must not concurrently mutate the same dossier chain
- outbound reconciliation must not interleave with unrelated claim ownership for the same dossier

### Why this is required
The current system uses SQLite-backed stores and append-only records. That gives local serialization, but not a full distributed concurrency guarantee. Without an explicit single-writer contract:
- duplicate suppression can drift under timing skew
- control-chain ordering can diverge across workers
- replay determinism can fail under load

### Operational guidance
Until a stronger partitioning system exists:
- isolate work by dossier key
- ensure only one process can claim a dossier at a time
- avoid simultaneous claim+commit activity for the same dossier across workers

## Failure Atomicity Boundaries

### Boundary 1 receipt to claim
Failure before claim means the message may be retried safely.

### Boundary 2 claim to classification
Failure after claim but before commit must not corrupt the seen registry.

### Boundary 3 classification to policy
Failure after classification but before policy evaluation must be replayable without changing output.

### Boundary 4 policy to commit
Rejected messages must terminate here. Allowed messages proceed to commit.

### Boundary 5 commit to anchor
Commit must be durable before any final seen-state finalization. Anchoring may be performed later and must be derived from committed state.

## Idempotency Rules
The following operations must be safe to retry:
- message claim acquisition
- replay log reconstruction
- outbound reconciliation
- export generation

The following operations must not create divergent side effects when retried:
- duplicate suppression
- control-chain append
- policy rejection recording

## Determinism Rules
Determinism means:
- same raw input → same classification
- same classification/provenance → same policy outcome
- same ordered transitions → same commit sequence
- same commit sequence → same tail hash

Determinism must hold without relying on:
- arrival time
- thread scheduling
- incidental dictionary ordering
- implicit retries that reorder durable writes

## Stress Conditions That Must Be Treated as First-Class
The execution model must remain valid under:
- duplicate retry storms
- crash after claim
- crash after policy but before commit
- crash after commit but before seen finalization
- delayed outbound reconciliation
- replay from persisted state only

## Relationship to the Runtime State Machine
The runtime pipeline state machine is an implementation detail of this execution model.

Runtime states:
- describe code progression
- are emitted by the pipeline
- are verified by tests

Execution states:
- describe the system contract
- define how the pipeline is allowed to behave
- are the basis for concurrency and replay guarantees

## Verification Expectations
A system conforming to this spec should be able to prove:
- single-writer behavior for a dossier
- stable replay from raw input
- append-only commit order
- no commit on policy rejection
- no state corruption on duplicate or partial-failure scenarios

## Next Architectural Extension
The next production-hardening layer should be:
1. a deterministic fault-injection harness that exercises claim/commit boundaries
2. a concurrency coordinator that enforces the single-writer-per-dossier contract
3. CI gating that rejects nondeterministic replay output
