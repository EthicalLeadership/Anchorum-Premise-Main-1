"""Governed `.eml` intake: envelope → classification → policy.

This is the product's front door for email. It runs the same three deterministic
stages the dossier pipeline runs, in the same order, with the same components —
`dossier_pipeline.intake.EmailIntake`, `.classifier.EmailClassifier`, and
`.policy.PolicyEngine` — so a verdict shown in the interface means what the same
verdict means inside the pipeline. Nothing here is a mock or a placeholder: if a
stage cannot run, it says so and the later stages do not pretend it succeeded.

Two deliberate differences from `DossierPipeline.process_email`:

* No control-plane commit. That method writes a signed record into the pipeline's
  own chained store, which is the dossier's ledger and not a per-click API
  action. Here the outcome is returned and audited on the case; the custody of
  the bytes belongs to the case's evidence store.
* No privacy layer re-validation or state machine. The API has already taken the
  bytes and the case already owns them; the state machine exists to govern a
  long-running pipeline run, not one request.

The stages are independent functions returning one outcome, so a failure at
classification is reported as a failure at classification rather than as a
missing policy verdict.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: The three stages the interface draws. `received` and `classified` and
#: `policy` are the names the pipeline itself uses for them.
STAGE_RECEIVED = "received"
STAGE_CLASSIFIED = "classified"
STAGE_POLICY = "policy"
STAGES = (STAGE_RECEIVED, STAGE_CLASSIFIED, STAGE_POLICY)

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

#: Overall outcomes. The vocabulary matches `ResultStatus` where it overlaps so
#: a reader does not have to translate between two same-named things.
OUTCOME_PROCESSED = "processed"
OUTCOME_REJECTED_POLICY = "rejected_policy"
OUTCOME_DUPLICATE = "duplicate"
OUTCOME_FAILED = "failed"

#: Nothing here is a size guard for the whole upload — that lives in the route.
#: This one bounds what a single message may contribute to the response: a body
#: preview that is a preview.
BODY_PREVIEW_CHARS = 280


@dataclass
class Stage:
    """One stage's outcome, as the interface draws it."""

    id: str
    status: str
    detail: str
    data: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "detail": self.detail,
            "data": self.data,
        }


@dataclass
class IntakeOutcome:
    """Everything one `.eml` produced, including what did not happen."""

    filename: str
    status: str
    stages: List[Stage]
    byte_size: int
    source_sha256: str
    message_id: str = ""
    subject: str = ""
    sender: str = ""
    recipient: str = ""
    date: str = ""
    body_preview: str = ""
    #: The full text the parser read out of the message. Not serialized into the
    #: response — a body is a document, and a document is opened, not dumped
    #: into a JSON payload — but the route stores it as the evidence sidecar so
    #: an email submitted here is searchable alongside every other exhibit.
    body_text: str = ""
    attachment_count: int = 0
    received_count: int = 0
    actor: str = ""
    labels: List[str] = field(default_factory=list)
    confidence: float = 0.0
    classification_scope_warning: str = ""
    policy_allowed: Optional[bool] = None
    policy_quarantine: Optional[bool] = None
    policy_reason: str = ""
    provenance_complete: Optional[bool] = None
    human_review_required: Optional[bool] = None
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "status": self.status,
            "stages": [stage.as_dict() for stage in self.stages],
            "byteSize": self.byte_size,
            "sourceSha256": self.source_sha256,
            "messageId": self.message_id,
            "subject": self.subject,
            "sender": self.sender,
            "recipient": self.recipient,
            "date": self.date,
            "bodyPreview": self.body_preview,
            "attachmentCount": self.attachment_count,
            "receivedCount": self.received_count,
            "actor": self.actor,
            "labels": list(self.labels),
            "confidence": self.confidence,
            "classificationScopeWarning": self.classification_scope_warning,
            "policy": {
                "allowed": self.policy_allowed,
                "quarantine": self.policy_quarantine,
                "reason": self.policy_reason,
            },
            "provenance": {
                "complete": self.provenance_complete,
                "humanReviewRequired": self.human_review_required,
            },
            "reason": self.reason,
        }


