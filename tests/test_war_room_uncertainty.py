"""Contract tests for dossier_pipeline.war_room.uncertainty.

Written before the implementation exists.

The uncertainty register answers a question the fact base cannot: what does
this case *not* know, and does not-knowing block a theory? It is the honest
counterpart to the frame — a dossier that lists only what it has established
reads as complete when it is not.

Two rules are load-bearing and are tested explicitly:

  - A missing confidence is `None`, never `0.0`. An unquantified hypothesis and
    a hopeless one are different facts, and averaging them together would
    invent a number nobody supplied.
  - A gap that blocks a hypothesis is not the same as a gap that merely exists.
    `is_blocked` is true only for BLOCKING severity, and BLOCKING outranks a
    high risk score.
"""

from __future__ import annotations

import pytest


class FakeResolver:
    def __init__(self, known: set[str]):
        self.known = known

    def exists(self, evidence_id: str) -> bool:
        return evidence_id in self.known


@pytest.fixture()
def factbase():
    from dossier_pipeline.war_room.models import FactBase, Finding, SourceKind

    fb = FactBase(FakeResolver({"ev-001", "ev-002"}))
    fb.add(
        Finding(
            case_id="case-1",
            statement="Notice was served on 12 March.",
            evidence_ids=["ev-001"],
            source_kind=SourceKind.CLASSIFIER,
            classifier_concept_id="DOCTRINE_NOTICE",
        )
    )
    fb.add(
        Finding(
            case_id="case-1",
            statement="The notice named the wrong employer.",
            evidence_ids=["ev-002"],
            source_kind=SourceKind.CLASSIFIER,
            classifier_concept_id="DOCTRINE_NOTICE",
        )
    )
    return fb


@pytest.fixture()
def frame_store(factbase):
    from dossier_pipeline.war_room.entities import FrameStore

    return FrameStore(factbase)


def _finding_id(factbase, index: int = 0) -> str:
    return factbase.list()[index].id


def _hypothesis(frame_store, factbase, *, confidence=None, statement="x"):
    from dossier_pipeline.war_room.entities import Hypothesis

    return frame_store.add_hypothesis(
        Hypothesis(
            case_id="case-1",
            statement=statement,
            supports=(_finding_id(factbase),),
            confidence=confidence,
        )
    )


# --- KnowledgeGap schema (4) ---

def test_gap_requires_severity():
    from dossier_pipeline.war_room.uncertainty import KnowledgeGap
    with pytest.raises(ValueError):
        KnowledgeGap(case_id="case-1", description="Missing minutes")  # type: ignore[call-arg]


def test_gap_rejects_empty_description():
    from dossier_pipeline.war_room.uncertainty import GapSeverity, KnowledgeGap
    with pytest.raises(ValueError):
        KnowledgeGap(case_id="case-1", description="", severity=GapSeverity.LOW)


def test_gap_defaults_to_blocking_nothing():
    from dossier_pipeline.war_room.uncertainty import GapSeverity, KnowledgeGap
    gap = KnowledgeGap(
        case_id="case-1", description="Missing minutes", severity=GapSeverity.MEDIUM
    )
    assert gap.blocks == ()
    assert gap.rests_on == ()
    assert gap.id.startswith("gap_")


def test_gap_is_immutable():
    from dossier_pipeline.war_room.uncertainty import GapSeverity, KnowledgeGap
    gap = KnowledgeGap(
        case_id="case-1", description="Missing minutes", severity=GapSeverity.MEDIUM
    )
    with pytest.raises((TypeError, ValueError, AttributeError)):
        gap.description = "something else"


# --- Register validation (5) ---

def test_gap_cannot_block_an_unknown_hypothesis(frame_store, factbase):
    from dossier_pipeline.war_room.uncertainty import (
        GapSeverity,
        KnowledgeGap,
        UncertaintyRegister,
    )
    register = UncertaintyRegister(factbase, frame_store)
    with pytest.raises(ValueError, match="unknown hypothesis"):
        register.add_gap(
            KnowledgeGap(
                case_id="case-1",
                description="Missing minutes",
                severity=GapSeverity.HIGH,
                blocks=("hyp_nope",),
            )
        )


def test_gap_cannot_block_a_hypothesis_from_another_case(frame_store, factbase):
    from dossier_pipeline.war_room.uncertainty import (
        GapSeverity,
        KnowledgeGap,
        UncertaintyRegister,
    )
    h = _hypothesis(frame_store, factbase)
    register = UncertaintyRegister(factbase, frame_store)
    with pytest.raises(ValueError, match="different case"):
        register.add_gap(
            KnowledgeGap(
                case_id="case-2",
                description="Missing minutes",
                severity=GapSeverity.HIGH,
                blocks=(h.id,),
            )
        )


def test_gap_cannot_rest_on_an_unknown_finding(frame_store, factbase):
    from dossier_pipeline.war_room.uncertainty import (
        GapSeverity,
        KnowledgeGap,
        UncertaintyRegister,
    )
    register = UncertaintyRegister(factbase, frame_store)
    with pytest.raises(ValueError, match="unknown finding"):
        register.add_gap(
            KnowledgeGap(
                case_id="case-1",
                description="Missing minutes",
                severity=GapSeverity.HIGH,
                rests_on=("fnd_nope",),
            )
        )


