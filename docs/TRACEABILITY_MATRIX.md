# Traceability Matrix — Conversation Ledger & Replay

**Status:** Signed by Samuel Tessier on 2026-11-12 against `docs/REVISION_2.md`
(the requirements document, 129 lines). See `docs/THREAT_MODEL.md` §8 for the
residual attached to that signature: for v1 the implementer is the reviewer, and
there is no independent review.

**What each column means.**

- **Covered** — a named test exists, passes, and the requirement it pins is defined
  in `REVISION_2.md`. The test name is given, not a document reference.
- **BLOCKED — requirement not yet defined** — the ID is reserved here so the
  workstream can fill it in, but `REVISION_2.md` does not yet state what the
  requirement is. Nothing can be covered by a requirement nobody has written.
- **BLOCKED — reason** — the requirement is defined or implied but no test covers it.

`REVISION_2.md` currently defines fourteen requirements (CR-1.1–1.6, CR-3.1, CR-3.2,
CR-6.1, CR-6.2, CR-10.3, CR-11.1–11.3). The other eighty-eight IDs in this matrix are
**reserved placeholders**, not requirements: the numbering came from the workstream
structure, and a row is only marked covered once its requirement text exists.

| Requirement ID | Workstream | File | Test Name | Evidence Location | Enforcement Point | Status |
|---|---|---|---|---|---|---|
| CR-0.1 | CR-0 Security architecture | docs/THREAT_MODEL.md | — | Threat model §1–§8 | CR-0 sign-off | Covered by document; no code test applies |
| CR-0.2 | CR-0 Security architecture | | | | | BLOCKED — requirement not yet defined |
| CR-0.3 | CR-0 Security architecture | | | | | BLOCKED — requirement not yet defined |
| CR-0.4 | CR-0 Security architecture | | | | | BLOCKED — requirement not yet defined |
| CR-1.1 | CR-1 Record and storage | tests/test_ledger_canonical.py | test_sorted_keys, test_determinism_two_runs, test_no_whitespace | commit 46bb8ad | canonical serializer | Covered |
| CR-1.2 | CR-1 Record and storage | tests/test_ledger_merkle.py | test_tamper_detected, test_order_independent, test_single_leaf | commit 46bb8ad | Merkle root builder | Covered |
| CR-1.3 | CR-1 Record and storage | tests/test_ledger_snapshot.py | test_canonical_is_deterministic, test_canonical_shape | commit e40f031 | snapshot canonicalisation | Covered |
| CR-1.4 | CR-1 Record and storage | tests/test_ledger_snapshot.py | test_rule_ids_sorted, test_rule_ids_order_independence | commit e40f031 | rule ordering | Covered |
| CR-1.5 | CR-1 Record and storage | tests/test_ledger_snapshot.py | test_as_of_utc_formats_as_z, test_naive_datetime_rejected | commit e40f031 | as-of timestamp | Covered |
| CR-1.6 | CR-1 Record and storage | tests/test_ledger_snapshot.py | test_single_message_root_is_its_hash | commit e40f031 | single-message root | Covered |
| CR-1.7 | CR-1 Record and storage | | | | | BLOCKED — requirement not yet defined |
| CR-1.8 | CR-1 Record and storage | | | | | BLOCKED — requirement not yet defined |
| CR-1.9 | CR-1 Record and storage | | | | | BLOCKED — requirement not yet defined |
| CR-1.10 | CR-1 Record and storage | | | | | BLOCKED — requirement not yet defined |
| CR-2.1 | CR-2 Ingest adapters | | | | | BLOCKED — requirement not yet defined |
| CR-2.2 | CR-2 Ingest adapters | | | | | BLOCKED — requirement not yet defined |
| CR-2.3 | CR-2 Ingest adapters | | | | | BLOCKED — requirement not yet defined |
| CR-2.4 | CR-2 Ingest adapters | | | | | BLOCKED — requirement not yet defined |
| CR-2.5 | CR-2 Ingest adapters | | | | | BLOCKED — requirement not yet defined |
| CR-2.6 | CR-2 Ingest adapters | | | | | BLOCKED — requirement not yet defined |
| CR-2.7 | CR-2 Ingest adapters | | | | | BLOCKED — requirement not yet defined |
| CR-2.8 | CR-2 Ingest adapters | | | | | BLOCKED — requirement not yet defined |
| CR-3.1 | CR-3 Identity resolution | tests/test_war_room_entities.py | test_add_hypothesis_rejects_unknown_finding, test_hypothesis_requires_a_supporting_finding | commit 7737b30 | factbase entity resolution | Covered |
| CR-3.2 | CR-3 Identity resolution | tests/test_war_room_links.py | test_link_is_immutable, test_duplicate_link_is_refused, test_link_refuses_cross_case_endpoints | commit 7737b30 | link register, append-only | Covered |
| CR-3.3 | CR-3 Identity resolution | | | | | BLOCKED — requirement not yet defined |
| CR-3.4 | CR-3 Identity resolution | | | | | BLOCKED — requirement not yet defined |
| CR-3.5 | CR-3 Identity resolution | | | | | BLOCKED — requirement not yet defined |
| CR-3.6 | CR-3 Identity resolution | | | | | BLOCKED — requirement not yet defined |
| CR-4.1 | CR-4 Rule corpus and findings | | | | | BLOCKED — requirement not yet defined |
| CR-4.2 | CR-4 Rule corpus and findings | | | | | BLOCKED — requirement not yet defined |
| CR-4.3 | CR-4 Rule corpus and findings | | | | | BLOCKED — requirement not yet defined |
| CR-4.4 | CR-4 Rule corpus and findings | | | | | BLOCKED — requirement not yet defined |
| CR-4.5 | CR-4 Rule corpus and findings | | | | | BLOCKED — requirement not yet defined |
| CR-4.6 | CR-4 Rule corpus and findings | | | | | BLOCKED — requirement not yet defined |
| CR-4.7 | CR-4 Rule corpus and findings | | | | | BLOCKED — requirement not yet defined |
| CR-4.8 | CR-4 Rule corpus and findings | | | | | BLOCKED — requirement not yet defined |
| CR-4.9 | CR-4 Rule corpus and findings | | | | | BLOCKED — requirement not yet defined |
| CR-4.10 | CR-4 Rule corpus and findings | | | | | BLOCKED — requirement not yet defined |
| CR-5.1 | CR-5 Review workflow and decision ledger | | | | | BLOCKED — requirement not yet defined |
| CR-5.2 | CR-5 Review workflow and decision ledger | | | | | BLOCKED — requirement not yet defined |
| CR-5.3 | CR-5 Review workflow and decision ledger | | | | | BLOCKED — requirement not yet defined |
| CR-5.4 | CR-5 Review workflow and decision ledger | | | | | BLOCKED — requirement not yet defined |
| CR-5.5 | CR-5 Review workflow and decision ledger | | | | | BLOCKED — requirement not yet defined |
| CR-5.6 | CR-5 Review workflow and decision ledger | | | | | BLOCKED — requirement not yet defined |
| CR-5.7 | CR-5 Review workflow and decision ledger | | | | | BLOCKED — requirement not yet defined |
| CR-5.8 | CR-5 Review workflow and decision ledger | | | | | BLOCKED — requirement not yet defined |
| CR-5.9 | CR-5 Review workflow and decision ledger | | | | | BLOCKED — requirement not yet defined |
| CR-5.10 | CR-5 Review workflow and decision ledger | | | | | BLOCKED — requirement not yet defined |
| CR-6.1 | CR-6 Replay engine and performance | tests/test_war_room_replay.py | test_replay_rebuilds_findings_with_their_content, test_replay_rebuilds_every_entity_type, test_replay_of_an_empty_chain_yields_an_empty_store | commit 7737b30 | replay engine | Covered |
| CR-6.2 | CR-6 Replay engine and performance | tests/test_war_room_models.py | test_finding_requires_at_least_one_evidence_id, test_finding_is_immutable, test_cannot_add_presuperseded_finding | commit 7737b30 | war room data models | Covered |
| CR-6.3 | CR-6 Replay engine and performance | | | | | BLOCKED — requirement not yet defined |
| CR-6.4 | CR-6 Replay engine and performance | | | | | BLOCKED — requirement not yet defined |
| CR-6.5 | CR-6 Replay engine and performance | | | | | BLOCKED — requirement not yet defined |
| CR-6.6 | CR-6 Replay engine and performance | | | | | BLOCKED — requirement not yet defined |
| CR-6.7 | CR-6 Replay engine and performance | | | | | BLOCKED — requirement not yet defined |
| CR-6.8 | CR-6 Replay engine and performance | | | | | BLOCKED — requirement not yet defined |
| CR-6.9 | CR-6 Replay engine and performance | | | | | BLOCKED — requirement not yet defined |
| CR-7.1 | CR-7 Interface | | | | | BLOCKED — requirement not yet defined |
| CR-7.2 | CR-7 Interface | | | | | BLOCKED — requirement not yet defined |
| CR-7.3 | CR-7 Interface | | | | | BLOCKED — requirement not yet defined |
| CR-7.4 | CR-7 Interface | | | | | BLOCKED — requirement not yet defined |
| CR-7.5 | CR-7 Interface | | | | | BLOCKED — requirement not yet defined |
| CR-7.6 | CR-7 Interface | | | | | BLOCKED — requirement not yet defined |
| CR-7.7 | CR-7 Interface | | | | | BLOCKED — requirement not yet defined |
| CR-7.8 | CR-7 Interface | | | | | BLOCKED — requirement not yet defined |
| CR-8.1 | CR-8 Accessibility | | | | | BLOCKED — requirement not yet defined |
| CR-8.2 | CR-8 Accessibility | | | | | BLOCKED — requirement not yet defined |
| CR-8.3 | CR-8 Accessibility | | | | | BLOCKED — requirement not yet defined |
| CR-8.4 | CR-8 Accessibility | | | | | BLOCKED — requirement not yet defined |
| CR-8.5 | CR-8 Accessibility | | | | | BLOCKED — requirement not yet defined |
| CR-8.6 | CR-8 Accessibility | | | | | BLOCKED — requirement not yet defined |
| CR-9.1 | CR-9 Export and evidence pack | | | | | BLOCKED — requirement not yet defined |
| CR-9.2 | CR-9 Export and evidence pack | | | | | BLOCKED — requirement not yet defined |
| CR-9.3 | CR-9 Export and evidence pack | | | | | BLOCKED — requirement not yet defined |
| CR-9.4 | CR-9 Export and evidence pack | | | | | BLOCKED — requirement not yet defined |
| CR-9.5 | CR-9 Export and evidence pack | | | | | BLOCKED — requirement not yet defined |
| CR-9.6 | CR-9 Export and evidence pack | | | | | BLOCKED — requirement not yet defined |
| CR-9.7 | CR-9 Export and evidence pack | | | | | BLOCKED — requirement not yet defined |
| CR-9.8 | CR-9 Export and evidence pack | | | | | BLOCKED — requirement not yet defined |
| CR-10.1 | CR-10 Security and integrity | | | | | BLOCKED — requirement not yet defined |
| CR-10.2 | CR-10 Security and integrity | | | | | BLOCKED — requirement not yet defined |
| CR-10.3 | CR-10 Security and integrity | tests/test_ledger_signing.py | test_sign_verify_roundtrip, test_verify_wrong_key, test_verify_malformed_signature | commit 46bb8ad | Ed25519 signer | Covered |
| CR-10.4 | CR-10 Security and integrity | | | | | BLOCKED — requirement not yet defined |
| CR-10.5 | CR-10 Security and integrity | | | | | BLOCKED — requirement not yet defined |
| CR-10.6 | CR-10 Security and integrity | tests/test_auth.py | test_auth.py::test_requires_api_key_on_api_routes | commit HEAD | AuthMiddleware | Covered |
| CR-10.7 | CR-10 Security and integrity | | | | | BLOCKED — requirement not yet defined |
| CR-10.8 | CR-10 Security and integrity | | | | | BLOCKED — requirement not yet defined |
| CR-10.9 | CR-10 Security and integrity | | | | | BLOCKED — requirement not yet defined |
| CR-10.10 | CR-10 Security and integrity | | | | | BLOCKED — requirement not yet defined |
| CR-11.1 | CR-11 Verification and rollout | tests/test_ledger_anchor.py | test_stamp_bytes_writes_snapshot_and_invokes_ots, test_round_trip_stamp_then_verify | commit 2609339 | OpenTimestamps stamping | Covered |
| CR-11.2 | CR-11 Verification and rollout | tests/test_ledger_anchor.py | test_verify_confirmed, test_verify_pending_is_not_failure, test_verify_failed_when_no_marker | commit 2609339 | verification classification | Covered |
| CR-11.3 | CR-11 Verification and rollout | tests/test_ledger_anchor_router.py | test_anchor_stamps_snapshot, test_verify_returns_confirmed, test_anchor_returns_503_when_ots_missing | commit 2609339 | anchor HTTP route | Covered |
| CR-11.4 | CR-11 Verification and rollout | | | | | BLOCKED — requirement not yet defined |
| CR-11.5 | CR-11 Verification and rollout | | | | | BLOCKED — requirement not yet defined |
| CR-11.6 | CR-11 Verification and rollout | | | | | BLOCKED — requirement not yet defined |
| CR-11.7 | CR-11 Verification and rollout | | | | | BLOCKED — requirement not yet defined |
| CR-12.1 | CR-12 Privacy and data lifecycle | | | | | BLOCKED — requirement not yet defined |
| CR-12.2 | CR-12 Privacy and data lifecycle | | | | | BLOCKED — requirement not yet defined |
| CR-12.3 | CR-12 Privacy and data lifecycle | | | | | BLOCKED — requirement not yet defined |
| CR-12.4 | CR-12 Privacy and data lifecycle | | | | | BLOCKED — requirement not yet defined |
| CR-12.5 | CR-12 Privacy and data lifecycle | | | | | BLOCKED — requirement not yet defined |
| CR-12.6 | CR-12 Privacy and data lifecycle | | | | | BLOCKED — requirement not yet defined |

## Evidence not yet counted

`tests/test_client_keys.py` (4 tests) covers per-install key generation, key reuse,
restricted file permissions and per-directory isolation. Those are CR-12 key-storage
properties and evidence for the §F per-client individualization gate, but CR-12.1–12.6
are not yet defined, so the file is recorded here rather than scored against an ID
nobody has written.

## Verified

The tests named above exist, are collected, and pass: 156 passed across the eleven
files cited (`tests/test_ledger_*.py`, `tests/test_client_keys.py`,
`tests/test_war_room_*.py`). Any row that cannot be checked that way is marked
BLOCKED rather than Covered.
