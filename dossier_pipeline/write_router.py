"""
Dossier DOSSIER-PIPELINE Write Authority Router

Thin indirection layer for governed writes. In the initial refactor phase it
simply centralizes the current legacy write paths so they can be inverted in
later steps without changing behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .evidence import EvidencePacket, EvidenceStore
from .intake import EmailSeenSet
from .outbound import DocumentType, OutboundRegistry, OutboundSend, SendMethod
from .replay import ReplayEvent, ReplayRecorder


@dataclass
class WriteRouter:
    seen_set: EmailSeenSet
    outbound_registry: OutboundRegistry
    evidence_store: EvidenceStore
    replay_recorder: ReplayRecorder | None = None

    def mark_seen(self, message_id: str, sha256: str) -> None:
        self.seen_set.mark_seen(message_id, sha256)

    def register_send(
        self,
        *,
        actor: str,
        document_type: DocumentType,
        document_path: str,
        send_method: SendMethod,
        sender_address: str,
        recipient_address: str,
        tracking_number: Optional[str] = None,
        response_deadline_days: int = 30,
        notes: str = "",
    ) -> OutboundSend:
        return self.outbound_registry.register_send(
            actor=actor,
            document_type=document_type,
            document_path=document_path,
            send_method=send_method,
            sender_address=sender_address,
            recipient_address=recipient_address,
            tracking_number=tracking_number,
            response_deadline_days=response_deadline_days,
            notes=notes,
        )

    def ingest_evidence(
        self,
        *,
        event_type: str,
        raw_payload: dict[str, Any],
        normalized_payload: dict[str, Any],
        metadata: dict[str, Any],
        duplicate_of: Optional[str] = None,
        hash_chain_id: Optional[str] = None,
    ) -> EvidencePacket:
        return self.evidence_store.ingest(
            event_type=event_type,
            raw_payload=raw_payload,
            normalized_payload=normalized_payload,
            metadata=metadata,
            duplicate_of=duplicate_of,
            hash_chain_id=hash_chain_id,
        )

    def record_replay(self, event_type: str, payload: dict[str, Any]) -> ReplayEvent | None:
        if self.replay_recorder is None:
            return None
        return self.replay_recorder.record(event_type, payload)
