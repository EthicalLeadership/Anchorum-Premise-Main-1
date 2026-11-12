"""What the case does not know, and whether that stops a theory.

The fact base records what is established; the frame records what is argued.
Neither records the third thing a reader of a dossier needs: where the evidence
runs out. This module holds that, in the same append-only, audited form.

Contract:
  - Every gap declares a severity. A gap with no severity is a note, and notes
    do not survive review.
  - A gap may name the hypotheses it blocks, and the findings that revealed it.
    Both are validated against the fact base and the frame — same case, must
    exist.
  - Gaps are never deleted and are listed worst first.
  - `UncertaintyReport.mean_confidence` is `None` when no hypothesis declared a
    confidence. It is never `0.0` for "unquantified": inventing a zero would
    make an open question look like a hopeless one.
  - `is_blocked` is true only for a BLOCKING gap. A HIGH gap is a problem; a
    BLOCKING gap means a theory cannot be tested until it is closed, and a
    reader must be able to tell those apart at a glance.

Deferred:
  - Severity is declared by the analyst, not computed from the evidence. Any
    scoring of "how much does this gap matter" is judgement, and judgement
    belongs in the analyst's hands with the declaration visible.
  - The report does not weight confidence by the number of findings a
    hypothesis rests on. A mean over declared confidences is a summary, not a
    posterior, and must not be presented as one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from dossier_pipeline.war_room.entities import (
    FrameStore,
    Hypothesis,
    HypothesisStatus,
)
from dossier_pipeline.war_room.models import AuditSink, FactBase


class GapSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKING = "blocking"


#: Worst first. Used for ordering, not for scoring.
_SEVERITY_RANK: dict[GapSeverity, int] = {
    GapSeverity.BLOCKING: 0,
    GapSeverity.HIGH: 1,
    GapSeverity.MEDIUM: 2,
    GapSeverity.LOW: 3,
}


class KnowledgeGap(BaseModel):
    """One thing the case does not know."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: f"gap_{uuid4().hex[:12]}")
    case_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    severity: GapSeverity
    #: Hypotheses that cannot be settled until this gap is closed.
    blocks: tuple[str, ...] = ()
    #: Findings that revealed the gap — e.g. the contradictory pair. May be
    #: empty, which means the gap was noticed rather than evidenced.
    rests_on: tuple[str, ...] = ()
    audit_entry_id: str | None = None


@dataclass(frozen=True)
class UncertaintyReport:
    """A case's uncertainty, summarised. Counts are over live hypotheses."""

    case_id: str
    open_hypotheses: int
    supported_hypotheses: int
    refuted_hypotheses: int
    retired_hypotheses: int
    #: Mean over the hypotheses that declared one; None if none did.
    mean_confidence: float | None
    total_gaps: int
    blocking_gaps: int
    is_blocked: bool


class UncertaintyRegister:
    """Append-only register of knowledge gaps, audited like the fact base."""

    def __init__(
        self,
        factbase: FactBase,
        frame_store: FrameStore,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self._factbase = factbase
        self._frame_store = frame_store
        self._sink: AuditSink = audit_sink or (lambda _entry: None)
        self._gaps: dict[str, KnowledgeGap] = {}
        self._audit: list[dict[str, Any]] = []

    # -- write path ------------------------------------------------------

    def add_gap(self, gap: KnowledgeGap) -> KnowledgeGap:
        if gap.audit_entry_id is not None:
            raise ValueError("audit_entry_id is assigned by UncertaintyRegister")
        if gap.id in self._gaps:
            raise ValueError(f"gap id collision: {gap.id}")

        for hid in gap.blocks:
            try:
                hypothesis = self._frame_store.get_hypothesis(hid)
            except KeyError:
                raise ValueError(f"unknown hypothesis: {hid}") from None
            _require_same_case(hypothesis.case_id, gap.case_id, f"hypothesis {hid}")

        for fid in gap.rests_on:
            try:
                finding = self._factbase.get(fid)
            except KeyError:
                raise ValueError(f"unknown finding: {fid}") from None
            _require_same_case(finding.case_id, gap.case_id, f"finding {fid}")

        audit_id = f"aud_{uuid4().hex[:12]}"
        self._record(
            {
                "audit_entry_id": audit_id,
                "action": "knowledge_gap_recorded",
                "gap_id": gap.id,
                "case_id": gap.case_id,
                "description": gap.description,
                "severity": gap.severity.value,
                "blocks": list(gap.blocks),
                "rests_on": list(gap.rests_on),
            }
        )
        stored = gap.model_copy(update={"audit_entry_id": audit_id})
        self._gaps[stored.id] = stored
        return stored

    # -- read paths ------------------------------------------------------

    def gaps_for_case(self, case_id: str) -> list[KnowledgeGap]:
        """Worst first. Stable within a severity, so insertion order survives."""
        matching = [g for g in self._gaps.values() if g.case_id == case_id]
        return sorted(matching, key=lambda g: _SEVERITY_RANK[g.severity])

    def report(self, case_id: str) -> UncertaintyReport:
        hypotheses = [
            h for h in self._frame_store.list_hypotheses() if h.case_id == case_id
        ]
        confidences = [
            h.confidence for h in hypotheses if h.confidence is not None
        ]
        gaps = self.gaps_for_case(case_id)
        blocking = sum(1 for g in gaps if g.severity is GapSeverity.BLOCKING)

        return UncertaintyReport(
            case_id=case_id,
            open_hypotheses=_count_status(hypotheses, HypothesisStatus.OPEN),
            supported_hypotheses=_count_status(hypotheses, HypothesisStatus.SUPPORTED),
            refuted_hypotheses=_count_status(hypotheses, HypothesisStatus.REFUTED),
            retired_hypotheses=_count_status(hypotheses, HypothesisStatus.RETIRED),
            mean_confidence=(
                sum(confidences) / len(confidences) if confidences else None
            ),
            total_gaps=len(gaps),
            blocking_gaps=blocking,
            is_blocked=blocking > 0,
        )

    def audit_trail(self) -> list[dict[str, Any]]:
        return [dict(entry) for entry in self._audit]

    # -- replay path -----------------------------------------------------

    def restore(self, gaps: Iterable[KnowledgeGap]) -> None:
        """Install already-audited gaps verbatim. Replay only.

        Same reasoning as `models.FactBase.restore`: the gaps are already in
        the case chain, so re-auditing them would duplicate it, and their
        provenance cannot be re-checked because the store they reference is
        itself being rebuilt from the same chain.
        """
        for gap in gaps:
            self._gaps[gap.id] = gap

    # -- internals -------------------------------------------------------

    def _record(self, entry: dict[str, Any]) -> None:
        self._sink(dict(entry))
        self._audit.append(entry)


def _require_same_case(target_case: str, entity_case: str, subject: str) -> None:
    """A gap and everything it names must belong to the same case.

    Cross-case citation is refused for the same reason `entities.FrameStore`
    refuses it: a gap that blocks another dossier's hypothesis is a caller bug.
    """
    if target_case != entity_case:
        raise ValueError(
            f"{subject} belongs to case {target_case!r}, which is a different "
            f"case from {entity_case!r}"
        )


def _count_status(hypotheses: list[Hypothesis], status: HypothesisStatus) -> int:
    return sum(1 for h in hypotheses if h.status is status)