def test_gap_id_collision_is_refused(frame_store, factbase):
    from dossier_pipeline.war_room.uncertainty import (
        GapSeverity,
        KnowledgeGap,
        UncertaintyRegister,
    )
    register = UncertaintyRegister(factbase, frame_store)
    gap = KnowledgeGap(
        case_id="case-1", description="Missing minutes", severity=GapSeverity.LOW
    )
    register.add_gap(gap)
    with pytest.raises(ValueError, match="collision"):
        register.add_gap(gap)


def test_sink_failure_rolls_back_the_gap(frame_store, factbase):
    from dossier_pipeline.war_room.uncertainty import (
        GapSeverity,
        KnowledgeGap,
        UncertaintyRegister,
    )

    def failing_sink(entry):
        raise RuntimeError("audit sink down")

    register = UncertaintyRegister(factbase, frame_store, audit_sink=failing_sink)
    with pytest.raises(RuntimeError, match="audit sink down"):
        register.add_gap(
            KnowledgeGap(
                case_id="case-1", description="Missing minutes", severity=GapSeverity.LOW
            )
        )
    assert register.gaps_for_case("case-1") == []


# --- Ordering and the report (6) ---

def test_gaps_are_ordered_by_severity(frame_store, factbase):
    from dossier_pipeline.war_room.uncertainty import (
        GapSeverity,
        KnowledgeGap,
        UncertaintyRegister,
    )
    register = UncertaintyRegister(factbase, frame_store)
    for severity in (
        GapSeverity.LOW,
        GapSeverity.BLOCKING,
        GapSeverity.MEDIUM,
        GapSeverity.HIGH,
    ):
        register.add_gap(
            KnowledgeGap(
                case_id="case-1", description=f"{severity.value} gap", severity=severity
            )
        )
    ordered = [gap.severity.value for gap in register.gaps_for_case("case-1")]
    assert ordered == ["blocking", "high", "medium", "low"]


def test_report_counts_hypotheses_by_status(frame_store, factbase):
    from dossier_pipeline.war_room.entities import HypothesisStatus
    from dossier_pipeline.war_room.uncertainty import UncertaintyRegister

    h1 = _hypothesis(frame_store, factbase)
    h2 = _hypothesis(frame_store, factbase)
    h3 = _hypothesis(frame_store, factbase)
    frame_store.update_hypothesis_status(h1.id, HypothesisStatus.SUPPORTED)
    frame_store.update_hypothesis_status(h2.id, HypothesisStatus.REFUTED)

    report = UncertaintyRegister(factbase, frame_store).report("case-1")
    assert report.open_hypotheses == 1
    assert report.supported_hypotheses == 1
    assert report.refuted_hypotheses == 1
    assert h3.status is HypothesisStatus.OPEN


def test_mean_confidence_is_none_when_nothing_was_quantified(frame_store, factbase):
    from dossier_pipeline.war_room.uncertainty import UncertaintyRegister

    _hypothesis(frame_store, factbase, confidence=None)
    report = UncertaintyRegister(factbase, frame_store).report("case-1")
    # None, not 0.0 — see the module docstring.
    assert report.mean_confidence is None


def test_mean_confidence_ignores_unquantified_hypotheses(frame_store, factbase):
    from dossier_pipeline.war_room.uncertainty import UncertaintyRegister

    _hypothesis(frame_store, factbase, confidence=0.8)
    _hypothesis(frame_store, factbase, confidence=0.4)
    _hypothesis(frame_store, factbase, confidence=None)
    report = UncertaintyRegister(factbase, frame_store).report("case-1")
    assert report.mean_confidence == pytest.approx(0.6)


def test_blocking_gap_sets_is_blocked(frame_store, factbase):
    from dossier_pipeline.war_room.uncertainty import (
        GapSeverity,
        KnowledgeGap,
        UncertaintyRegister,
    )
    h = _hypothesis(frame_store, factbase)
    register = UncertaintyRegister(factbase, frame_store)
    register.add_gap(
        KnowledgeGap(
            case_id="case-1",
            description="The witness cannot be located",
            severity=GapSeverity.BLOCKING,
            blocks=(h.id,),
        )
    )
    report = register.report("case-1")
    assert report.blocking_gaps == 1
    assert report.is_blocked is True


def test_high_gap_alone_does_not_block(frame_store, factbase):
    from dossier_pipeline.war_room.uncertainty import (
        GapSeverity,
        KnowledgeGap,
        UncertaintyRegister,
    )
    register = UncertaintyRegister(factbase, frame_store)
    register.add_gap(
        KnowledgeGap(
            case_id="case-1", description="Slow disclosure", severity=GapSeverity.HIGH
        )
    )
    report = register.report("case-1")
    assert report.blocking_gaps == 0
    assert report.is_blocked is False


def test_report_for_an_empty_case_is_not_an_error(frame_store, factbase):
    from dossier_pipeline.war_room.uncertainty import UncertaintyRegister

    report = UncertaintyRegister(factbase, frame_store).report("case-unseen")
    assert report.open_hypotheses == 0
    assert report.mean_confidence is None
    assert report.is_blocked is False