def _preview(text: str) -> str:
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= BODY_PREVIEW_CHARS:
        return collapsed
    return collapsed[:BODY_PREVIEW_CHARS].rstrip() + "…"


def run(
    raw_bytes: bytes,
    filename: str,
    seen_set: Any = None,
) -> IntakeOutcome:
    """Process one message through the three stages.

    `seen_set` is an optional `EmailSeenSet`. When given, the message is claimed
    for processing and a repeat submission is reported as a duplicate rather
    than classified twice — the same dedupe the pipeline performs. When absent,
    no dedupe claim is made and the response does not pretend one was.

    Never raises for a document-level problem: a message this system cannot read
    is a `failed` outcome with the failing stage named, which is what the
    interface needs in order to draw it.
    """
    # Imported here, not at module import time: these modules pull in the
    # dossier enforcement machinery, and an interface that cannot import them
    # must still be able to serve the rest of the API.
    from dossier_pipeline.adapter import GovernanceAdapter
    from dossier_pipeline.classifier import EmailClassifier
    from dossier_pipeline.intake import EmailIntake
    from dossier_pipeline.policy import PolicyEngine
    from dossier_pipeline.provenance import ProvenanceCurator

    outcome = IntakeOutcome(
        filename=filename,
        status=OUTCOME_FAILED,
        stages=[],
        byte_size=len(raw_bytes),
        source_sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )

    # --- Received -----------------------------------------------------------
    try:
        intake = EmailIntake(seen_set)
        envelope = intake.parse_email_bytes(raw_bytes)
    except Exception as exc:  # noqa: BLE001 - the stage boundary is the handler
        outcome.stages.append(
            Stage(
                id=STAGE_RECEIVED,
                status=STATUS_FAILED,
                detail=f"The message could not be parsed: {type(exc).__name__}",
                data={"error": type(exc).__name__},
            )
        )
        outcome.reason = "PARSE_FAILED"
        return outcome

    outcome.message_id = envelope.message_id
    outcome.subject = envelope.subject
    outcome.sender = envelope.sender
    outcome.recipient = envelope.recipient
    outcome.date = envelope.date
    outcome.body_text = envelope.body_text
    outcome.body_preview = _preview(envelope.body_text)
    outcome.attachment_count = len(envelope.attachments)
    outcome.received_count = envelope.received_count
    # `parse_email_bytes` derives `source_sha256` from the same bytes; the two
    # must agree or something upstream rewrote the artifact.
    outcome.source_sha256 = envelope.source_sha256 or outcome.source_sha256
    outcome.stages.append(
        Stage(
            id=STAGE_RECEIVED,
            status=STATUS_SUCCESS,
            detail=f"Parsed {outcome.byte_size} bytes",
            data={
                "messageId": envelope.message_id,
                "subject": envelope.subject,
                "sender": envelope.sender,
                "attachments": len(envelope.attachments),
                "receivedHeaders": envelope.received_count,
                "sourceSha256": outcome.source_sha256,
                "transport": envelope.transport,
            },
        )
    )

    # A file that parsed into a message with no headers at all is not an email.
    # `email.message_from_bytes` accepts any bytes and would hand back an
    # envelope with a synthesised id and an empty body, which then classifies as
    # correspondence and passes policy — a confident verdict about a file nobody
    # read. A real message always has at least one of these.
    if not any((envelope.sender, envelope.recipient, envelope.subject, envelope.date)):
        outcome.stages[-1] = Stage(
            id=STAGE_RECEIVED,
            status=STATUS_FAILED,
            detail="This file is not an email: it has no From, To, Subject or Date header.",
            data={"error": "NOT_AN_EMAIL"},
        )
        outcome.reason = "NOT_AN_EMAIL"
        return outcome

    # --- Dedupe (part of received) ------------------------------------------
    if seen_set is not None:
        normalized = intake.normalize(envelope)
        if normalized is None:
            outcome.status = OUTCOME_DUPLICATE
            outcome.reason = "This message has already been processed."
            outcome.stages.append(
                Stage(
                    id=STAGE_CLASSIFIED,
                    status=STATUS_SKIPPED,
                    detail="Skipped: duplicate message",
                )
            )
            outcome.stages.append(
                Stage(
                    id=STAGE_POLICY,
                    status=STATUS_SKIPPED,
                    detail="Skipped: duplicate message",
                )
            )
            return outcome
        envelope = normalized

    # --- Classified ---------------------------------------------------------
    try:
        classification = EmailClassifier().classify(envelope)
    except Exception as exc:  # noqa: BLE001 - the stage boundary is the handler
        outcome.stages.append(
            Stage(
                id=STAGE_CLASSIFIED,
                status=STATUS_FAILED,
                detail=f"Classification failed: {type(exc).__name__}",
                data={"error": type(exc).__name__},
            )
        )
        outcome.stages.append(
            Stage(
                id=STAGE_POLICY,
                status=STATUS_SKIPPED,
                detail="Skipped: classification did not complete",
            )
        )
        outcome.reason = "CLASSIFICATION_FAILED"
        return outcome

    outcome.actor = classification.actor.value
    outcome.labels = [label.value for label in classification.labels]
    outcome.confidence = classification.confidence
    outcome.classification_scope_warning = classification.classification_scope_warning
    outcome.stages.append(
        Stage(
            id=STAGE_CLASSIFIED,
            status=STATUS_SUCCESS,
            detail=f"{classification.actor.value} · {len(outcome.labels)} label(s)",
            data={
                "actor": classification.actor.value,
                "labels": list(outcome.labels),
                "confidence": classification.confidence,
                # The rule hits are what make the verdict explainable rather
                # than merely asserted. They are already in the classifier's
                # output; withholding them would leave the reader with a label
                # and no reason.
                "ruleHits": list(classification.rule_hits),
                "scopeWarning": classification.classification_scope_warning,
            },
        )
    )

    # --- Policy -------------------------------------------------------------
    try:
        provenance = ProvenanceCurator().curate(classification, envelope)
        adapted = GovernanceAdapter().adapt(classification, provenance, envelope)
        decision = PolicyEngine().evaluate(adapted)
    except Exception as exc:  # noqa: BLE001 - the stage boundary is the handler
        outcome.stages.append(
            Stage(
                id=STAGE_POLICY,
                status=STATUS_FAILED,
                detail=f"Policy check failed: {type(exc).__name__}",
                data={"error": type(exc).__name__},
            )
        )
        outcome.reason = "POLICY_CHECK_FAILED"
        return outcome

    outcome.provenance_complete = provenance.complete
    outcome.human_review_required = provenance.human_review_required
    outcome.policy_allowed = decision.allowed
    outcome.policy_quarantine = decision.quarantine
    outcome.policy_reason = decision.reason

    if decision.allowed:
        outcome.status = OUTCOME_PROCESSED
        outcome.stages.append(
            Stage(
                id=STAGE_POLICY,
                status=STATUS_SUCCESS,
                detail="Allowed",
                data={
                    "allowed": True,
                    "quarantine": False,
                    "reason": decision.reason,
                    "payloadHash": adapted.payload_hash,
                    "provenanceComplete": provenance.complete,
                    "missingFields": list(provenance.missing_fields),
                    "humanReviewRequired": provenance.human_review_required,
                },
            )
        )
    else:
        # Not a runtime failure: the policy worked. The stage fails because the
        # message did, and the interface colours it that way.
        outcome.status = OUTCOME_REJECTED_POLICY
        outcome.reason = decision.reason
        outcome.stages.append(
            Stage(
                id=STAGE_POLICY,
                status=STATUS_FAILED,
                detail=decision.reason,
                data={
                    "allowed": False,
                    "quarantine": decision.quarantine,
                    "reason": decision.reason,
                    "payloadHash": adapted.payload_hash,
                    "provenanceComplete": provenance.complete,
                    "missingFields": list(provenance.missing_fields),
                    "humanReviewRequired": provenance.human_review_required,
                },
            )
        )
    return outcome
