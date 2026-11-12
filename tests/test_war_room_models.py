"""Contract tests for dossier_pipeline.war_room.models.

Written before the implementation exists. Expect ImportError on first run.

Implementation-agnostic: pydantic v2 ValidationError is a ValueError subclass;
a frozen-dataclass fallback would raise ValueError from __post_init__ or
AttributeError from __setattr__. Assertions use those supertypes deliberately.
"""

from __future__ import annotations

import pytest


# --- Schema: Finding (8) ---

def test_finding_requires_at_least_one_evidence_id():
    from dossier_pipeline.war_room.models import Finding, SourceKind
    with pytest.raises(ValueError):
        Finding(
            case_id="case-1",
            statement="unsourced claim",
            evidence_ids=[],
            source_kind=SourceKind.CLASSIFIER,
            classifier_concept_id="DOCTRINE_NOTICE",
        )


def test_finding_rejects_empty_case_id():
    from dossier_pipeline.war_room.models import Finding, SourceKind
    with pytest.raises(ValueError):
        Finding(
            case_id="",
            statement="x",
            evidence_ids=["ev-001"],
            source_kind=SourceKind.CLASSIFIER,
            classifier_concept_id="DOCTRINE_NOTICE",
        )


def test_finding_classifier_requires_concept_id():
    from dossier_pipeline.war_room.models import Finding, SourceKind
    with pytest.raises(ValueError):
        Finding(
            case_id="case-1",
            statement="x",
            evidence_ids=["ev-001"],
            source_kind=SourceKind.CLASSIFIER,
        )


def test_finding_authority_requires_authority_id():
    from dossier_pipeline.war_room.models import Finding, SourceKind
    with pytest.raises(ValueError):
        Finding(
            case_id="case-1",
            statement="x",
            evidence_ids=["ev-001"],
            source_kind=SourceKind.AUTHORITY,
        )


def test_finding_authority_rejects_classifier_concept():
    """source_kind and citation field must agree. No ambiguity."""
    from dossier_pipeline.war_room.models import Finding, SourceKind
    with pytest.raises(ValueError):
        Finding(
            case_id="case-1",
            statement="x",
            evidence_ids=["ev-001"],
            source_kind=SourceKind.AUTHORITY,
            authority_id="ca-on:limitations:s5@2023",
            classifier_concept_id="DOCTRINE_NOTICE",
        )


def test_finding_defaults_to_proposed():
    from dossier_pipeline.war_room.models import Finding, FindingStatus, SourceKind
    f = Finding(
        case_id="case-1",
        statement="x",
        evidence_ids=["ev-001"],
        source_kind=SourceKind.CLASSIFIER,
        classifier_concept_id="DOCTRINE_NOTICE",
    )
    assert f.status == FindingStatus.PROPOSED
    assert f.superseded_by is None
    assert f.audit_entry_id is None


def test_finding_is_immutable():
    """frozen=True: attribute reassignment raises."""
    from dossier_pipeline.war_room.models import Finding, SourceKind
    f = Finding(
        case_id="case-1",
        statement="x",
        evidence_ids=["ev-001"],
        source_kind=SourceKind.CLASSIFIER,
        classifier_concept_id="DOCTRINE_NOTICE",
    )
    with pytest.raises((TypeError, ValueError, AttributeError)):
        f.statement = "y"


def test_finding_evidence_ids_is_immutable():
    """evidence_ids must be tuple-like. Appending mutates a shared list and
    corrupts every shallow model_copy. AttributeError here proves tuple."""
    from dossier_pipeline.war_room.models import Finding, SourceKind
    f = Finding(
        case_id="case-1",
        statement="x",
        evidence_ids=["ev-001"],
        source_kind=SourceKind.CLASSIFIER,
        classifier_concept_id="DOCTRINE_NOTICE",
    )
    with pytest.raises(AttributeError):
        f.evidence_ids.append("ev-999")  # type: ignore[attr-defined]


# --- FactBase: provenance enforcement (5) ---

class FakeResolver:
    def __init__(self, known: set[str]):
        self.known = known

    def exists(self, evidence_id: str) -> bool:
        return evidence_id in self.known


def _make(**overrides):
    from dossier_pipeline.war_room.models import Finding, SourceKind
    base = dict(
        case_id="case-1",
        statement="Notice was served on 12 March.",
        evidence_ids=["ev-001"],
        source_kind=SourceKind.CLASSIFIER,
        classifier_concept_id="DOCTRINE_NOTICE",
    )
    base.update(overrides)
    return Finding(**base)


def test_factbase_rejects_unknown_evidence_id():
    from dossier_pipeline.war_room.models import FactBase
    fb = FactBase(FakeResolver({"ev-001"}))
    with pytest.raises(ValueError, match="unknown evidence_id"):
        fb.add(_make(evidence_ids=["ev-999"]))


