"""Contract tests for dossier_pipeline.war_room.entities.

Written before the implementation exists. Expect ModuleNotFoundError on first
run.

Phase 1b extends the fact base with the entities a theory is built from. The
rules are the same rules as `models.FactBase`, applied one level up:

  - every derived entity cites the findings it rests on, and those findings
    must exist in the FactBase it is derived from;
  - every cross-reference must resolve inside the same store and the same
    case — a theory cannot cite a hypothesis from another dossier;
  - nothing is deleted, only superseded;
  - every transition reaches the audit sink before state is committed.

Implementation-agnostic for the same reason as the 1a suite: pydantic's
ValidationError is a ValueError subclass, and a frozen-dataclass fallback
raises ValueError or AttributeError. The assertions use those supertypes.
"""

from __future__ import annotations

import pytest


# --- Fixtures: a real FactBase with two findings ---------------------

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


def _finding_ids(factbase) -> list[str]:
    return [f.id for f in factbase.list()]


# --- Hypothesis schema and scoring (6) ---

def test_hypothesis_requires_a_supporting_finding():
    from dossier_pipeline.war_room.entities import Hypothesis
    with pytest.raises(ValueError):
        Hypothesis(
            case_id="case-1",
            statement="The notice was never received.",
            supports=(),
        )


def test_hypothesis_rejects_empty_statement():
    from dossier_pipeline.war_room.entities import Hypothesis
    with pytest.raises(ValueError):
        Hypothesis(case_id="case-1", statement="", supports=("fnd_x",))


def test_hypothesis_confidence_is_optional():
    from dossier_pipeline.war_room.entities import Hypothesis
    h = Hypothesis(case_id="case-1", statement="x", supports=("fnd_x",))
    assert h.confidence is None
    assert h.status.value == "open"
    assert h.superseded_by is None


def test_hypothesis_confidence_out_of_range_rejected():
    from dossier_pipeline.war_room.entities import Hypothesis
    with pytest.raises(ValueError):
        Hypothesis(case_id="case-1", statement="x", supports=("fnd_x",), confidence=1.5)
    with pytest.raises(ValueError):
        Hypothesis(case_id="case-1", statement="x", supports=("fnd_x",), confidence=-0.1)


def test_hypothesis_is_immutable():
    from dossier_pipeline.war_room.entities import Hypothesis
    h = Hypothesis(case_id="case-1", statement="x", supports=("fnd_x",))
    with pytest.raises((TypeError, ValueError, AttributeError)):
        h.statement = "y"


def test_hypothesis_supports_is_immutable():
    from dossier_pipeline.war_room.entities import Hypothesis
    h = Hypothesis(case_id="case-1", statement="x", supports=("fnd_x",))
    with pytest.raises(AttributeError):
        h.supports.append("fnd_other")  # type: ignore[attr-defined]


# --- Option and Assumption scoring (5) ---

def test_option_scores_are_bounded():
    from dossier_pipeline.war_room.entities import Option
    with pytest.raises(ValueError):
        Option(
            case_id="case-1",
            name="Alibi witness",
            description="Call the witness",
            feasibility=1.2,
            impact=0.5,
        )
    with pytest.raises(ValueError):
        Option(
            case_id="case-1",
            name="Alibi witness",
            description="Call the witness",
            feasibility=0.5,
            impact=-0.2,
        )


def test_option_requires_scored_feasibility_and_impact():
    from dossier_pipeline.war_room.entities import Option
    o = Option(
        case_id="case-1",
        name="Alibi witness",
        description="Call the witness",
        feasibility=0.9,
        impact=0.7,
    )
    assert 0.0 <= o.feasibility <= 1.0
    assert 0.0 <= o.impact <= 1.0


def test_assumption_requires_risk_level():
    from dossier_pipeline.war_room.entities import Assumption
    with pytest.raises(ValueError):
        Assumption(case_id="case-1", statement="Witness is reliable")  # type: ignore[call-arg]


def test_assumption_risk_level_is_bounded():
    from dossier_pipeline.war_room.entities import Assumption
    with pytest.raises(ValueError):
        Assumption(case_id="case-1", statement="Witness is reliable", risk_level=2.0)


