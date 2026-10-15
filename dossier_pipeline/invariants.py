"""
Dossier DOSSIER-PIPELINE Runtime Invariant Definitions

Registers the runtime invariants enforced by the assertion engine. The checks
are intentionally pure so they can be used in both live execution and tests.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from .assertions import Invariant, assertions
from .contracts import LOW_CLASSIFICATION_CONFIDENCE, ActorType

CRITICAL_LABELS = {
    "conflict_marker",
    "requires_response",
    "legal_significant",
    "urgent",
}


def check_inv_001(result: Mapping[str, Any] | None) -> bool:
    if result is None:
        return True

    envelope = result.get("envelope")
    if not isinstance(envelope, Mapping):
        return False

    required_fields = [
        "message_id",
        "source",
        "timestamp",
        "subject",
        "sender",
        "body",
        "attachments",
        "headers",
        "provenance",
    ]
    return all(field in envelope for field in required_fields)


def check_inv_002(envelope: Mapping[str, Any], normalized: Any, seen_before: bool) -> bool:
    if seen_before:
        return normalized is None
    return True


def check_inv_003(raw_bytes: bytes, envelope: Mapping[str, Any]) -> bool:
    message_id = str(envelope.get("message_id", ""))
    if message_id.startswith("sha256:"):
        expected = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
        return message_id == expected
    return True


def check_inv_004(classifier: Any, envelope: Mapping[str, Any]) -> bool:
    r1 = classifier.classify(envelope)
    r2 = classifier.classify(envelope)
    return r1 == r2


def check_inv_005(adapter: Mapping[str, Any], decision: Mapping[str, Any]) -> bool:
    labels = set(adapter["payload"]["labels"])
    if labels & CRITICAL_LABELS:
        return decision["route"] == "QUARANTINE_REVIEW"
    return True


def check_inv_006(adapter: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
    payload = adapter["payload"]
    if payload.get("message_id") is None or payload.get("provenance") is None:
        return policy["allowed"] is False and policy["quarantine"] is True
    return True


def check_inv_007(prev_record: Mapping[str, Any] | None, new_record: Mapping[str, Any]) -> bool:
    if prev_record is None:
        return True
    return new_record["previous_hash"] == prev_record["record_hash"]


def check_inv_008(classification: Mapping[str, Any], provenance: Mapping[str, Any], output: Mapping[str, Any]) -> bool:
    """Human review is required unless the actor is recognised and provenance complete.

    Two defects lived here, and both made this check pass for the wrong reason:

    * the actor was compared against the uppercase string ``"UNKNOWN"`` while
      :class:`ActorType.UNKNOWN` is the lowercase ``"unknown"``. The branch could
      never fire, so "an unrecognised actor must be flagged for human review" was
      enforced by nothing at all;
    * ``provenance["confidence"]`` was the *classification's* confidence supplied
      under a provenance name, and its ``< 0.5`` threshold is subsumed by the
      ``< 0.6`` tested above it, so it could not decide the outcome either.

    The comparison now uses the enum's own value, so this check and
    :class:`ActorType` cannot drift apart again. The matching provenance signal is
    set by ``ProvenanceCurator.curate``, which requires human review for an
    unrecognised actor too: without that, this check would abort the run for real
    mail rather than describe it.
    """
    actor = str(classification.get("actor", "")).strip().lower()
    if (
        classification["confidence"] < LOW_CLASSIFICATION_CONFIDENCE
        or actor == ActorType.UNKNOWN.value
        or provenance.get("missing_fields")
    ):
        return output.get("human_review_required") is True
    return True


assertions.register(
    Invariant(
        id="inv_001",
        description="Processed email must have full envelope shape",
        check=check_inv_001,
    )
)

assertions.register(
    Invariant(
        id="inv_002",
        description="Duplicate message_id must return None",
        check=check_inv_002,
    )
)

assertions.register(
    Invariant(
        id="inv_003",
        description="Message-ID fallback must match SHA-256",
        check=check_inv_003,
    )
)

assertions.register(
    Invariant(
        id="inv_004",
        description="Classification must be deterministic",
        check=check_inv_004,
    )
)

assertions.register(
    Invariant(
        id="inv_005",
        description="Critical labels must route to quarantine",
        check=check_inv_005,
    )
)

assertions.register(
    Invariant(
        id="inv_006",
        description="Missing core fields must be rejected",
        check=check_inv_006,
    )
)

assertions.register(
    Invariant(
        id="inv_007",
        description="Control records must form hash chain",
        check=check_inv_007,
    )
)

assertions.register(
    Invariant(
        id="inv_008",
        description="Low confidence must trigger human review",
        check=check_inv_008,
    )
)
