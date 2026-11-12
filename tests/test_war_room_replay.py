"""Contract tests for dossier_pipeline.war_room.replay.

Written before the implementation exists.

The war-room stores are in-memory and single-writer by design; the durable
record is the case audit chain, which is already hash-linked and tamper-evident.
Replay projects those rows back into the stores, which means two things must
hold and are tested here:

  - **The audit entry must carry the entity, not just its id.** An entry saying
    "finding fnd_abc was created" cannot rebuild the finding, so a restart would
    silently lose every statement and every citation while the chain still
    claimed the work had happened. The payload is the record.
  - **Replay must be tolerant of what it does not know.** A chain written by a
    newer build may contain actions this build has never heard of; skipping them
    is correct, crashing is not. The skipped actions are reported by name so a
    reader can tell "nothing was skipped" from "I did not look".
"""

from __future__ import annotations

import pytest


class FakeResolver:
    def exists(self, evidence_id: str) -> bool:
        return True


def _finding(**overrides):
    from dossier_pipeline.war_room.models import Finding, SourceKind

    base = dict(
        case_id="case-1",
        statement="A finding.",
        evidence_ids=("ev-001",),
        source_kind=SourceKind.CLASSIFIER,
        classifier_concept_id="DOCTRINE_NOTICE",
    )
    base.update(overrides)
    return Finding(**base)


# --- Payload completeness (3) ---

def test_finding_audit_entry_carries_enough_to_rebuild_the_finding():
    from dossier_pipeline.war_room.models import FactBase

    entries: list[dict] = []
    factbase = FactBase(FakeResolver(), audit_sink=entries.append)
    finding = factbase.add(_finding(statement="Notice was served on 12 March."))

    entry = entries[-1]
    assert entry["finding_id"] == finding.id
    assert entry["statement"] == "Notice was served on 12 March."
    assert entry["evidence_ids"] == ["ev-001"]
    assert entry["source_kind"] == "classifier"
    assert entry["classifier_concept_id"] == "DOCTRINE_NOTICE"


def test_hypothesis_audit_entry_carries_statement_and_confidence():
    from dossier_pipeline.war_room.entities import FrameStore, Hypothesis
    from dossier_pipeline.war_room.models import FactBase

    entries: list[dict] = []
    factbase = FactBase(FakeResolver())
    finding = factbase.add(_finding())
    store = FrameStore(factbase, audit_sink=entries.append)
    store.add_hypothesis(
        Hypothesis(
            case_id="case-1",
            statement="The notice never arrived.",
            supports=(finding.id,),
            confidence=0.7,
        )
    )

    entry = entries[-1]
    assert entry["statement"] == "The notice never arrived."
    assert entry["confidence"] == 0.7


def test_theory_audit_entry_carries_the_reference_lists():
    from dossier_pipeline.war_room.entities import CaseTheory, FrameStore, Hypothesis
    from dossier_pipeline.war_room.models import FactBase

    entries: list[dict] = []
    factbase = FactBase(FakeResolver())
    finding = factbase.add(_finding())
    store = FrameStore(factbase, audit_sink=entries.append)
    hypothesis = store.add_hypothesis(
        Hypothesis(case_id="case-1", statement="x", supports=(finding.id,))
    )
    store.add_theory(
        CaseTheory(
            case_id="case-1",
            title="No notice",
            summary="Never received.",
            hypothesis_ids=(hypothesis.id,),
        )
    )

    entry = entries[-1]
    assert entry["title"] == "No notice"
    assert entry["summary"] == "Never received."
    assert entry["hypothesis_ids"] == [hypothesis.id]


# --- Fact base replay (4) ---

def _factbase_entries() -> list[dict]:
    from dossier_pipeline.war_room.models import FactBase, FindingStatus

    entries: list[dict] = []
    factbase = FactBase(FakeResolver(), audit_sink=entries.append)
    first = factbase.add(_finding(statement="First."))
    second = factbase.add(_finding(statement="Second."))
    factbase.update_status(second.id, FindingStatus.CORROBORATED)
    factbase.supersede(first.id, _finding(statement="First, revised."))
    return entries


def test_replay_rebuilds_findings_with_their_content():
    from dossier_pipeline.war_room.replay import replay_fact_base

    factbase = replay_fact_base(_factbase_entries(), FakeResolver())

    statements = {f.statement for f in factbase.list(include_superseded=True)}
    assert statements == {"First.", "Second.", "First, revised."}


def test_replay_applies_status_changes():
    from dossier_pipeline.war_room.models import FindingStatus
    from dossier_pipeline.war_room.replay import replay_fact_base

    factbase = replay_fact_base(_factbase_entries(), FakeResolver())

    corroborated = [
        f for f in factbase.list() if f.status is FindingStatus.CORROBORATED
    ]
    assert len(corroborated) == 1
    assert corroborated[0].statement == "Second."


def test_replay_applies_supersession():
    from dossier_pipeline.war_room.replay import replay_fact_base

    factbase = replay_fact_base(_factbase_entries(), FakeResolver())

    live = [f.statement for f in factbase.list()]
    assert live == ["Second.", "First, revised."]


def test_replay_of_an_empty_chain_yields_an_empty_store():
    from dossier_pipeline.war_room.replay import replay_fact_base

    factbase = replay_fact_base([], FakeResolver())
    assert factbase.list(include_superseded=True) == []


