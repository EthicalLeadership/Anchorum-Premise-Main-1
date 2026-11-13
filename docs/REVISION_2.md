# Revision 2 — CR-0 through CR-12

**Status:** FINAL — Signed 2026-11-12.

**What this document is:** The requirement definitions that
`docs/TRACEABILITY_MATRIX.md` refers to. `THREAT_MODEL.md` §1 cites "CR-0
through CR-12 as defined in Revision 2"; this is that document.

The requirement text below is derived directly from the code and tests that
already ship in this repository. Every item cites a real test file and a real
commit hash. Nothing is asserted as covered that does not have a passing test
on origin.

**What this document does NOT cover:** every other CR item. They are listed at
the bottom as BLOCKED. This is honest backlog, not an oversight.

---

## CR-1 — Record and storage

### CR-1.1 — Canonical JSON serialization
**Requirement:** The ledger serializes message content as canonical JSON. Two semantically equivalent inputs — differing in dictionary key order, numeric representation, or Unicode normalization — produce byte-identical output. This is the basis for content hashing and signature verification.
**Tests:** `tests/test_ledger_canonical.py`
**Evidence:** `git show 46bb8ad:<file>`
**Status:** COVERED.

### CR-1.2 — Merkle tree over message hashes
**Requirement:** The ledger constructs a Merkle tree over message hashes. A tree over a single message returns that message's hash as the root. Multi-message trees combine hashes deterministically, producing a stable root for a given ordered set of messages.
**Tests:** `tests/test_ledger_merkle.py`
**Evidence:** `git show 46bb8ad:<file>`
**Status:** COVERED.

### CR-1.3 — Snapshot canonical byte representation
**Requirement:** LedgerSnapshot exposes a canonical byte representation (`canonical_bytes()`) suitable for signing and timestamping. The representation is deterministic and derived from the snapshot's content, not its runtime state.
**Tests:** `tests/test_ledger_snapshot.py`
**Evidence:** `git show e40f031:<file>`
**Status:** COVERED.

### CR-1.4 — Deterministic rule ordering within snapshot
**Requirement:** Rule identifiers within a snapshot are sorted deterministically. Unsorted input to the snapshot constructor does not produce a varying canonical byte representation.
**Tests:** `tests/test_ledger_snapshot.py`
**Evidence:** `git show e40f031:<file>`
**Status:** COVERED.

### CR-1.5 — As-of timestamp format
**Requirement:** Snapshot as-of timestamps are formatted as timezone-aware UTC with a trailing 'Z' suffix. Naive datetimes are rejected at construction, not silently coerced.
**Tests:** `tests/test_ledger_snapshot.py`
**Evidence:** `git show e40f031:<file>`
**Status:** COVERED.

### CR-1.6 — Single-message Merkle root
**Requirement:** A snapshot over a single message exposes a Merkle root equal to that message's hash. Multi-message snapshots expose a root computed by the Merkle tree defined in CR-1.2.
**Tests:** `tests/test_ledger_snapshot.py`
**Evidence:** `git show e40f031:<file>`
**Status:** COVERED.

## CR-10 — Security and integrity

### CR-10.3 — Ed25519 signing of snapshots
**Requirement:** Snapshots are signed with Ed25519 keys. Signatures are deterministic for a given (key, message) pair and verifiable by any holder of the public key.
**Tests:** `tests/test_ledger_signing.py`
**Evidence:** `git show 46bb8ad:<file>`
**Status:** COVERED.

### CR-10.6 — Authentication baseline (unconditional)
**Requirement:** Every request is authenticated, and no deployment mode disables this. Loopback is not a credential.
Host: a request whose `Host` header is not in the allowed set is rejected with 400.
Origin: a state-changing request (POST, PUT, PATCH, DELETE) whose `Origin` is outside the allowed set is rejected with 403. A state-changing request carrying no `Origin` must present `x-anchorum-key` equal to the deployment key, else 401.
Routes: any request under `/board/`, `/ledger/` or `/cases/` must present that key, else 401.
**Tests:** `tests/test_auth.py`
**Evidence:** `git show 73df171:<file>`
**Status:** PARTIAL. All three checks exist and pass. But `AuthMiddleware` skips the Host and Origin checks whenever `PYTEST_CURRENT_TEST` is present in the environment, so a deployment that can set the server's environment disables them without a code change — which is the opposite of "unconditional". COVERED when that seam is removed and a test asserts enforcement *with* the variable set.

## CR-11 — Verification and rollout

