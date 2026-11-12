"""Derived entities: the theory layer built on the fact base.

Contract:
  - Every entity cites the findings it rests on. Those findings must exist in
    the `FactBase` the store was built over, and must belong to the same case
    as the entity citing them. Cross-case citation is refused rather than
    silently allowed: a theory that leans on another dossier's findings is not
    a weaker theory, it is a different case wearing this one's name.
  - Every cross-reference between entities (an option advancing a hypothesis, a
    theory citing hypotheses, a frame citing theories) must resolve inside the
    same store and the same case.
  - Entities are immutable after construction. The only mutations are
    supersession and — for a hypothesis — a status transition. Nothing is
    deleted.
  - Every transition reaches the audit sink before in-memory state is
    committed, exactly as `models.FactBase` does. If the sink raises, the
    transition does not occur.

Deferred (documented gaps, closed as the war-room routes land):
  - Hypothesis status transitions are not policy-checked. Any transition
    between distinct statuses is accepted; which transitions are legal is a
    routing decision, not a model one.
  - `assumption.rests_on` may be empty. An assumption is a premise the theory
    needs and may be untethered from any single finding; when it is tethered,
    every cited finding is validated. An empty tuple means "working premise",
    and a reader must not treat it as evidenced.
  - Whether a theory is *any good* is not represented here. This module
    enforces structure and provenance, not judgement.

Threading: one `FrameStore` per derivation run, same rule as `FactBase`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from dossier_pipeline.war_room.models import AuditSink, FactBase


class HypothesisStatus(str, Enum):
    OPEN = "open"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    RETIRED = "retired"


class _Entity(BaseModel):
    """Shared shape: immutable, case-scoped, supersedable, audited."""

    model_config = ConfigDict(frozen=True)

    #: Each subclass supplies its own prefix via default_factory.
    id: str
    case_id: str = Field(min_length=1)
    superseded_by: str | None = None
    #: Assigned by the store on add; identifies the creation audit entry.
    audit_entry_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Hypothesis(_Entity):
    """A proposition the case is built to test.

    `supports` is mandatory and holds finding ids, not free text: a hypothesis
    with no finding behind it is an assertion, and the whole point of the fact
    base is that assertions are distinguishable from findings.
    """

    id: str = Field(default_factory=lambda: f"hyp_{uuid4().hex[:12]}")
    statement: str = Field(min_length=1)
    supports: tuple[str, ...] = Field(min_length=1)
    status: HypothesisStatus = HypothesisStatus.OPEN
    #: Unquantified unless the analyst says otherwise. None is not zero.
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class Assumption(_Entity):
    """A premise the theory needs but has not established."""

    id: str = Field(default_factory=lambda: f"asm_{uuid4().hex[:12]}")
    statement: str = Field(min_length=1)
    risk_level: float = Field(ge=0.0, le=1.0)
    #: May be empty — see the module docstring's "Deferred" note.
    rests_on: tuple[str, ...] = ()


class Option(_Entity):
    """A course of action, scored on feasibility and impact."""

    id: str = Field(default_factory=lambda: f"opt_{uuid4().hex[:12]}")
    name: str = Field(min_length=1)
    description: str = ""
    feasibility: float = Field(ge=0.0, le=1.0)
    impact: float = Field(ge=0.0, le=1.0)
    #: Hypotheses this option would test or exploit. May be empty for an
    #: option that responds to the case rather than to one hypothesis.
    advances: tuple[str, ...] = ()


class CaseTheory(_Entity):
    """A coherent account of the case, citing hypotheses rather than facts.

    The findings live one level down, reachable through each hypothesis's
    `supports`. Repeating them here would let the two disagree.
    """

    id: str = Field(default_factory=lambda: f"thr_{uuid4().hex[:12]}")
    title: str = Field(min_length=1)
    summary: str = ""
    hypothesis_ids: tuple[str, ...] = Field(min_length=1)
    option_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()


class StrategicFrame(_Entity):
    """The objective, and the theories that compete to meet it."""

    id: str = Field(default_factory=lambda: f"frm_{uuid4().hex[:12]}")
    objective: str = Field(min_length=1)
    theory_ids: tuple[str, ...] = Field(min_length=1)


class FrameStore:
    """The store the theory layer writes to.

    Same discipline as `FactBase`: append-only, audit-before-commit, no
    delete. It additionally refuses cross-case references, because the fact
    base is already scoped to one dossier and a theory that reaches into
    another one is a bug in the caller, not a modelling choice.
    """

    def __init__(self, factbase: FactBase, audit_sink: AuditSink | None = None) -> None:
        self._factbase = factbase
        self._sink: AuditSink = audit_sink or (lambda _entry: None)
        self._hypotheses: dict[str, Hypothesis] = {}
        self._assumptions: dict[str, Assumption] = {}
        self._options: dict[str, Option] = {}
        self._theories: dict[str, CaseTheory] = {}
        self._frames: dict[str, StrategicFrame] = {}
        self._audit: list[dict[str, Any]] = []

    # -- hypotheses ------------------------------------------------------

    def add_hypothesis(self, hypothesis: Hypothesis) -> Hypothesis:
        self._validate_for_add(hypothesis, self._hypotheses, "hypothesis")
        self._require_findings(hypothesis.supports, hypothesis.case_id, "hypothesis")
        audit_id = self._record(
            {
                "action": "hypothesis_created",
                "hypothesis_id": hypothesis.id,
                "case_id": hypothesis.case_id,
                "status": hypothesis.status.value,
                "supports": list(hypothesis.supports),
                "statement": hypothesis.statement,
                "confidence": hypothesis.confidence,
                "created_at": hypothesis.created_at.isoformat(),
            }
        )
        stored = hypothesis.model_copy(update={"audit_entry_id": audit_id})
        self._hypotheses[stored.id] = stored
        return stored

    def supersede_hypothesis(
        self, old_id: str, new_hypothesis: Hypothesis
    ) -> tuple[Hypothesis, Hypothesis]:
        old = self._hypotheses.get(old_id)
        if old is None:
            raise KeyError(old_id)
        if old.superseded_by:
            raise ValueError(f"{old_id} already superseded by {old.superseded_by}")

        # add() validates and commits the new row. If the supersede event
        # then fails, state has two heads — the same documented asymmetry as
        # FactBase.supersede(); wrap the derivation run in a transaction.
        stored = self.add_hypothesis(new_hypothesis)

        self._record(
            {
                "action": "hypothesis_superseded",
                "old_id": old_id,
                "new_id": stored.id,
                "case_id": old.case_id,
            }
        )
        updated_old = old.model_copy(update={"superseded_by": stored.id})
        self._hypotheses[old_id] = updated_old
        return updated_old, stored

    def update_hypothesis_status(
        self, hypothesis_id: str, new_status: HypothesisStatus
    ) -> Hypothesis:
        if not isinstance(new_status, HypothesisStatus):
            raise TypeError(
                f"new_status must be a HypothesisStatus, got {type(new_status).__name__}"
            )
        h = self._hypotheses.get(hypothesis_id)
        if h is None:
            raise KeyError(hypothesis_id)
        if h.superseded_by:
            raise ValueError(f"{hypothesis_id} is superseded; cannot update status")
        if h.status == new_status:
            raise ValueError(f"{hypothesis_id} status already {new_status.value}")

        self._record(
            {
                "action": "hypothesis_status_changed",
                "hypothesis_id": hypothesis_id,
                "from": h.status.value,
                "to": new_status.value,
                "case_id": h.case_id,
            }
        )
        updated = h.model_copy(update={"status": new_status})
        self._hypotheses[hypothesis_id] = updated
        return updated

    def get_hypothesis(self, hypothesis_id: str) -> Hypothesis:
        return self._hypotheses[hypothesis_id]

    def list_hypotheses(self, include_superseded: bool = False) -> list[Hypothesis]:
        items = list(self._hypotheses.values())
        if not include_superseded:
            items = [h for h in items if not h.superseded_by]
        return items

    # -- assumptions -----------------------------------------------------

    def add_assumption(self, assumption: Assumption) -> Assumption:
        self._validate_for_add(assumption, self._assumptions, "assumption")
        # rests_on may be empty (see the module docstring); when it is not,
        # every cited finding is checked like any other provenance claim.
        self._require_findings(assumption.rests_on, assumption.case_id, "assumption")
        audit_id = self._record(
            {
                "action": "assumption_created",
                "assumption_id": assumption.id,
                "case_id": assumption.case_id,
                "risk_level": assumption.risk_level,
                "rests_on": list(assumption.rests_on),
                "statement": assumption.statement,
                "created_at": assumption.created_at.isoformat(),
            }
        )
        stored = assumption.model_copy(update={"audit_entry_id": audit_id})
        self._assumptions[stored.id] = stored
        return stored

    def list_assumptions(self) -> list[Assumption]:
        return list(self._assumptions.values())

    # -- options ---------------------------------------------------------

    def add_option(self, option: Option) -> Option:
        self._validate_for_add(option, self._options, "option")
        for hid in option.advances:
            target = self._hypotheses.get(hid)
            if target is None:
                raise ValueError(f"unknown hypothesis: {hid}")
            self._require_same_case(target.case_id, option.case_id, f"hypothesis {hid}")
        audit_id = self._record(
            {
                "action": "option_created",
                "option_id": option.id,
                "case_id": option.case_id,
                "feasibility": option.feasibility,
                "impact": option.impact,
                "advances": list(option.advances),
                "name": option.name,
                "description": option.description,
                "created_at": option.created_at.isoformat(),
            }
        )
        stored = option.model_copy(update={"audit_entry_id": audit_id})
        self._options[stored.id] = stored
        return stored

    def list_options(self) -> list[Option]:
        return list(self._options.values())

    # -- theories and frames ---------------------------------------------

    def add_theory(self, theory: CaseTheory) -> CaseTheory:
        self._validate_for_add(theory, self._theories, "theory")
        for hid in theory.hypothesis_ids:
            target = self._hypotheses.get(hid)
            if target is None:
                raise ValueError(f"unknown hypothesis: {hid}")
            self._require_same_case(target.case_id, theory.case_id, f"hypothesis {hid}")
        for oid in theory.option_ids:
            target_option = self._options.get(oid)
            if target_option is None:
                raise ValueError(f"unknown option: {oid}")
            self._require_same_case(
                target_option.case_id, theory.case_id, f"option {oid}"
            )
        for aid in theory.assumption_ids:
            target_assumption = self._assumptions.get(aid)
            if target_assumption is None:
                raise ValueError(f"unknown assumption: {aid}")
            self._require_same_case(
                target_assumption.case_id, theory.case_id, f"assumption {aid}"
            )
        audit_id = self._record(
            {
                "action": "theory_created",
                "theory_id": theory.id,
                "case_id": theory.case_id,
                "hypothesis_ids": list(theory.hypothesis_ids),
                "option_ids": list(theory.option_ids),
                "assumption_ids": list(theory.assumption_ids),
                "title": theory.title,
                "summary": theory.summary,
                "created_at": theory.created_at.isoformat(),
            }
        )
        stored = theory.model_copy(update={"audit_entry_id": audit_id})
        self._theories[stored.id] = stored
        return stored

    def get_theory(self, theory_id: str) -> CaseTheory:
        return self._theories[theory_id]

    def list_theories(self) -> list[CaseTheory]:
        return list(self._theories.values())

    def add_frame(self, frame: StrategicFrame) -> StrategicFrame:
        self._validate_for_add(frame, self._frames, "frame")
        for tid in frame.theory_ids:
            target = self._theories.get(tid)
            if target is None:
                raise ValueError(f"unknown theory: {tid}")
            self._require_same_case(target.case_id, frame.case_id, f"theory {tid}")
        audit_id = self._record(
            {
                "action": "frame_created",
                "frame_id": frame.id,
                "case_id": frame.case_id,
                "objective": frame.objective,
                "theory_ids": list(frame.theory_ids),
                "created_at": frame.created_at.isoformat(),
            }
        )
        stored = frame.model_copy(update={"audit_entry_id": audit_id})
        self._frames[stored.id] = stored
        return stored

    def list_frames(self) -> list[StrategicFrame]:
        return list(self._frames.values())

    # -- replay path -----------------------------------------------------

    def restore(
        self,
        *,
        hypotheses: Iterable[Hypothesis] = (),
        assumptions: Iterable[Assumption] = (),
        options: Iterable[Option] = (),
        theories: Iterable[CaseTheory] = (),
        frames: Iterable[StrategicFrame] = (),
    ) -> None:
        """Install already-audited entities verbatim. Replay only.

        Same reasoning as `models.FactBase.restore`: the rows are already in
        the case chain, so re-auditing them would duplicate it, and the
        provenance checks cannot be re-run because a replayed store is built
        one layer at a time. Callers must pass entities whose cross-references
        and `superseded_by` already reflect the end state of the chain.
        """
        for hypothesis in hypotheses:
            self._hypotheses[hypothesis.id] = hypothesis
        for assumption in assumptions:
            self._assumptions[assumption.id] = assumption
        for option in options:
            self._options[option.id] = option
        for theory in theories:
            self._theories[theory.id] = theory
        for frame in frames:
            self._frames[frame.id] = frame

    # -- read paths ------------------------------------------------------

    def audit_trail(self) -> list[dict[str, Any]]:
        return [dict(entry) for entry in self._audit]

    # Deliberately no delete().

    # -- internals -------------------------------------------------------

    def _validate_for_add(
        self,
        entity: _Entity,
        registry: dict[str, Any],
        kind: str,
    ) -> None:
        if entity.audit_entry_id is not None:
            raise ValueError("audit_entry_id is assigned by FrameStore; do not set it")
        if entity.superseded_by is not None:
            raise ValueError(
                f"cannot add a {kind} with superseded_by set; use supersede_hypothesis()"
            )
        if entity.id in registry:
            raise ValueError(f"{kind} id collision: {entity.id}")

    def _require_findings(
        self, finding_ids: tuple[str, ...], case_id: str, kind: str
    ) -> None:
        for fid in finding_ids:
            try:
                finding = self._factbase.get(fid)
            except KeyError:
                raise ValueError(f"unknown finding: {fid}") from None
            self._require_same_case(finding.case_id, case_id, f"finding {fid}")

    @staticmethod
    def _require_same_case(target_case: str, entity_case: str, subject: str) -> None:
        if target_case != entity_case:
            raise ValueError(
                f"{subject} belongs to case {target_case!r}, which is a different "
                f"case from {entity_case!r}"
            )

    def _record(self, entry: dict[str, Any]) -> str:
        """Deliver to the sink, then append to the mirror. Returns the audit id.

        If the sink raises, nothing is appended and the caller's state commit
        does not happen — the transition simply did not occur.
        """
        audit_id = f"aud_{uuid4().hex[:12]}"
        record = {"audit_entry_id": audit_id, **entry}
        self._sink(dict(record))
        self._audit.append(record)
        return audit_id