# --- Theory layer replay (3) ---

def _frame_entries() -> tuple[list[dict], object]:
    from dossier_pipeline.war_room.entities import (
        Assumption,
        CaseTheory,
        FrameStore,
        Hypothesis,
        Option,
        StrategicFrame,
    )
    from dossier_pipeline.war_room.models import FactBase

    entries: list[dict] = []
    factbase = FactBase(FakeResolver())
    finding = factbase.add(_finding())
    store = FrameStore(factbase, audit_sink=entries.append)
    hypothesis = store.add_hypothesis(
        Hypothesis(
            case_id="case-1",
            statement="H1",
            supports=(finding.id,),
            confidence=0.5,
        )
    )
    option = store.add_option(
        Option(
            case_id="case-1",
            name="Subpoena",
            description="Compel production.",
            feasibility=0.8,
            impact=0.6,
            advances=(hypothesis.id,),
        )
    )
    assumption = store.add_assumption(
        Assumption(case_id="case-1", statement="Witness reliable.", risk_level=0.3)
    )
    theory = store.add_theory(
        CaseTheory(
            case_id="case-1",
            title="T1",
            summary="S1",
            hypothesis_ids=(hypothesis.id,),
            option_ids=(option.id,),
            assumption_ids=(assumption.id,),
        )
    )
    store.add_frame(
        StrategicFrame(
            case_id="case-1", objective="Objectives.", theory_ids=(theory.id,)
        )
    )
    return entries, factbase


def test_replay_rebuilds_every_entity_type():
    from dossier_pipeline.war_room.replay import replay_frame_store

    entries, factbase = _frame_entries()
    store = replay_frame_store(entries, factbase)

    assert [h.statement for h in store.list_hypotheses()] == ["H1"]
    assert [o.name for o in store.list_options()] == ["Subpoena"]
    assert [a.statement for a in store.list_assumptions()] == ["Witness reliable."]
    assert [t.title for t in store.list_theories()] == ["T1"]
    assert [f.objective for f in store.list_frames()] == ["Objectives."]


def test_replayed_theory_keeps_its_references():
    from dossier_pipeline.war_room.replay import replay_frame_store

    entries, factbase = _frame_entries()
    store = replay_frame_store(entries, factbase)

    theory = store.list_theories()[0]
    assert theory.hypothesis_ids == (store.list_hypotheses()[0].id,)
    assert theory.option_ids == (store.list_options()[0].id,)
    assert theory.assumption_ids == (store.list_assumptions()[0].id,)


def test_replay_preserves_hypothesis_confidence():
    from dossier_pipeline.war_room.replay import replay_frame_store

    entries, factbase = _frame_entries()
    store = replay_frame_store(entries, factbase)
    assert store.list_hypotheses()[0].confidence == 0.5


# --- Uncertainty and links replay (3) ---

def test_replay_rebuilds_gaps_with_severity():
    from dossier_pipeline.war_room.replay import (
        replay_frame_store,
        replay_uncertainty,
    )
    from dossier_pipeline.war_room.uncertainty import (
        GapSeverity,
        KnowledgeGap,
        UncertaintyRegister,
    )

    entries, factbase = _frame_entries()
    store = replay_frame_store(entries, factbase)

    gap_entries: list[dict] = []
    register = UncertaintyRegister(factbase, store, audit_sink=gap_entries.append)
    register.add_gap(
        KnowledgeGap(
            case_id="case-1",
            description="Minutes missing.",
            severity=GapSeverity.BLOCKING,
        )
    )

    replayed = replay_uncertainty(gap_entries, factbase, store)
    gaps = replayed.gaps_for_case("case-1")
    assert [g.description for g in gaps] == ["Minutes missing."]
    assert gaps[0].severity is GapSeverity.BLOCKING
    assert replayed.report("case-1").is_blocked is True


def test_replay_rebuilds_links():
    from dossier_pipeline.war_room.link_register import (
        FindingLink,
        LinkKind,
        LinkRegister,
    )
    from dossier_pipeline.war_room.models import FactBase
    from dossier_pipeline.war_room.replay import replay_links

    entries: list[dict] = []
    factbase = FactBase(FakeResolver())
    first = factbase.add(_finding(statement="One."))
    second = factbase.add(_finding(statement="Two."))
    register = LinkRegister(factbase, audit_sink=entries.append)
    register.add_link(
        FindingLink(
            case_id="case-1",
            kind=LinkKind.CONTRADICTS,
            source_finding_id=first.id,
            target_finding_id=second.id,
            rationale="Cannot both hold.",
        )
    )

    replayed = replay_links(entries, factbase)
    links = replayed.links_for_case("case-1")
    assert len(links) == 1
    assert links[0].kind is LinkKind.CONTRADICTS
    assert links[0].rationale == "Cannot both hold."


def test_replay_reports_unknown_actions_instead_of_failing():
    from dossier_pipeline.war_room.replay import replay_all

    entries = [{"action": "something_from_a_newer_build", "case_id": "case-1"}]
    result = replay_all(entries, FakeResolver())

    assert result.factbase.list(include_superseded=True) == []
    assert result.skipped_actions == ["something_from_a_newer_build"]