def test_assumption_scores_accept_the_bounds():
    from dossier_pipeline.war_room.entities import Assumption
    assert Assumption(case_id="case-1", statement="x", risk_level=0.0).risk_level == 0.0
    assert Assumption(case_id="case-1", statement="x", risk_level=1.0).risk_level == 1.0
# --- FrameStore: provenance against the fact base (5) ---

def _hypothesis(**overrides):
    from dossier_pipeline.war_room.entities import Hypothesis
    base = dict(
        case_id="case-1",
        statement="The notice was served on the wrong employer.",
        supports=("fnd_placeholder",),
    )
    base.update(overrides)
    return Hypothesis(**base)


def test_add_hypothesis_rejects_unknown_finding(factbase):
    from dossier_pipeline.war_room.entities import FrameStore
    store = FrameStore(factbase)
    with pytest.raises(ValueError, match="unknown finding"):
        store.add_hypothesis(_hypothesis(supports=("fnd_nope",)))


def test_add_hypothesis_rejects_finding_from_another_case(factbase):
    from dossier_pipeline.war_room.entities import FrameStore
    from dossier_pipeline.war_room.models import Finding, SourceKind

    other = factbase.add(
        Finding(
            case_id="case-2",
            statement="Another dossier entirely.",
            evidence_ids=["ev-002"],
            source_kind=SourceKind.CLASSIFIER,
            classifier_concept_id="DOCTRINE_NOTICE",
        )
    )
    store = FrameStore(factbase)
    with pytest.raises(ValueError, match="different case"):
        store.add_hypothesis(_hypothesis(case_id="case-1", supports=(other.id,)))


def test_add_hypothesis_assigns_audit_entry_id(factbase):
    from dossier_pipeline.war_room.entities import FrameStore
    store = FrameStore(factbase)
    stored = store.add_hypothesis(_hypothesis(supports=(_finding_ids(factbase)[0],)))
    assert stored.id.startswith("hyp_")
    assert stored.audit_entry_id is not None


def test_cannot_add_presuperseded_hypothesis(factbase):
    from dossier_pipeline.war_room.entities import FrameStore
    store = FrameStore(factbase)
    with pytest.raises(ValueError, match="superseded_by"):
        store.add_hypothesis(
            _hypothesis(
                supports=(_finding_ids(factbase)[0],),
                superseded_by="hyp_deadbeef",
            )
        )


def test_add_assumption_rejects_unknown_finding(factbase):
    from dossier_pipeline.war_room.entities import Assumption, FrameStore
    store = FrameStore(factbase)
    with pytest.raises(ValueError, match="unknown finding"):
        store.add_assumption(
            Assumption(
                case_id="case-1",
                statement="The witness is reliable.",
                risk_level=0.3,
                rests_on=("fnd_nope",),
            )
        )


# --- FrameStore: cross-reference integrity (5) ---

def test_option_cannot_advance_an_unknown_hypothesis(factbase):
    from dossier_pipeline.war_room.entities import FrameStore, Option
    store = FrameStore(factbase)
    with pytest.raises(ValueError, match="unknown hypothesis"):
        store.add_option(
            Option(
                case_id="case-1",
                name="Alibi witness",
                description="Call the witness",
                feasibility=0.9,
                impact=0.7,
                advances=("hyp_nope",),
            )
        )


def test_option_cannot_advance_a_hypothesis_from_another_case(factbase):
    from dossier_pipeline.war_room.entities import FrameStore, Option
    store = FrameStore(factbase)
    h = store.add_hypothesis(_hypothesis(supports=(_finding_ids(factbase)[0],)))
    with pytest.raises(ValueError, match="different case"):
        store.add_option(
            Option(
                case_id="case-2",
                name="Alibi witness",
                description="Call the witness",
                feasibility=0.9,
                impact=0.7,
                advances=(h.id,),
            )
        )


