"""The pair D-6 is about: the flag the curator sets and the invariant that reads it.

Fixing `inv_008` on its own is not a fix. It requires
`human_review_required is True` when the actor is unrecognised, so if the
curator did not set that flag for an unrecognised actor, a real submission would
abort the run under strict mode (`ASSERT_STRICT` defaults to true) instead of
being described. These pins hold both halves and assert they agree, which is the
property the dead `"UNKNOWN"` comparison made unobservable.

Why it was dead: `check_inv_008` compared the actor against the uppercase string
`"UNKNOWN"` while `ActorType.UNKNOWN` is the lowercase `"unknown"`, so the branch
could never fire; and the caller supplied the *classification's* confidence under
a `provenance` name at a threshold the stricter test above it already covered, so
that disjunct could not decide anything either. The check therefore enforced only
"low confidence needs review", while `decision.py` separately routed an
unrecognised actor to `QUARANTINE_REVIEW` saying "manual review required". The
record could carry both statements at once.
"""

from typing import Any

from dossier_pipeline.contracts import (
    LOW_CLASSIFICATION_CONFIDENCE,
    ActorType,
    ClassificationResult,
    EmailEnvelope,
)
from dossier_pipeline.invariants import check_inv_008
from dossier_pipeline.provenance import ProvenanceCurator

FULL_CONFIDENCE = 0.9


def _envelope(**overrides) -> EmailEnvelope:
    """A message with every provenance field present and observed."""
    values: dict[str, Any] = {
        "message_id": "<scheduling@example.com>",
        "subject": "Scheduling update",
        "sender": "HR Operations <hr.operations@example.com>",
        "recipient": "user@example.com",
        "date": "Fri, 1 May 2026 09:15:00 -0400",
        "body_text": "Client scheduling update",
    }
    values.update(overrides)
    return EmailEnvelope(**values)


def _classification(actor: ActorType, confidence: float) -> ClassificationResult:
    return ClassificationResult(
        labels=[],
        confidence=confidence,
        actor=actor,
        reasoning=[],
        rule_hits=[],
    )


def _review_required(actor: ActorType, confidence: float, **envelope_overrides) -> bool:
    """Curate, then hold the curator's flag and the invariant to each other."""
    curated = ProvenanceCurator().curate(
        _classification(actor, confidence), _envelope(**envelope_overrides)
    )
    agreed = check_inv_008(
        classification={"confidence": confidence, "actor": actor.value},
        provenance={"missing_fields": curated.missing_fields},
        output={"human_review_required": curated.human_review_required},
    )
    assert agreed, (
        "the curator's flag and inv_008 disagree for "
        f"actor={actor.value} confidence={confidence}: the run would abort under "
        "strict mode rather than describe the submission"
    )
    return curated.human_review_required


def test_an_unrecognised_actor_requires_review_even_at_full_confidence() -> None:
    """Nobody was recognised as the correspondent, so a human must look.

    This is the case the dead branch hid: confidence is high and every field was
    observed, so only the actor decides it.
    """
    assert _review_required(ActorType.UNKNOWN, FULL_CONFIDENCE) is True


def test_a_recognised_actor_with_observed_fields_does_not_require_review() -> None:
    """The counterpoint: same shape, a recognised actor, nothing to flag."""
    assert _review_required(ActorType.EMPLOYER, FULL_CONFIDENCE) is False


def test_low_confidence_requires_review_for_a_recognised_actor() -> None:
    assert (
        _review_required(ActorType.EMPLOYER, LOW_CLASSIFICATION_CONFIDENCE - 0.1)
        is True
    )


def test_the_threshold_is_the_shared_constant_not_a_local_copy() -> None:
    """One threshold, so the curator and the invariant cannot drift apart.

    A local copy in either place is how the two came to disagree at 0.5 versus
    0.6, which is an abort path: below 0.6 the invariant demands review and a
    higher local threshold in the curator would not set it.
    """
    just_below = LOW_CLASSIFICATION_CONFIDENCE - 0.01
    assert _review_required(ActorType.EMPLOYER, just_below) is True
    assert _review_required(ActorType.EMPLOYER, LOW_CLASSIFICATION_CONFIDENCE) is False


def test_synthesised_fields_still_count_as_missing() -> None:
    """W2's rule, pinned here too so this file cannot regress it."""
    curated = ProvenanceCurator().curate(
        _classification(ActorType.LEGAL, FULL_CONFIDENCE),
        _envelope(
            synthesised_fields=(
                "message_id",
                "subject",
                "sender",
                "recipient",
                "date",
            )
        ),
    )

    assert set(curated.missing_fields) == {
        "message_id (synthesised)",
        "date (synthesised)",
        "sender (synthesised)",
        "subject (synthesised)",
        "recipient (synthesised)",
    }
