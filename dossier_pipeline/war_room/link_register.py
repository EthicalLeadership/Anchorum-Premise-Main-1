"""Typed links between findings.

The fact base holds findings; almost every argument about a case is about how
they bear on each other. This module records that, with the same discipline as
the stores it sits beside: append-only, audited before commit, no delete.

Contract:
  - Both endpoints must exist in the fact base and belong to the link's case.
  - A finding cannot link to itself.
  - `DEPENDS_ON` is acyclic. A dependency ring means no member can be
    established first, so the case cannot be built from it; refusing the edge at
    write time beats discovering the ring mid-argument.
  - `SUPPORTS`, `CONTRADICTS` and `DUPLICATES` may be mutual. Two findings can
    corroborate each other; two findings can be irreconcilable both ways.
  - Exact duplicates are refused. Re-recording the same kind in the same
    direction adds nothing and inflates any count taken over the register.

Deferred:
  - Only `DEPENDS_ON` is acyclicity-checked. A cycle of `SUPPORTS` edges is
    legal and can be circular reasoning in practice, but detecting that is a
    judgement about content, not about graph shape, and this module does not
    make it.
  - Transitive closure is computed on demand for cycle checks and is not
    cached; the registers here are per-case and small.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Iterable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dossier_pipeline.war_room.models import AuditSink, FactBase


class LinkKind(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    DEPENDS_ON = "depends_on"
    DUPLICATES = "duplicates"


class FindingLink(BaseModel):
    """A directed, typed, justified relation between two findings."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: f"lnk_{uuid4().hex[:12]}")
    case_id: str = Field(min_length=1)
    kind: LinkKind
    source_finding_id: str = Field(min_length=1)
    target_finding_id: str = Field(min_length=1)
    #: Why this link holds. A link with no reason cannot be reviewed.
    rationale: str = Field(min_length=1)
    audit_entry_id: str | None = None

    @model_validator(mode="after")
    def _no_self_link(self) -> "FindingLink":
        if self.source_finding_id == self.target_finding_id:
            raise ValueError("a finding cannot link to itself")
        return self


class LinkRegister:
    """Append-only register of finding links for one derivation run."""

    def __init__(self, factbase: FactBase, audit_sink: AuditSink | None = None) -> None:
        self._factbase = factbase
        self._sink: AuditSink = audit_sink or (lambda _entry: None)
        self._links: dict[str, FindingLink] = {}
        self._audit: list[dict[str, Any]] = []

    # -- write path ------------------------------------------------------

    def add_link(self, link: FindingLink) -> FindingLink:
        if link.audit_entry_id is not None:
            raise ValueError("audit_entry_id is assigned by LinkRegister; do not set it")
        if link.id in self._links:
            raise ValueError(f"link id collision: {link.id}")

        self._require_endpoint(link.source_finding_id, link.case_id, "source")
        self._require_endpoint(link.target_finding_id, link.case_id, "target")

        if self._is_duplicate(link):
            raise ValueError(
                f"duplicate link: {link.kind.value} "
                f"{link.source_finding_id} -> {link.target_finding_id}"
            )

        if link.kind is LinkKind.DEPENDS_ON and self._reaches(
            link.target_finding_id, link.source_finding_id
        ):
            raise ValueError(
                f"dependency cycle: {link.target_finding_id} already depends on "
                f"{link.source_finding_id}"
            )

        audit_id = f"aud_{uuid4().hex[:12]}"
        self._record(
            {
                "audit_entry_id": audit_id,
                "action": "finding_link_created",
                "link_id": link.id,
                "case_id": link.case_id,
                "kind": link.kind.value,
                "source_finding_id": link.source_finding_id,
                "target_finding_id": link.target_finding_id,
                "rationale": link.rationale,
            }
        )
        stored = link.model_copy(update={"audit_entry_id": audit_id})
        self._links[stored.id] = stored
        return stored

    # -- read paths ------------------------------------------------------

    def links_for_case(self, case_id: str) -> list[FindingLink]:
        return [link for link in self._links.values() if link.case_id == case_id]

    def links_between(self, first_id: str, second_id: str) -> list[FindingLink]:
        """Either direction — the register stores direction, callers ask by pair."""
        return [
            link
            for link in self._links.values()
            if {link.source_finding_id, link.target_finding_id} == {first_id, second_id}
        ]

    def contradictions_for(self, finding_id: str) -> list[FindingLink]:
        return [
            link
            for link in self._links.values()
            if link.kind is LinkKind.CONTRADICTS
            and finding_id in (link.source_finding_id, link.target_finding_id)
        ]

    def audit_trail(self) -> list[dict[str, Any]]:
        return [dict(entry) for entry in self._audit]

    # -- replay path -----------------------------------------------------

    def restore(self, links: Iterable[FindingLink]) -> None:
        """Install already-audited links verbatim. Replay only.

        Same reasoning as `models.FactBase.restore`: the links are already in
        the case chain, so re-auditing them would duplicate it, and the
        endpoint/cycle checks cannot be re-run because the fact base they
        reference is itself being rebuilt from the same chain.
        """
        for link in links:
            self._links[link.id] = link

    # -- internals -------------------------------------------------------

    def _require_endpoint(self, finding_id: str, case_id: str, role: str) -> None:
        try:
            finding = self._factbase.get(finding_id)
        except KeyError:
            raise ValueError(f"unknown finding: {finding_id}") from None
        if finding.case_id != case_id:
            raise ValueError(
                f"{role} finding {finding_id} belongs to case {finding.case_id!r}, "
                f"which is a different case from {case_id!r}"
            )

    def _is_duplicate(self, candidate: FindingLink) -> bool:
        return any(
            existing.case_id == candidate.case_id
            and existing.kind is candidate.kind
            and existing.source_finding_id == candidate.source_finding_id
            and existing.target_finding_id == candidate.target_finding_id
            for existing in self._links.values()
        )

    def _reaches(self, start_id: str, target_id: str) -> bool:
        """True if `target_id` is reachable from `start_id` following DEPENDS_ON."""
        adjacency: dict[str, list[str]] = {}
        for link in self._links.values():
            if link.kind is LinkKind.DEPENDS_ON:
                adjacency.setdefault(link.source_finding_id, []).append(
                    link.target_finding_id
                )

        seen: set[str] = set()
        stack = [start_id]
        while stack:
            current = stack.pop()
            if current == target_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(adjacency.get(current, ()))
        return False

    def _record(self, entry: dict[str, Any]) -> None:
        self._sink(dict(entry))
        self._audit.append(entry)