def test_theory_cannot_cite_an_unknown_hypothesis(factbase):
    from dossier_pipeline.war_room.entities import CaseTheory, FrameStore
    store = FrameStore(factbase)
    with pytest.raises(ValueError, match="unknown hypothesis"):
        store.add_theory(
            CaseTheory(
                case_id="case-1",
                title="No notice",
                summary="The notice never reached the employee.",
                hypothesis_ids=("hyp_nope",),
            )
        )


def test_theory_cannot_mix_cases(factbase):
    from dossier_pipeline.war_room.entities import CaseTheory, FrameStore
    store = FrameStore(factbase)
    h = store.add_hypothesis(_hypothesis(supports=(_finding_ids(factbase)[0],)))
    with pytest.raises(ValueError, match="different case"):
        store.add_theory(
            CaseTheory(
                case_id="case-2",
                title="No notice",
                summary="x",
                hypothesis_ids=(h.id,),
            )
        )


def test_frame_cannot_cite_an_unknown_theory(factbase):
    from dossier_pipeline.war_room.entities import FrameStore, StrategicFrame
    store = FrameStore(factbase)
    with pytest.raises(ValueError, match="unknown theory"):
        store.add_frame(
            StrategicFrame(
                case_id="case-1",
                objective="Defeat the limitation defence.",
                theory_ids=("thr_nope",),
            )
        )


# --- FrameStore: supersession, status and audit (5) ---

def test_supersede_hypothesis_leaves_the_original(factbase):
    from dossier_pipeline.war_room.entities import FrameStore
    store = FrameStore(factbase)
    fid = _finding_ids(factbase)[0]
    first = store.add_hypothesis(_hypothesis(supports=(fid,)))
    old, new = store.supersede_hypothesis(
        first.id, _hypothesis(statement="Revised.", supports=(fid,))
    )
    assert old.superseded_by == new.id
    assert store.get_hypothesis(first.id).statement == first.statement
    assert [h.id for h in store.list_hypotheses()] == [new.id]
    assert {h.id for h in store.list_hypotheses(include_superseded=True)} == {
        first.id,
        new.id,
    }


def test_cannot_supersede_a_hypothesis_twice(factbase):
    from dossier_pipeline.war_room.entities import FrameStore
    store = FrameStore(factbase)
    fid = _finding_ids(factbase)[0]
    first = store.add_hypothesis(_hypothesis(supports=(fid,)))
    store.supersede_hypothesis(first.id, _hypothesis(supports=(fid,)))
    with pytest.raises(ValueError, match="already superseded"):
        store.supersede_hypothesis(first.id, _hypothesis(supports=(fid,)))


def test_update_hypothesis_status_emits_audit(factbase):
    from dossier_pipeline.war_room.entities import FrameStore, HypothesisStatus
    store = FrameStore(factbase)
    h = store.add_hypothesis(_hypothesis(supports=(_finding_ids(factbase)[0],)))
    updated = store.update_hypothesis_status(h.id, HypothesisStatus.SUPPORTED)
    assert updated.status == HypothesisStatus.SUPPORTED
    change = store.audit_trail()[-1]
    assert change["action"] == "hypothesis_status_changed"
    assert change["from"] == "open"
    assert change["to"] == "supported"


def test_update_status_rejects_superseded_hypothesis(factbase):
    from dossier_pipeline.war_room.entities import FrameStore, HypothesisStatus
    store = FrameStore(factbase)
    fid = _finding_ids(factbase)[0]
    first = store.add_hypothesis(_hypothesis(supports=(fid,)))
    store.supersede_hypothesis(first.id, _hypothesis(supports=(fid,)))
    with pytest.raises(ValueError, match="superseded"):
        store.update_hypothesis_status(first.id, HypothesisStatus.SUPPORTED)


def test_sink_failure_rolls_back_the_hypothesis(factbase):
    from dossier_pipeline.war_room.entities import FrameStore

    def failing_sink(entry):
        raise RuntimeError("audit sink down")

    store = FrameStore(factbase, audit_sink=failing_sink)
    with pytest.raises(RuntimeError, match="audit sink down"):
        store.add_hypothesis(_hypothesis(supports=(_finding_ids(factbase)[0],)))
    assert store.list_hypotheses(include_superseded=True) == []
    assert store.audit_trail() == []
