"""
Dossier DOSSIER-PIPELINE Provenance Curator
Trace completeness analysis and thread detection.
"""

import hashlib
import re
from typing import List, Optional

from .contracts import ClassificationResult, EmailEnvelope, ProvenanceResult


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

        if not envelope.message_id or "message_id" in synthesised:
            missing.append("message_id")
        if not envelope.date or "date" in synthesised:
            missing.append("date")
        if not envelope.sender or "sender" in synthesised:
            missing.append("sender")
        if not envelope.subject or "subject" in synthesised:
            missing.append("subject")
        if not envelope.recipient or "recipient" in synthesised:
            missing.append("recipient")

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
        human_review = not complete or classification.confidence < 0.5

        return ProvenanceResult(
            complete=complete,
            missing_fields=missing,
            human_review_required=human_review,
            thread_id=thread_id,
            source_type=classification.actor.value
        )
