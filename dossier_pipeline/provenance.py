"""
Dossier DOSSIER-PIPELINE Provenance Curator
Trace completeness analysis and thread detection.
"""

import hashlib
import re
from typing import List, Optional

from .contracts import (
    LOW_CLASSIFICATION_CONFIDENCE,
    ActorType,
    ClassificationResult,
    EmailEnvelope,
    ProvenanceResult,
)


class ProvenanceCurator:
    """
    Checks whether an email has sufficient provenance metadata
    and detects conversation threads.
    """

    def curate(
        self,
        classification: ClassificationResult,
        envelope: EmailEnvelope
    ) -> ProvenanceResult:
        missing: List[str] = []

        # A field the connector invented counts as ABSENT for completeness. The
        # document bridge synthesises message_id, subject, sender, recipient and
        # date, so without this the record claims complete provenance built
        # entirely from values this system made up - which is the opposite of
        # what a completeness check is for.
        synthesised = set(getattr(envelope, "synthesised_fields", ()) or ())

        # Canonical field order so missing_fields is stable across runs
        # (inv_004 requires the same envelope to yield the same result).
        for field in ("message_id", "date", "sender", "subject", "recipient"):
            value = getattr(envelope, field, None)
            if not value:
                missing.append(field)
            elif field in synthesised:
                missing.append(f"{field} (synthesised)")

        # Thread detection via Re:/Fwd:/FW: prefixes.
        # Strip ALL leading prefixes iteratively so that nested replies like
        # "Re: Re: Subject" correctly reduce to "Subject" for consistent thread_id.
        thread_id: Optional[str] = None
        if envelope.subject:
            prefix_re = re.compile(
                r'^(re|fwd|fw|tr|ré):\s*', flags=re.IGNORECASE
            )
            normalized = envelope.subject
            while True:
                stripped = prefix_re.sub("", normalized)
                if stripped == normalized:
                    break
                normalized = stripped
            if normalized != envelope.subject:
                thread_id = hashlib.sha256(
                    normalized.strip().encode()
                ).hexdigest()[:16]

        complete = len(missing) == 0

        # A recognised actor is part of what "complete" means here. `decision.py`
        # already routes an unrecognised actor to QUARANTINE_REVIEW, with the
        # interpretation "Actor unrecognised manual review required", so without
        # this clause a committed record could carry that route and simultaneously
        # state human_review_required = False, and nothing would notice. The
        # threshold is the constant `inv_008` also reads, so the two cannot
        # disagree and abort a run between them.
        unrecognised_actor = classification.actor is ActorType.UNKNOWN
        human_review = (
            not complete
            or classification.confidence < LOW_CLASSIFICATION_CONFIDENCE
            or unrecognised_actor
        )

        return ProvenanceResult(
            complete=complete,
            missing_fields=missing,
            human_review_required=human_review,
            thread_id=thread_id,
            source_type=classification.actor.value
        )