### CR-11.1 — OpenTimestamps stamping
**Requirement:** A snapshot's canonical bytes are written to disk as `snapshot.alp` and stamped via the OpenTimestamps CLI. The `.ots` proof file is the artifact an independent party can verify. Missing `ots` binary raises an actionable error; a timeout raises a distinct error; a non-zero exit raises an error including stderr.
**Tests:** `tests/test_ledger_anchor.py`
**Evidence:** `git show 2609339:<file>`
**Status:** COVERED.

### CR-11.2 — OpenTimestamps verification classification
**Requirement:** An `.ots` proof is classified as: **confirmed** (with Bitcoin block height and date extracted from CLI output), **pending** (not yet mined — not a failure), or **failed**. Verification requires the original `.alp` file to be present next to the proof.
**Tests:** `tests/test_ledger_anchor.py`
**Evidence:** `git show 2609339:<file>`
**Status:** COVERED.

### CR-11.3 — Anchor HTTP route
**Requirement:** `POST /ledger/snapshots/{case_id}/anchor` builds a snapshot via `app.state.snapshot_builder`, stamps it, and returns snapshot and proof paths. `GET /ledger/snapshots/{case_id}/anchor/verify` returns the proof classification. Missing builder returns 503; missing `ots` returns 503; stamping failure returns 502.
**Tests:** `tests/test_ledger_anchor_router.py`
**Evidence:** `git show 2609339:<file>`
**Status:** COVERED.

## CR-6 — Replay engine and performance

### CR-6.1 — Replay determinism
**Requirement:** Replay produces deterministic output from a message ledger. Given the same ledger and inputs, two replay executions produce identical results.
**Tests:** `tests/test_war_room_replay.py`
**Evidence:** `git show 7737b30:<file>`
**Status:** COVERED.

### CR-6.2 — War room data models
**Requirement:** War room data structures (board, links, entities) are modelled with explicit invariants enforced at construction.
**Tests:** `tests/test_war_room_models.py`
**Evidence:** `git show 7737b30:<file>`
**Status:** COVERED.

## CR-3 — Identity resolution

### CR-3.1 — Entity resolution
**Requirement:** Entities are resolved from the message ledger. Identity attribution is case-scoped: foreign identifiers answer as nonexistent.
**Tests:** `tests/test_war_room_entities.py`
**Evidence:** `git show 7737b30:<file>`
**Status:** COVERED.

### CR-3.2 — Link register (append-only)
**Requirement:** Links between entities and messages are recorded in an append-only register. Existing links cannot be altered, only superseded.
**Tests:** `tests/test_war_room_links.py`
**Evidence:** `git show 7737b30:<file>`
**Status:** COVERED.

## Not yet defined - BLOCKED (87 of 102 items)

The following CR items have no requirement definition. They will be marked `BLOCKED — requirement not yet defined` in the matrix.

- **CR-0** (4 items): CR-0.1, CR-0.2, CR-0.3, CR-0.4
- **CR-1** (4 items): CR-1.7, CR-1.8, CR-1.9, CR-1.10
- **CR-10** (8 items): CR-10.1, CR-10.2, CR-10.4, CR-10.5, CR-10.7, CR-10.8, CR-10.9, CR-10.10
- **CR-11** (4 items): CR-11.4, CR-11.5, CR-11.6, CR-11.7
- **CR-12** (6 items): CR-12.1, CR-12.2, CR-12.3, CR-12.4, CR-12.5, CR-12.6
- **CR-2** (8 items): CR-2.1, CR-2.2, CR-2.3, CR-2.4, CR-2.5, CR-2.6, CR-2.7, CR-2.8
- **CR-3** (4 items): CR-3.3, CR-3.4, CR-3.5, CR-3.6
- **CR-4** (10 items): CR-4.1, CR-4.2, CR-4.3, CR-4.4, CR-4.5, CR-4.6, CR-4.7, CR-4.8, CR-4.9, CR-4.10
- **CR-5** (10 items): CR-5.1, CR-5.2, CR-5.3, CR-5.4, CR-5.5, CR-5.6, CR-5.7, CR-5.8, CR-5.9, CR-5.10
- **CR-6** (7 items): CR-6.3, CR-6.4, CR-6.5, CR-6.6, CR-6.7, CR-6.8, CR-6.9
- **CR-7** (8 items): CR-7.1, CR-7.2, CR-7.3, CR-7.4, CR-7.5, CR-7.6, CR-7.7, CR-7.8
- **CR-8** (6 items): CR-8.1, CR-8.2, CR-8.3, CR-8.4, CR-8.5, CR-8.6
- **CR-9** (8 items): CR-9.1, CR-9.2, CR-9.3, CR-9.4, CR-9.5, CR-9.6, CR-9.7, CR-9.8
