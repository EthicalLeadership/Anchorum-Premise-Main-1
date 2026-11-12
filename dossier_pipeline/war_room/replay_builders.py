"""Turn case-audit rows back into war-room entities.

The stores in this package are in-memory; the durable record is the case audit
chain. This module owns the one direction that is not covered anywhere else:
reading a row back into the entity that wrote it. `replay` composes these.

Contract:
  - A builder reads only the row it is given. Every field the entity needs must
    therefore be in the payload — an id-only entry cannot be rebuilt, and the
    builders fail rather than invent a value.
  - A *missing* field on a known action is corruption, and raises. A *unknown*
    action is ordinary forward compatibility, and the callers skip it. The two
    are deliberately different: guessing at a damaged row is how a replay
    silently produces a case that never happened.
  - `created_at` is optional in the row. When it is absent the entity takes its
    own default, which is the honest answer — the row predates the field, so
    the real timestamp is unknown, not equal to replay time.
  - Folding the chain (status changes, supersessions) is the caller's job. A
    builder builds one row; it never looks at its neighbours.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from dossier_pipeline.war_room.entities import (
    Assumption,
    CaseTheory,
    Hypothesis,
    HypothesisStatus,
    Option,
    StrategicFrame,
)
from dossier_pipeline.war_room.link_register import FindingLink, LinkKind
from dossier_pipeline.war_room.models import Finding, FindingStatus, SourceKind
from dossier_pipeline.war_room.uncertainty import GapSeverity, KnowledgeGap

# -- action names --------------------------------------------------------
# Mirrors of the literals the stores put in their audit entries. Named here so
# a typo is a NameError rather than a silently skipped action.

ACTION_FINDING_CREATED = "finding_created"
ACTION_FINDING_STATUS_CHANGED = "finding_status_changed"
ACTION_FINDING_SUPERSEDED = "finding_superseded"

ACTION_HYPOTHESIS_CREATED = "hypothesis_created"
ACTION_HYPOTHESIS_STATUS_CHANGED = "hypothesis_status_changed"
ACTION_HYPOTHESIS_SUPERSEDED = "hypothesis_superseded"
ACTION_ASSUMPTION_CREATED = "assumption_created"
ACTION_OPTION_CREATED = "option_created"
ACTION_THEORY_CREATED = "theory_created"
ACTION_FRAME_CREATED = "frame_created"

ACTION_GAP_RECORDED = "knowledge_gap_recorded"
ACTION_LINK_CREATED = "finding_link_created"

FACT_BASE_ACTIONS: frozenset[str] = frozenset(
    {ACTION_FINDING_CREATED, ACTION_FINDING_STATUS_CHANGED, ACTION_FINDING_SUPERSEDED}
)

FRAME_ACTIONS: frozenset[str] = frozenset(
    {
        ACTION_HYPOTHESIS_CREATED,
        ACTION_HYPOTHESIS_STATUS_CHANGED,
        ACTION_HYPOTHESIS_SUPERSEDED,
        ACTION_ASSUMPTION_CREATED,
        ACTION_OPTION_CREATED,
        ACTION_THEORY_CREATED,
        ACTION_FRAME_CREATED,
    }
)

UNCERTAINTY_ACTIONS: frozenset[str] = frozenset({ACTION_GAP_RECORDED})
LINK_ACTIONS: frozenset[str] = frozenset({ACTION_LINK_CREATED})

#: Everything this build can rebuild. Anything else is skipped and reported.
KNOWN_ACTIONS: frozenset[str] = (
    FACT_BASE_ACTIONS | FRAME_ACTIONS | UNCERTAINTY_ACTIONS | LINK_ACTIONS
)


def action_of(entry: dict[str, Any]) -> str:
    """The row's action name, or a marker that cannot collide with a real one."""
    action = entry.get("action")
    return action if isinstance(action, str) else "<missing>"


# -- timestamp -----------------------------------------------------------


def _timestamps(payload: dict[str, Any]) -> dict[str, Any]:
    """`created_at` as a kwarg, or nothing at all when the row predates it."""
    raw = payload.get("created_at")
    if raw is None:
        return {}
    return {"created_at": datetime.fromisoformat(raw)}


