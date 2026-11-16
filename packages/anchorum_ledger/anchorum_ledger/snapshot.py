"""LedgerSnapshot — the immutable claim the ALP signs.

A snapshot asserts: "as of as_of_utc, the system held exactly N messages,
M decisions, K rules, P identities, and Q audit rows, with merkle roots
X_message, X_decision, ... proving the exact set of records."
"""
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .canonical import canonical_hash
from .merkle import merkle_root


SNAPSHOT_VERSION = "1.0.0"


def _iso_utc(dt: datetime) -> str:
    """Format a timezone-aware datetime as ISO 8601 with Z suffix."""
    if dt.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class LedgerSnapshot:
    """Immutable snapshot of case state at a specific UTC moment."""

    case_id: str
    as_of_utc: datetime

    message_count: int
    message_merkle_root: str

    decision_count: int
    decision_merkle_root: str

    rule_count: int
    rule_merkle_root: str
    rule_ids: tuple[str, ...]

    identity_count: int
    identity_merkle_root: str

    audit_count: int
    audit_merkle_root: str

    snapshot_version: str = SNAPSHOT_VERSION

    def to_canonical(self) -> dict[str, Any]:
        return {
            "snapshot_version": self.snapshot_version,
            "case_id": self.case_id,
            "as_of_utc": _iso_utc(self.as_of_utc),
            "counts": {
                "messages": self.message_count,
                "decisions": self.decision_count,
                "rules": self.rule_count,
                "identities": self.identity_count,
                "audit_rows": self.audit_count,
            },
            "merkle_roots": {
                "messages": self.message_merkle_root,
                "decisions": self.decision_merkle_root,
                "rules": self.rule_merkle_root,
                "identities": self.identity_merkle_root,
                "audit_rows": self.audit_merkle_root,
            },
            "rule_ids": list(self.rule_ids),
        }

    def canonical_hash(self) -> str:
        return canonical_hash(self.to_canonical())


def _hash_items(items: Sequence[Mapping[str, Any]]) -> list[str]:
    return [canonical_hash(item) for item in items]


def build_snapshot(
    *,
    case_id: str,
    as_of_utc: datetime,
    messages: Sequence[Mapping[str, Any]] = (),
    decisions: Sequence[Mapping[str, Any]] = (),
    rules: Sequence[Mapping[str, Any]] = (),
    identities: Sequence[Mapping[str, Any]] = (),
    audit_rows: Sequence[Mapping[str, Any]] = (),
    snapshot_version: str = SNAPSHOT_VERSION,
) -> LedgerSnapshot:
    if not case_id:
        raise ValueError("case_id must be non-empty")
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")

    message_leaves = _hash_items(messages)
    decision_leaves = _hash_items(decisions)
    rule_leaves = _hash_items(rules)
    identity_leaves = _hash_items(identities)
    audit_leaves = _hash_items(audit_rows)

    rule_ids = tuple(sorted(str(r.get("rule_id", "")) for r in rules))

    return LedgerSnapshot(
        case_id=case_id,
        as_of_utc=as_of_utc,
        message_count=len(messages),
        message_merkle_root=merkle_root(message_leaves),
        decision_count=len(decisions),
        decision_merkle_root=merkle_root(decision_leaves),
        rule_count=len(rules),
        rule_merkle_root=merkle_root(rule_leaves),
        rule_ids=rule_ids,
        identity_count=len(identities),
        identity_merkle_root=merkle_root(identity_leaves),
        audit_count=len(audit_rows),
        audit_merkle_root=merkle_root(audit_leaves),
        snapshot_version=snapshot_version,
    )
