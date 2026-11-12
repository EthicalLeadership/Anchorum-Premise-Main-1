"""Tests for the LedgerSnapshot dataclass and build_snapshot factory."""
import hashlib
from datetime import datetime, timezone, timedelta

import pytest

from interface.ledger.snapshot import LedgerSnapshot, build_snapshot, SNAPSHOT_VERSION


AS_OF = datetime(2026, 11, 11, 14, 32, 7, tzinfo=timezone.utc)
CASE = "CA-QC-2024-018"


def _msg(mid: str, sha: str) -> dict:
    return {"message_id": mid, "content_hash": sha, "captured_at": "2026-11-01T00:00:00Z"}


def test_empty_snapshot_uses_null_root():
    snap = build_snapshot(case_id=CASE, as_of_utc=AS_OF)
    null_root = hashlib.sha256(b"").hexdigest()
    assert snap.message_count == 0
    assert snap.message_merkle_root == null_root
    assert snap.decision_count == 0
    assert snap.decision_merkle_root == null_root
    assert snap.rule_count == 0
    assert snap.rule_merkle_root == null_root
    assert snap.rule_ids == ()
    assert snap.identity_count == 0
    assert snap.identity_merkle_root == null_root
    assert snap.audit_count == 0
    assert snap.audit_merkle_root == null_root


def test_empty_case_id_rejected():
    with pytest.raises(ValueError, match="case_id"):
        build_snapshot(case_id="", as_of_utc=AS_OF)


def test_naive_datetime_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        build_snapshot(case_id=CASE, as_of_utc=datetime(2026, 11, 11, 14, 32, 7))


def test_single_message_root_is_its_hash():
    m = _msg("m1", "a" * 64)
    snap = build_snapshot(case_id=CASE, as_of_utc=AS_OF, messages=[m])
    assert snap.message_count == 1
    from interface.ledger.canonical import canonical_hash
    assert snap.message_merkle_root == canonical_hash(m)


def test_multiple_messages_counted():
    msgs = [_msg(f"m{i}", "a" * 64) for i in range(5)]
    snap = build_snapshot(case_id=CASE, as_of_utc=AS_OF, messages=msgs)
    assert snap.message_count == 5


def test_order_independence():
    msgs = [_msg(f"m{i}", chr(ord("a") + i) * 64) for i in range(5)]
    snap1 = build_snapshot(case_id=CASE, as_of_utc=AS_OF, messages=msgs)
    snap2 = build_snapshot(case_id=CASE, as_of_utc=AS_OF, messages=list(reversed(msgs)))
    assert snap1.message_merkle_root == snap2.message_merkle_root
    assert snap1.canonical_hash() == snap2.canonical_hash()


def test_canonical_is_deterministic():
    msgs = [_msg(f"m{i}", "a" * 64) for i in range(3)]
    snap1 = build_snapshot(case_id=CASE, as_of_utc=AS_OF, messages=msgs)
    snap2 = build_snapshot(case_id=CASE, as_of_utc=AS_OF, messages=msgs)
    assert snap1.canonical_hash() == snap2.canonical_hash()
    assert snap1.to_canonical() == snap2.to_canonical()


def test_different_data_different_root():
    s1 = build_snapshot(case_id=CASE, as_of_utc=AS_OF, messages=[_msg("m1", "a" * 64)])
    s2 = build_snapshot(case_id=CASE, as_of_utc=AS_OF, messages=[_msg("m1", "b" * 64)])
    assert s1.message_merkle_root != s2.message_merkle_root


def test_rule_ids_sorted():
    rules = [
        {"rule_id": "QC-CC-1613", "version": 1},
        {"rule_id": "QC-CC-1600", "version": 1},
        {"rule_id": "QC-CC-1700", "version": 1},
    ]
    snap = build_snapshot(case_id=CASE, as_of_utc=AS_OF, rules=rules)
    assert snap.rule_ids == ("QC-CC-1600", "QC-CC-1613", "QC-CC-1700")


def test_rule_ids_order_independence():
    s1 = build_snapshot(case_id=CASE, as_of_utc=AS_OF, rules=[{"rule_id": "B"}, {"rule_id": "A"}])
    s2 = build_snapshot(case_id=CASE, as_of_utc=AS_OF, rules=[{"rule_id": "A"}, {"rule_id": "B"}])
    assert s1.rule_ids == s2.rule_ids
    assert s1.rule_merkle_root == s2.rule_merkle_root


def test_canonical_shape():
    snap = build_snapshot(case_id=CASE, as_of_utc=AS_OF)
    c = snap.to_canonical()
    assert c["snapshot_version"] == SNAPSHOT_VERSION
    assert c["case_id"] == CASE
    assert c["as_of_utc"] == "2026-11-11T14:32:07Z"
    assert isinstance(c["counts"], dict)
    assert set(c["counts"].keys()) == {"messages", "decisions", "rules", "identities", "audit_rows"}
    assert set(c["merkle_roots"].keys()) == {"messages", "decisions", "rules", "identities", "audit_rows"}
    assert isinstance(c["rule_ids"], list)


def test_as_of_utc_formats_as_z():
    snap = build_snapshot(case_id=CASE, as_of_utc=AS_OF)
    assert snap.to_canonical()["as_of_utc"].endswith("Z")
    assert "+00:00" not in snap.to_canonical()["as_of_utc"]


def test_as_of_utc_normalizes_to_utc():
    tz_est = timezone(timedelta(hours=-5))
    snap = build_snapshot(case_id=CASE, as_of_utc=datetime(2026, 11, 11, 9, 32, 7, tzinfo=tz_est))
    assert snap.to_canonical()["as_of_utc"] == "2026-11-11T14:32:07Z"


def test_all_categories_populated():
    snap = build_snapshot(
        case_id=CASE, as_of_utc=AS_OF,
        messages=[_msg("m1", "a" * 64)],
        decisions=[{"finding_id": "f1", "action": "affirm"}],
        rules=[{"rule_id": "R1"}],
        identities=[{"handle": "a@b.com", "person": "P1"}],
        audit_rows=[{"at": "2026-11-01T00:00:00Z", "action": "login"}],
    )
    assert snap.message_count == 1
    assert snap.decision_count == 1
    assert snap.rule_count == 1
    assert snap.identity_count == 1
    assert snap.audit_count == 1


def test_frozen():
    snap = build_snapshot(case_id=CASE, as_of_utc=AS_OF)
    with pytest.raises(Exception):
        snap.case_id = "changed"


def test_version_override():
    snap = build_snapshot(case_id=CASE, as_of_utc=AS_OF, snapshot_version="2.0.0")
    assert snap.to_canonical()["snapshot_version"] == "2.0.0"
