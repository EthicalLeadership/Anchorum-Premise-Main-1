"""
Dossier DOSSIER-PIPELINE Hardened Projection Layer v2

Projection helpers with deep immutability, schema validation, cross-store
consistency checks, and drift detection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .control import ControlPlane
from .evidence import EvidenceStore
from .intake import EmailSeenSet
from .outbound import OutboundRegistry
from .replay import ReplayRecorder


class FrozenDict(dict):
    def _blocked(self, *_: Any, **__: Any) -> None:
        raise TypeError("FrozenDict is immutable")

    __setitem__ = _blocked
    __delitem__ = _blocked
    clear = _blocked
    pop = _blocked
    popitem = _blocked
    setdefault = _blocked
    update = _blocked


def deep_freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return FrozenDict({k: deep_freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(deep_freeze(v) for v in value)
    if isinstance(value, set):
        return frozenset(deep_freeze(v) for v in value)
    if isinstance(value, tuple):
        return tuple(deep_freeze(v) for v in value)
    return value


@dataclass(frozen=True)
class SchemaField:
    name: str
    expected_type: type
    required: bool = True


class SchemaValidator:
    def __init__(self, fields: Sequence[SchemaField]):
        self.fields = tuple(fields)

    def validate(self, payload: Mapping[str, Any]) -> List[str]:
        issues: List[str] = []
        for field in self.fields:
            if field.required and field.name not in payload:
                issues.append(f"missing:{field.name}")
                continue
            if field.name in payload and not isinstance(payload[field.name], field.expected_type):
                issues.append(f"type:{field.name}")
        return issues


@dataclass(frozen=True)
class ProjectionSnapshot:
    seen_count: int
    evidence_packet_count: int
    custody_event_count: int
    outbound_send_count: int
    pending_outbound_count: int
    processed_record_count: int
    rejected_record_count: int
    quarantined_count: int
    duplicate_record_count: int
    replay_event_count: int
    control_tail_hash: str
    payload: FrozenDict

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.payload)


def rebuild_seen_projection(seen_set: EmailSeenSet) -> List[Dict[str, Any]]:
    return [deep_freeze(row) for row in seen_set.get_all()]


def rebuild_projection_snapshot(
    *,
    control: ControlPlane,
    evidence: EvidenceStore,
    outbound: OutboundRegistry,
    replay: ReplayRecorder,
    seen_count: int,
    duplicate_count: int,
    quarantined_count: int,
) -> ProjectionSnapshot:
    records = control.get_all_records()
    replay_events = replay.load()
    processed_record_count = len(records)
    rejected_record_count = sum(1 for record in records if record.get("route") == "quarantine_review")
    outbound_send_count = len(outbound.get_all())
    pending_outbound_count = len(outbound.get_pending())
    payload = deep_freeze(
        {
            "seen_count": seen_count,
            "evidence_packet_count": len(evidence.get_packets()),
            "custody_event_count": len(evidence.get_custody_events()),
            "outbound_send_count": outbound_send_count,
            "pending_outbound_count": pending_outbound_count,
            "processed_record_count": processed_record_count,
            "rejected_record_count": rejected_record_count,
            "quarantined_count": quarantined_count,
            "duplicate_record_count": duplicate_count,
            "replay_event_count": len(replay_events),
            "control_tail_hash": control.get_tail_hash(),
        }
    )
    validator = SchemaValidator(
        [
            SchemaField("seen_count", int),
            SchemaField("evidence_packet_count", int),
            SchemaField("custody_event_count", int),
            SchemaField("outbound_send_count", int),
            SchemaField("pending_outbound_count", int),
            SchemaField("processed_record_count", int),
            SchemaField("rejected_record_count", int),
            SchemaField("quarantined_count", int),
            SchemaField("duplicate_record_count", int),
            SchemaField("replay_event_count", int),
            SchemaField("control_tail_hash", str),
        ]
    )
    issues = validator.validate(payload)
    if issues:
        raise ValueError(f"Projection snapshot schema validation failed: {issues}")
    return ProjectionSnapshot(
        seen_count=seen_count,
        evidence_packet_count=len(evidence.get_packets()),
        custody_event_count=len(evidence.get_custody_events()),
        outbound_send_count=outbound_send_count,
        pending_outbound_count=pending_outbound_count,
        processed_record_count=processed_record_count,
        rejected_record_count=rejected_record_count,
        quarantined_count=quarantined_count,
        duplicate_record_count=duplicate_count,
        replay_event_count=len(replay_events),
        control_tail_hash=control.get_tail_hash(),
        payload=payload,
    )


def projection_health_report(snapshot: ProjectionSnapshot) -> Dict[str, Any]:
    severity = "INFO"
    if snapshot.control_tail_hash == "" or snapshot.processed_record_count == 0:
        severity = "WARNING"
    if snapshot.quarantined_count > 0 or snapshot.rejected_record_count > 0:
        severity = "CRITICAL"
    return {
        "ok": snapshot.control_tail_hash != "",
        "severity": severity,
        "snapshot": snapshot.as_dict(),
        "consistency": {
            "evidence_vs_control": snapshot.evidence_packet_count >= snapshot.processed_record_count,
            "seen_vs_control": snapshot.seen_count >= snapshot.processed_record_count,
            "replay_monotonic": snapshot.replay_event_count >= snapshot.processed_record_count,
        },
    }


def compare_seen_projection(seen_set: EmailSeenSet) -> Dict[str, Any]:
    snapshot = rebuild_seen_projection(seen_set)
    return {
        "legacy_count": seen_set.count(),
        "snapshot_count": len(snapshot),
        "matches": seen_set.count() == len(snapshot),
        "snapshot": snapshot,
    }


def rebuild_outbound_projection(outbound: OutboundRegistry) -> Dict[str, Any]:
    return {
        "registry": outbound.get_all(),
        "outbox": outbound.get_outbox(),
        "pending_count": len(outbound.get_pending()),
        "send_count": len(outbound.get_all()),
    }


def compare_outbound_projection(outbound: OutboundRegistry) -> Dict[str, Any]:
    snapshot = rebuild_outbound_projection(outbound)
    return {
        "legacy_send_count": len(outbound.get_all()),
        "snapshot_send_count": snapshot["send_count"],
        "matches": len(outbound.get_all()) == snapshot["send_count"],
        "snapshot": snapshot,
    }


def rebuild_evidence_projection(evidence: EvidenceStore) -> Dict[str, Any]:
    return {
        "packets": [packet.__dict__ for packet in evidence.get_packets()],
        "custody_events": [event.__dict__ for event in evidence.get_custody_events()],
        "packet_count": len(evidence.get_packets()),
        "custody_count": len(evidence.get_custody_events()),
        "system_state": evidence.state.value,
    }


def compare_evidence_projection(evidence: EvidenceStore) -> Dict[str, Any]:
    snapshot = rebuild_evidence_projection(evidence)
    return {
        "legacy_packet_count": len(evidence.get_packets()),
        "snapshot_packet_count": snapshot["packet_count"],
        "matches": len(evidence.get_packets()) == snapshot["packet_count"],
        "snapshot": snapshot,
    }


def detect_drift(previous: ProjectionSnapshot, current: ProjectionSnapshot) -> Dict[str, Any]:
    changes: Dict[str, Any] = {}
    if current.processed_record_count != previous.processed_record_count:
        changes["processed_record_count"] = {
            "previous": previous.processed_record_count,
            "current": current.processed_record_count,
        }
    if current.evidence_packet_count != previous.evidence_packet_count:
        changes["evidence_packet_count"] = {
            "previous": previous.evidence_packet_count,
            "current": current.evidence_packet_count,
        }
    if current.replay_event_count != previous.replay_event_count:
        changes["replay_event_count"] = {
            "previous": previous.replay_event_count,
            "current": current.replay_event_count,
        }
    return {"drifted": bool(changes), "changes": changes}
