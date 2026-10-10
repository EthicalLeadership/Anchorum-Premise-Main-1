from __future__ import annotations

from typing import Any, Dict

VOLATILE_PAYLOAD_FIELDS = {
    "payload_hash",
    "trace",
    "decision_trace",
}


def normalize_public_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Projection-only normalizer for equivalence tests.

    This function must stay non-semantic: no policy-aware branching,
    no route rewriting, no inference.
    """
    payload = dict(record.get("payload", {}))
    for field in VOLATILE_PAYLOAD_FIELDS:
        payload.pop(field, None)

    labels = payload.get("labels")
    if isinstance(labels, list):
        payload["labels"] = sorted(labels)

    return {
        "decision": record.get("decision"),
        "route": record.get("route"),
        "payload": payload,
    }
