"""
Dossier DOSSIER-PIPELINE — Deterministic Replay Log

Captures ordered pipeline transitions as canonical JSONL events so a run can be
replayed or diffed against a later execution. The design is intentionally small:
it records immutable facts, not live objects.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .state_machine import TransitionTrace


def _canonical_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


@dataclass(frozen=True)
class ReplayEvent:
    sequence_no: int
    event_type: str
    timestamp_utc: str
    payload: Dict[str, Any]


@dataclass
class ReplayVerification:
    integrity_pass: bool
    total_events: int
    mismatches: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ReplayEquivalence:
    identical: bool
    trace_hash: str
    final_state: str
    mismatches: List[Dict[str, Any]] = field(default_factory=list)


class ReplayRecorder:
    """
    Append-only JSONL event recorder.

    Every event is written as a canonical JSON object with a monotonically
    increasing sequence number. Callers should record only deterministic
    state transitions and stable identifiers.
    """

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._sequence_no = 0

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def record(self, event_type: str, payload: Dict[str, Any]) -> ReplayEvent:
        self._sequence_no += 1
        event = ReplayEvent(
            sequence_no=self._sequence_no,
            event_type=event_type,
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            payload=payload,
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical_json(event.__dict__) + "\n")
        return event

    def load(self) -> List[ReplayEvent]:
        if not self.path.exists():
            return []
        events: List[ReplayEvent] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            events.append(
                ReplayEvent(
                    sequence_no=int(raw["sequence_no"]),
                    event_type=str(raw["event_type"]),
                    timestamp_utc=str(raw["timestamp_utc"]),
                    payload=dict(raw["payload"]),
                )
            )
        return events

    def verify(self) -> ReplayVerification:
        events = self.load()
        mismatches: List[Dict[str, Any]] = []

        previous_sequence = 0
        previous_timestamp: Optional[str] = None
        for event in events:
            if event.sequence_no != previous_sequence + 1:
                mismatches.append(
                    {
                        "sequence_no": event.sequence_no,
                        "field": "sequence_no",
                        "expected": previous_sequence + 1,
                        "found": event.sequence_no,
                    }
                )
            if previous_timestamp is not None and event.timestamp_utc < previous_timestamp:
                mismatches.append(
                    {
                        "sequence_no": event.sequence_no,
                        "field": "timestamp_order",
                        "expected": f">= {previous_timestamp}",
                        "found": event.timestamp_utc,
                    }
                )
            previous_sequence = event.sequence_no
            previous_timestamp = event.timestamp_utc

        return ReplayVerification(
            integrity_pass=len(mismatches) == 0,
            total_events=len(events),
            mismatches=mismatches,
        )

    def transition_trace(self) -> TransitionTrace:
        trace = TransitionTrace()
        previous_state = "RECEIVED"
        event_map = {
            "pipeline.received": "parse_ok",
            "intake.parsed": "parse_ok",
            "intake.dedup_checked": "dedup_ok",
            "classification.completed": "classify_ok",
            "policy.completed": "policy_allow",
            "policy.rejected": "policy_deny",
            "control.recorded": "evidence_written",
            "seen.committed": "commit_success",
            "intake.duplicate": "duplicate_detected",
            "outbound.confirmed": "outbound_confirm",
        }
        state_map = {
            "parse_ok": "PARSED",
            "dedup_ok": "DEDUPED",
            "classify_ok": "CLASSIFIED",
            "policy_allow": "POLICY_ALLOWED",
            "policy_deny": "POLICY_REJECTED",
            "evidence_written": "EVIDENCED",
            "commit_success": "COMMITTED",
            "duplicate_detected": "DUPLICATE",
            "outbound_confirm": "OUTBOUND_CONFIRMED",
        }
        for event in self.load():
            if event.event_type not in event_map:
                continue
            machine_event = event_map[event.event_type]
            next_state = state_map[machine_event]
            trace.record(previous_state, machine_event, next_state, event.payload)
            previous_state = next_state
        return trace

    def verify_against_spec(self) -> bool:
        seen_events = [event.event_type for event in self.load()]
        if not seen_events:
            return False
        allowed_prefixes = [
            [
                "pipeline.received",
                "intake.parsed",
                "intake.dedup_checked",
                "classification.completed",
                "provenance.completed",
                "adapter.completed",
                "policy.completed",
                "control.recorded",
                "seen.committed",
            ],
            [
                "pipeline.received",
                "intake.parsed",
                "intake.dedup_checked",
                "classification.completed",
                "provenance.completed",
                "adapter.completed",
                "policy.completed",
                "policy.rejected",
            ],
            [
                "pipeline.received",
                "intake.parsed",
                "intake.dedup_checked",
                "intake.duplicate",
            ],
        ]
        return seen_events in allowed_prefixes

    def replay_payloads(self) -> List[Dict[str, Any]]:
        return [event.payload for event in self.load()]

    def replay_projection(self) -> Dict[str, Any]:
        """
        Return a read-only derived view of the replay log.
        """
        events = self.load()
        return {
            "event_count": len(events),
            "events": [event.__dict__ for event in events],
            "verification": self.verify().__dict__,
            "spec_ok": self.verify_against_spec(),
        }

    def close(self) -> None:
        """Included for API symmetry."""
        return None


def replay_events(events: Iterable[ReplayEvent]) -> List[Dict[str, Any]]:
    return [event.payload for event in events]
