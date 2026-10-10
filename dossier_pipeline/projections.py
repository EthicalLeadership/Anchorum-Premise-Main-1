"""
Dossier DOSSIER-PIPELINE — Projection helpers

This module provides deterministic rebuild views for the auxiliary stores.
The control plane remains the canonical history; these helpers derive
operational projections from persisted records and replay facts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Sequence

from .contracts import ResultStatus
from .control import ControlPlane
from .evidence import EvidenceStore
from .intake import EmailSeenSet
from .outbound import OutboundRegistry
from .replay import ReplayRecorder


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

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def rebuild_seen_projection(seen_set: EmailSeenSet) -> List[Dict[str, Any]]:
    """
    Return a stable read-only snapshot of the deduplication table.

    This is the derived view used to compare legacy storage against the
    future projection-only seen set.
    """
    return seen_set.get_all()


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
    """
    Build a stable operational snapshot from persisted stores.

    The snapshot is intentionally conservative: it does not attempt to
    infer missing canonical events. Instead, it summarizes the stores that
    already exist and anchors them to the control-plane tail hash.
    """
    records = control.get_all_records()
    replay_events = replay.load()

    processed_record_count = len(records)
    rejected_record_count = sum(1 for record in records if record.get("route") == "quarantine_review")
    outbound_send_count = len(outbound.get_all())
    pending_outbound_count = len(outbound.get_pending())

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
    )


def compare_seen_projection(seen_set: EmailSeenSet) -> Dict[str, Any]:
    """
    Compare legacy SeenSet storage to the derived read-only snapshot.

    The comparison is intentionally simple: it verifies the set is readable and
    exposes the same processed count as the live accessor.
    """
    snapshot = rebuild_seen_projection(seen_set)
    return {
        "legacy_count": seen_set.count(),
        "snapshot_count": len(snapshot),
        "matches": seen_set.count() == len(snapshot),
        "snapshot": snapshot,
    }


def rebuild_outbound_projection(outbound: OutboundRegistry) -> Dict[str, Any]:
    """
    Return a read-only outbound registry projection for parity checks.
    """
    return {
        "registry": outbound.get_all(),
        "outbox": outbound.get_outbox(),
        "pending_count": len(outbound.get_pending()),
        "send_count": len(outbound.get_all()),
    }


def compare_outbound_projection(outbound: OutboundRegistry) -> Dict[str, Any]:
    """
    Compare the live outbound registry against its read-only projection.
    """
    snapshot = rebuild_outbound_projection(outbound)
    return {
        "legacy_send_count": len(outbound.get_all()),
        "snapshot_send_count": snapshot["send_count"],
        "matches": len(outbound.get_all()) == snapshot["send_count"],
        "snapshot": snapshot,
    }


def rebuild_evidence_projection(evidence: EvidenceStore) -> Dict[str, Any]:
    """
    Return a read-only evidence-store projection for parity checks.
    """
    return {
        "packets": [packet.__dict__ for packet in evidence.get_packets()],
        "custody_events": [event.__dict__ for event in evidence.get_custody_events()],
        "packet_count": len(evidence.get_packets()),
        "custody_count": len(evidence.get_custody_events()),
        "system_state": evidence.state.value,
    }


def compare_evidence_projection(evidence: EvidenceStore) -> Dict[str, Any]:
    """
    Compare the live evidence store against its read-only projection.
    """
    snapshot = rebuild_evidence_projection(evidence)
    return {
        "legacy_packet_count": len(evidence.get_packets()),
        "snapshot_packet_count": snapshot["packet_count"],
        "matches": len(evidence.get_packets()) == snapshot["packet_count"],
        "snapshot": snapshot,
    }


def projection_health_report(snapshot: ProjectionSnapshot) -> Dict[str, Any]:
    """
    Emit a minimal health report for tests and ops tooling.
    """
    return {
        "ok": snapshot.control_tail_hash != "",
        "snapshot": snapshot.as_dict(),
        "derived_status": (
            ResultStatus.PROCESSED.value
            if snapshot.processed_record_count > 0
            else ResultStatus.DUPLICATE.value
        ),
    }
