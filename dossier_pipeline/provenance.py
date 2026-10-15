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

        if not envelope.message_id:
            missing.append("message_id")
        if not envelope.date:
            missing.append("date")
        if not envelope.sender:
            missing.append("sender")
        if not envelope.subject:
            missing.append("subject")

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