# -- fact base -----------------------------------------------------------


def build_finding(
    payload: dict[str, Any],
    *,
    status: FindingStatus | None = None,
    superseded_by: str | None = None,
) -> Finding:
    """Rebuild one finding, optionally carrying a folded end state."""
    return Finding(
        id=payload["finding_id"],
        case_id=payload["case_id"],
        statement=payload["statement"],
        status=status or FindingStatus(payload["status"]),
        evidence_ids=tuple(payload["evidence_ids"]),
        source_kind=SourceKind(payload["source_kind"]),
        classifier_concept_id=payload.get("classifier_concept_id"),
        authority_id=payload.get("authority_id"),
        derivation_run_id=payload.get("derivation_run_id"),
        superseded_by=superseded_by,
        audit_entry_id=payload.get("audit_entry_id"),
        **_timestamps(payload),
    )


# -- theory layer --------------------------------------------------------


def build_hypothesis(
    payload: dict[str, Any],
    *,
    status: HypothesisStatus | None = None,
    superseded_by: str | None = None,
) -> Hypothesis:
    return Hypothesis(
        id=payload["hypothesis_id"],
        case_id=payload["case_id"],
        statement=payload["statement"],
        supports=tuple(payload["supports"]),
        status=status or HypothesisStatus(payload["status"]),
        confidence=payload.get("confidence"),
        superseded_by=superseded_by,
        audit_entry_id=payload.get("audit_entry_id"),
        **_timestamps(payload),
    )


def build_assumption(payload: dict[str, Any]) -> Assumption:
    return Assumption(
        id=payload["assumption_id"],
        case_id=payload["case_id"],
        statement=payload["statement"],
        risk_level=payload["risk_level"],
        rests_on=tuple(payload.get("rests_on", ())),
        audit_entry_id=payload.get("audit_entry_id"),
        **_timestamps(payload),
    )


def build_option(payload: dict[str, Any]) -> Option:
    return Option(
        id=payload["option_id"],
        case_id=payload["case_id"],
        name=payload["name"],
        description=payload.get("description", ""),
        feasibility=payload["feasibility"],
        impact=payload["impact"],
        advances=tuple(payload.get("advances", ())),
        audit_entry_id=payload.get("audit_entry_id"),
        **_timestamps(payload),
    )


def build_theory(payload: dict[str, Any]) -> CaseTheory:
    return CaseTheory(
        id=payload["theory_id"],
        case_id=payload["case_id"],
        title=payload["title"],
        summary=payload.get("summary", ""),
        hypothesis_ids=tuple(payload["hypothesis_ids"]),
        option_ids=tuple(payload.get("option_ids", ())),
        assumption_ids=tuple(payload.get("assumption_ids", ())),
        audit_entry_id=payload.get("audit_entry_id"),
        **_timestamps(payload),
    )


def build_frame(payload: dict[str, Any]) -> StrategicFrame:
    return StrategicFrame(
        id=payload["frame_id"],
        case_id=payload["case_id"],
        objective=payload["objective"],
        theory_ids=tuple(payload["theory_ids"]),
        audit_entry_id=payload.get("audit_entry_id"),
        **_timestamps(payload),
    )


# -- uncertainty and links -----------------------------------------------


def build_gap(payload: dict[str, Any]) -> KnowledgeGap:
    return KnowledgeGap(
        id=payload["gap_id"],
        case_id=payload["case_id"],
        description=payload["description"],
        severity=GapSeverity(payload["severity"]),
        blocks=tuple(payload.get("blocks", ())),
        rests_on=tuple(payload.get("rests_on", ())),
        audit_entry_id=payload.get("audit_entry_id"),
    )


def build_link(payload: dict[str, Any]) -> FindingLink:
    return FindingLink(
        id=payload["link_id"],
        case_id=payload["case_id"],
        kind=LinkKind(payload["kind"]),
        source_finding_id=payload["source_finding_id"],
        target_finding_id=payload["target_finding_id"],
        rationale=payload["rationale"],
        audit_entry_id=payload.get("audit_entry_id"),
    )