def test_cannot_add_presuperseded_finding():
    """add() must reject superseded_by. Otherwise list() hides it and no
    finding_superseded audit event exists — replay diverges from live state."""
    from dossier_pipeline.war_room.models import FactBase
    fb = FactBase(FakeResolver({"ev-001"}))
    with pytest.raises(ValueError, match="superseded_by"):
        fb.add(_make(superseded_by="fnd_deadbeef"))


def test_cannot_add_preaudited_finding():
    """audit_entry_id is FactBase-assigned. Reject user-supplied values
    rather than silently overwriting — silently overwriting hides bugs."""
    from dossier_pipeline.war_room.models import FactBase
    fb = FactBase(FakeResolver({"ev-001"}))
    with pytest.raises(ValueError, match="audit_entry_id"):
        fb.add(_make(audit_entry_id="aud_manual"))


def test_factbase_assigns_audit_entry_id():
    from dossier_pipeline.war_room.models import FactBase
    fb = FactBase(FakeResolver({"ev-001"}))
    stored = fb.add(_make())
    assert stored.audit_entry_id is not None
    assert stored.id.startswith("fnd_")


def test_get_raises_keyerror_on_missing():
    from dossier_pipeline.war_room.models import FactBase
    fb = FactBase(FakeResolver({"ev-001"}))
    with pytest.raises(KeyError):
        fb.get("fnd_nope")


# --- FactBase: audit sink (3) ---

def test_add_rolls_back_on_sink_failure():
    """Sink is called before in-memory state is committed. If it raises,
    the finding must not be stored and the audit trail must be untouched."""
    from dossier_pipeline.war_room.models import FactBase
    attempted = []

    def failing_sink(entry):
        attempted.append(entry)
        raise RuntimeError("audit sink down")

    fb = FactBase(FakeResolver({"ev-001"}), audit_sink=failing_sink)
    with pytest.raises(RuntimeError, match="audit sink down"):
        fb.add(_make())
    assert fb.list(include_superseded=True) == []
    assert fb.audit_trail() == []
    assert len(attempted) == 1


def test_sink_receives_every_entry():
    """The default silent sink is replaceable; every transition reaches it."""
    from dossier_pipeline.war_room.models import FactBase
    received: list[dict] = []
    fb = FactBase(FakeResolver({"ev-001"}), audit_sink=received.append)
    first = fb.add(_make())
    fb.supersede(first.id, _make())
    actions = [e["action"] for e in received]
    assert actions == ["finding_created", "finding_created", "finding_superseded"]


def test_sink_cannot_corrupt_audit_mirror():
    """A mutating sink must not be able to alter the internal audit trail.
    _record passes a copy to the sink; the mirror is authoritative."""
    from dossier_pipeline.war_room.models import FactBase

    def mutating_sink(entry):
        entry["action"] = "tampered"
        entry["injected"] = True

    fb = FactBase(FakeResolver({"ev-001"}), audit_sink=mutating_sink)
    fb.add(_make())
    entry = fb.audit_trail()[0]
    assert entry["action"] == "finding_created"
    assert "injected" not in entry
# --- FactBase: supersession (6) ---

def test_supersede_leaves_old_finding_in_place():
    from dossier_pipeline.war_room.models import FactBase
    fb = FactBase(FakeResolver({"ev-001"}))
    first = fb.add(_make(statement="A"))
    old, new = fb.supersede(first.id, _make(statement="A revised"))
    assert old.superseded_by == new.id
    assert fb.get(first.id).superseded_by == new.id
    assert fb.get(first.id).statement == "A"


def test_list_hides_superseded_by_default():
    from dossier_pipeline.war_room.models import FactBase
    fb = FactBase(FakeResolver({"ev-001"}))
    first = fb.add(_make(statement="A"))
    _, new = fb.supersede(first.id, _make(statement="A revised"))
    assert [f.id for f in fb.list()] == [new.id]
    ids = {f.id for f in fb.list(include_superseded=True)}
    assert ids == {first.id, new.id}


def test_cannot_supersede_twice():
    from dossier_pipeline.war_room.models import FactBase
    fb = FactBase(FakeResolver({"ev-001"}))
    first = fb.add(_make())
    fb.supersede(first.id, _make())
    with pytest.raises(ValueError, match="already superseded"):
        fb.supersede(first.id, _make())


def test_supersede_raises_keyerror_on_missing_old():
    from dossier_pipeline.war_room.models import FactBase
    fb = FactBase(FakeResolver({"ev-001"}))
    with pytest.raises(KeyError):
        fb.supersede("fnd_nope", _make())


