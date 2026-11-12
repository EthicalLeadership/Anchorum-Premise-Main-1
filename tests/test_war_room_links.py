"""Contract tests for dossier_pipeline.war_room.link_register.

Written before the implementation exists.

A finding on its own says one thing. A case is mostly about how findings bear
on each other: this one corroborates that one, these two cannot both be true,
this one only matters if the other holds.

Contract:
  - Both endpoints must be findings in the fact base, in the same case. A link
    to nothing is how a contradiction quietly disappears.
  - A finding cannot link to itself.
  - `DEPENDS_ON` is acyclic. A dependency cycle means no finding in the ring can
    be established first, so the case cannot be built; refusing the link at
    write time is cheaper than discovering it during argument.
  - `SUPPORTS` and `CONTRADICTS` may be mutual. Two findings can corroborate
    each other, and two findings can be irreconcilable in both directions.
    Refusing those would forbid true statements.
  - Duplicate links are refused: the same kind, same direction, twice, adds no
    information and inflates any count taken over the register.
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

    fb = FactBase(FakeResolver({"ev-001", "ev-002", "ev-003"}))
    for index, evidence in enumerate(("ev-001", "ev-002", "ev-003")):
        fb.add(
            Finding(
                case_id="case-1",
                statement=f"Finding {index}.",
                evidence_ids=(evidence,),
                source_kind=SourceKind.CLASSIFIER,
                classifier_concept_id="DOCTRINE_NOTICE",
            )
        )
    return fb


def _ids(factbase) -> list[str]:
    return [f.id for f in factbase.list()]


def _link(factbase, **overrides):
    from dossier_pipeline.war_room.link_register import LinkKind, FindingLink

    ids = _ids(factbase)
    return FindingLink(
        case_id=overrides.get("case_id", "case-1"),
        kind=overrides.get("kind", LinkKind.SUPPORTS),
        source_finding_id=overrides.get("source_finding_id", ids[0]),
        target_finding_id=overrides.get("target_finding_id", ids[1]),
        rationale=overrides.get("rationale", "They describe the same service attempt."),
    )


# --- Schema (4) ---

def test_link_requires_rationale(factbase):
    from dossier_pipeline.war_room.link_register import LinkKind, FindingLink
    ids = _ids(factbase)
    with pytest.raises(ValueError):
        FindingLink(
            case_id="case-1",
            kind=LinkKind.SUPPORTS,
            source_finding_id=ids[0],
            target_finding_id=ids[1],
            rationale="",
        )


def test_link_rejects_self_reference(factbase):
    from dossier_pipeline.war_room.link_register import FindingLink
    ids = _ids(factbase)
    with pytest.raises(ValueError, match="itself"):
        _link(factbase, source_finding_id=ids[0], target_finding_id=ids[0])


def test_link_defaults_to_a_lnk_id(factbase):
    link = _link(factbase)
    assert link.id.startswith("lnk_")
    assert link.audit_entry_id is None


def test_link_is_immutable(factbase):
    link = _link(factbase)
    with pytest.raises((TypeError, ValueError, AttributeError)):
        link.rationale = "changed"


# --- Endpoint validation (4) ---

def test_link_refuses_unknown_source(factbase):
    from dossier_pipeline.war_room.link_register import LinkRegister
    register = LinkRegister(factbase)
    with pytest.raises(ValueError, match="unknown finding"):
        register.add_link(_link(factbase, source_finding_id="fnd_nope"))


def test_link_refuses_unknown_target(factbase):
    from dossier_pipeline.war_room.link_register import LinkRegister
    register = LinkRegister(factbase)
    with pytest.raises(ValueError, match="unknown finding"):
        register.add_link(_link(factbase, target_finding_id="fnd_nope"))


def test_link_refuses_cross_case_endpoints(factbase):
    from dossier_pipeline.war_room.link_register import LinkRegister
    from dossier_pipeline.war_room.models import Finding, SourceKind

    other = factbase.add(
        Finding(
            case_id="case-2",
            statement="From another dossier.",
            evidence_ids=("ev-003",),
            source_kind=SourceKind.CLASSIFIER,
            classifier_concept_id="DOCTRINE_NOTICE",
        )
    )
    register = LinkRegister(factbase)
    with pytest.raises(ValueError, match="different case"):
        register.add_link(_link(factbase, source_finding_id=other.id))


def test_duplicate_link_is_refused(factbase):
    from dossier_pipeline.war_room.link_register import LinkRegister
    register = LinkRegister(factbase)
    register.add_link(_link(factbase))
    # A distinct object with the same endpoints and kind: the case a caller
    # actually produces twice. Should be refused on content, not on id.
    with pytest.raises(ValueError, match="duplicate"):
        register.add_link(_link(factbase))


def test_reusing_a_link_object_is_refused_on_id(factbase):
    from dossier_pipeline.war_room.link_register import LinkRegister
    register = LinkRegister(factbase)
    link = _link(factbase)
    register.add_link(link)
    with pytest.raises(ValueError, match="id collision"):
        register.add_link(link)


# --- Cycles (4) ---

def test_dependency_chain_is_allowed(factbase):
    from dossier_pipeline.war_room.link_register import LinkKind, LinkRegister
    ids = _ids(factbase)
    register = LinkRegister(factbase)
    register.add_link(_link(factbase, kind=LinkKind.DEPENDS_ON, source_finding_id=ids[0], target_finding_id=ids[1]))
    register.add_link(_link(factbase, kind=LinkKind.DEPENDS_ON, source_finding_id=ids[1], target_finding_id=ids[2]))
    assert len(register.links_for_case("case-1")) == 2


def test_direct_dependency_cycle_is_refused(factbase):
    from dossier_pipeline.war_room.link_register import LinkKind, LinkRegister
    ids = _ids(factbase)
    register = LinkRegister(factbase)
    register.add_link(_link(factbase, kind=LinkKind.DEPENDS_ON, source_finding_id=ids[0], target_finding_id=ids[1]))
    with pytest.raises(ValueError, match="cycle"):
        register.add_link(_link(factbase, kind=LinkKind.DEPENDS_ON, source_finding_id=ids[1], target_finding_id=ids[0]))


def test_indirect_dependency_cycle_is_refused(factbase):
    from dossier_pipeline.war_room.link_register import LinkKind, LinkRegister
    ids = _ids(factbase)
    register = LinkRegister(factbase)
    register.add_link(_link(factbase, kind=LinkKind.DEPENDS_ON, source_finding_id=ids[0], target_finding_id=ids[1]))
    register.add_link(_link(factbase, kind=LinkKind.DEPENDS_ON, source_finding_id=ids[1], target_finding_id=ids[2]))
    with pytest.raises(ValueError, match="cycle"):
        register.add_link(_link(factbase, kind=LinkKind.DEPENDS_ON, source_finding_id=ids[2], target_finding_id=ids[0]))


def test_mutual_support_is_allowed(factbase):
    from dossier_pipeline.war_room.link_register import LinkKind, LinkRegister
    ids = _ids(factbase)
    register = LinkRegister(factbase)
    register.add_link(_link(factbase, kind=LinkKind.SUPPORTS, source_finding_id=ids[0], target_finding_id=ids[1]))
    register.add_link(_link(factbase, kind=LinkKind.SUPPORTS, source_finding_id=ids[1], target_finding_id=ids[0]))
    assert len(register.links_for_case("case-1")) == 2


# --- Queries and audit (4) ---

def test_links_between_returns_either_direction_for_symmetric_kinds(factbase):
    from dossier_pipeline.war_room.link_register import LinkKind, LinkRegister
    ids = _ids(factbase)
    register = LinkRegister(factbase)
    register.add_link(_link(factbase, kind=LinkKind.CONTRADICTS, source_finding_id=ids[0], target_finding_id=ids[1]))
    assert register.links_between(ids[1], ids[0])
    assert register.links_between(ids[0], ids[1])


def test_contradictions_for_returns_only_contradictions(factbase):
    from dossier_pipeline.war_room.link_register import LinkKind, LinkRegister
    ids = _ids(factbase)
    register = LinkRegister(factbase)
    register.add_link(_link(factbase, kind=LinkKind.CONTRADICTS, source_finding_id=ids[0], target_finding_id=ids[1]))
    register.add_link(_link(factbase, kind=LinkKind.SUPPORTS, source_finding_id=ids[0], target_finding_id=ids[2]))

    contradictions = register.contradictions_for(ids[0])
    assert len(contradictions) == 1
    assert contradictions[0].kind is LinkKind.CONTRADICTS


def test_link_creation_is_audited_before_commit(factbase):
    from dossier_pipeline.war_room.link_register import LinkKind, LinkRegister
    register = LinkRegister(factbase)
    stored = register.add_link(_link(factbase))
    assert stored.audit_entry_id is not None
    entry = register.audit_trail()[-1]
    assert entry["action"] == "finding_link_created"
    assert entry["kind"] == LinkKind.SUPPORTS.value


def test_sink_failure_rolls_back_the_link(factbase):
    from dossier_pipeline.war_room.link_register import LinkRegister

    def failing_sink(entry):
        raise RuntimeError("audit sink down")

    register = LinkRegister(factbase, audit_sink=failing_sink)
    with pytest.raises(RuntimeError, match="audit sink down"):
        register.add_link(_link(factbase))
    assert register.links_for_case("case-1") == []
