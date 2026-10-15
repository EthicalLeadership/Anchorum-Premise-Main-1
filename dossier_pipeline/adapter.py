"""
Dossier DOSSIER-PIPELINE Governance Adapter
Bridges classification + provenance into a governed payload.
"""

import hashlib
import json

from .contracts import (AdapterResult, ClassificationResult, EmailEnvelope,
                        ProvenanceResult)


class GovernanceAdapter:
    """
    Fuses classification and provenance into a pipeline-ready payload
    with a cryptographic payload hash.
    """

    def adapt(
        self,
        classification: ClassificationResult,
        provenance: ProvenanceResult,
        envelope: EmailEnvelope
    ) -> AdapterResult:
        trace = [
            f"Intake message_id={envelope.message_id}",
            f"Intake original_message_id={envelope.original_message_id}",
            f"Intake message_key={envelope.message_key}",
            f"Actor detected={classification.actor.value}",
            f"Labels={[l.value for l in classification.labels]}",
            f"Confidence={classification.confidence:.2f}",
            f"Provenance complete={provenance.complete}",
        ]

        payload = {
            "message_id": envelope.message_id,
            "original_message_id": envelope.original_message_id,
            "message_key": envelope.message_key,
            "actor": classification.actor.value,
            "labels": [l.value for l in classification.labels],
            # AV-06: Round confidence to 4 decimal places for reproducible hashing
            # across Python versions (float repr can vary slightly otherwise).
            "confidence": round(classification.confidence, 4),
            "provenance": {
                "complete": provenance.complete,
                "missing_fields": provenance.missing_fields,
                "human_review_required": provenance.human_review_required,
                "thread_id": provenance.thread_id,
                "source_type": provenance.source_type,
            },
            "raw_sha256": envelope.raw_sha256,
            "ingest_time": envelope.ingest_timestamp,

            # Transport-proof fields (MD-safe representation: base64, not hex).
            "received_count": envelope.received_count,
            "received_first_ts": envelope.received_first_ts,
            "received_last_ts": envelope.received_last_ts,
            "received_chain_fingerprint_b64": envelope.received_chain_fingerprint_b64,
        }

        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()

        return AdapterResult(
            classification=classification,
            provenance=provenance,
            trace=trace,
            confidence=classification.confidence,
            raw_sha256=envelope.raw_sha256,
            payload_hash=payload_hash,
            received_count=envelope.received_count,
            received_first_ts=envelope.received_first_ts,
            received_last_ts=envelope.received_last_ts,
            received_chain_fingerprint_b64=envelope.received_chain_fingerprint_b64,
            message_id=envelope.message_id,
            message_key=envelope.message_key,
            original_message_id=envelope.original_message_id,
        )