def test_supersede_atomic_on_add_failure():
    """If the new finding fails provenance, the old row must be untouched
    and the audit trail must not gain a spurious entry."""
    from dossier_pipeline.war_room.models import FactBase
    fb = FactBase(FakeResolver({"ev-001"}))
    first = fb.add(_make())
    with pytest.raises(ValueError, match="unknown evidence_id"):
        fb.supersede(first.id, _make(evidence_ids=["ev-999"]))
    assert fb.get(first.id).superseded_by is None
    assert [e["action"] for e in fb.audit_trail()] == ["finding_created"]


def test_supersede_partial_failure_leaves_two_heads():
    """The one documented non-atomic path: add() commits the new finding,
    then the supersede event's sink call fails. Result is two heads and
    the old finding still marked as current. This test pins the failure
    mode so a future refactor cannot silently change it (in either
    direction) without updating the module docstring's recovery story."""
    from dossier_pipeline.war_room.models import FactBase

    def failing_sink(entry):
        if entry["action"] == "finding_superseded":
            raise RuntimeError("audit sink down")

    fb = FactBase(FakeResolver({"ev-001"}), audit_sink=failing_sink)
    first = fb.add(_make(statement="A"))

    with pytest.raises(RuntimeError, match="audit sink down"):
        fb.supersede(first.id, _make(statement="A revised"))

    heads = {f.id for f in fb.list()}
    assert first.id in heads               # old never marked superseded
    assert len(heads) == 2                 # new finding is an orphan head
    # Audit mirror reflects the committed create, not the failed supersede.
    assert [e["action"] for e in fb.audit_trail()] == [
        "finding_created",
        "finding_created",
    ]


# --- FactBase: status transitions (6) ---

def test_update_status_emits_audit():
    from dossier_pipeline.war_room.models import FactBase, FindingStatus
    fb = FactBase(FakeResolver({"ev-001"}))
    first = fb.add(_make())
    updated = fb.update_status(first.id, FindingStatus.CORROBORATED)
    assert updated.status == FindingStatus.CORROBORATED
    assert fb.get(first.id).status == FindingStatus.CORROBORATED
    assert [e["action"] for e in fb.audit_trail()] == [
        "finding_created",
        "finding_status_changed",
    ]
    change = fb.audit_trail()[-1]
    assert change["from"] == "proposed"
    assert change["to"] == "corroborated"


def test_update_status_rejects_superseded():
    from dossier_pipeline.war_room.models import FactBase, FindingStatus
    fb = FactBase(FakeResolver({"ev-001"}))
    first = fb.add(_make())
    fb.supersede(first.id, _make())
    with pytest.raises(ValueError, match="superseded"):
        fb.update_status(first.id, FindingStatus.CORROBORATED)


def test_update_status_raises_keyerror_on_missing():
    from dossier_pipeline.war_room.models import FactBase, FindingStatus
    fb = FactBase(FakeResolver({"ev-001"}))
    with pytest.raises(KeyError):
        fb.update_status("fnd_nope", FindingStatus.CORROBORATED)


def test_update_status_rolls_back_on_sink_failure():
    from dossier_pipeline.war_room.models import FactBase, FindingStatus

    def failing_sink(entry):
        if entry["action"] == "finding_status_changed":
            raise RuntimeError("audit sink down")

    fb = FactBase(FakeResolver({"ev-001"}), audit_sink=failing_sink)
    first = fb.add(_make())
    with pytest.raises(RuntimeError):
        fb.update_status(first.id, FindingStatus.CORROBORATED)
    assert fb.get(first.id).status == FindingStatus.PROPOSED


def test_update_status_rejects_noop():
    """Same-status updates are audit noise on a system whose audit is the
    point. Reject rather than permit."""
    from dossier_pipeline.war_room.models import FactBase, FindingStatus
    fb = FactBase(FakeResolver({"ev-001"}))
    first = fb.add(_make())
    with pytest.raises(ValueError, match="already"):
        fb.update_status(first.id, FindingStatus.PROPOSED)


def test_update_status_rejects_non_enum_status():
    """A str reaches model_copy before failing inside _record; reject at
    the entry point so the failure mode is loud, not mysterious."""
    from dossier_pipeline.war_room.models import FactBase
    fb = FactBase(FakeResolver({"ev-001"}))
    first = fb.add(_make())
    with pytest.raises(TypeError, match="FindingStatus"):
        fb.update_status(first.id, "corroborated")  # type: ignore[arg-type]


# --- FactBase: audit trail (2) ---

def test_audit_trail_records_every_transition():
    from dossier_pipeline.war_room.models import FactBase
    fb = FactBase(FakeResolver({"ev-001"}))
    first = fb.add(_make())
    fb.supersede(first.id, _make())
    actions = [e["action"] for e in fb.audit_trail()]
    assert actions == ["finding_created", "finding_created", "finding_superseded"]


def test_audit_trail_is_defensive_copy():
    """Mutating the returned entries must not corrupt internal state."""
    from dossier_pipeline.war_room.models import FactBase
