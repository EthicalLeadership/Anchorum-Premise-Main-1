"""War room fact base and derived entities.

Contract:
  - Every Finding carries at least one evidence_id, all of which must resolve.
  - Every Finding declares where its *rule* came from (source_kind + one of
    classifier_concept_id / authority_id). The two must agree.
  - Findings are immutable after construction; the only mutations are a
    supersession (new row + superseded_by forward) and a status transition
    (update_status). Neither deletes.
  - Every transition reaches the audit sink *before* in-memory state is
    committed. If the sink raises, the transition does not occur — with one
    documented exception in supersede(); see "Recovery from partial failure".

Deferred (documented gaps, closed in 1b):
  - classifier_concept_id / authority_id are shape-checked, not existence-
    checked. Existence validation is a batch operation performed by Lane A
    against the live lexicon/corpus before persisting. Coupling FactBase to
    Engine or the law corpus on construction is the wrong layer.
  - Legal status transitions (e.g., REFUTED -> CORROBORATED) are not enforced
    in 1a. `update_status` accepts any transition between distinct statuses;
    the transition graph is a policy decision that lands with the war-room
    routes in 1b. Until then, callers must not treat a status change as
    policy-validated.
  - `Finding.audit_entry_id` identifies the *creation* audit entry. Status
    changes and supersessions are audited via the FactBase mirror and the
    case audit chain, not by rewriting this field (which is frozen).
  - StrategicFrame, CaseTheory, Hypothesis, Option, Assumption land in 1b.

Recovery from partial failure:
  The only non-atomic path is supersede() when the supersede event's sink
  call fails after add() has already committed the new finding. In-memory
  state is left with two heads: the old finding is not marked superseded,
  and the new finding exists but is not linked from the old. There is no
  in-module recovery — calling supersede(old_id, new_finding) again raises
  `finding id collision` on the new finding. Production must wrap the
  entire derivation run in a DB transaction (the sink's writes are part
  of that transaction) and discard the FactBase on abort.

Threading: FactBase is a single-writer object per derivation run. Do not
share an instance across threads.

Dependencies: pydantic>=2 (model_validator(mode="after"), ConfigDict).
If swapping to @dataclass(frozen=True) + __post_init__, keep evidence_ids
as a tuple — a mutable list breaks the immutability guarantee via in-place
append even when the dataclass itself is frozen.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterable, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FindingStatus(str, Enum):
    PROPOSED = "proposed"
    CORROBORATED = "corroborated"
    CONTESTED = "contested"
    REFUTED = "refuted"


class SourceKind(str, Enum):
    CLASSIFIER = "classifier"   # rule from ccsp.verify.Engine lexicon
    AUTHORITY = "authority"     # rule from a legal authority corpus


class EvidenceResolver(Protocol):
    """Injected dependency. In production, an EvidenceStore adapter.
    In tests, a set. Never imported statically — that is what keeps
    Lane B free of evidence access."""
    def exists(self, evidence_id: str) -> bool: ...


# The sink receives each audit entry (as a copy) and is expected to persist
# it to the case audit chain (AuditLog + HMAC). In tests it is a no-op or
# an appender. A sink that raises aborts the transition.
AuditSink = Callable[[dict[str, Any]], None]


class Finding(BaseModel):
    # frozen=True blocks attribute reassignment (audit integrity);
    # tuple evidence_ids blocks in-place list mutation (the other half).
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: f"fnd_{uuid4().hex[:12]}")
    case_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    status: FindingStatus = FindingStatus.PROPOSED

    # Factual grounding — mandatory; tuple for immutability.
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    # Rule grounding — exactly one citation, matching source_kind.
    # Existence is not checked here; see module docstring "Deferred".
    source_kind: SourceKind
    classifier_concept_id: str | None = None
    authority_id: str | None = None

    # Lifecycle. audit_entry_id is the creation event; see "Deferred".
    derivation_run_id: str | None = None
    superseded_by: str | None = None
    audit_entry_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _citation_matches_source_kind(self) -> "Finding":
        if self.source_kind == SourceKind.CLASSIFIER:
            if not self.classifier_concept_id:
                raise ValueError("source_kind=classifier requires classifier_concept_id")
            if self.authority_id:
                raise ValueError("source_kind=classifier must not set authority_id")
        elif self.source_kind == SourceKind.AUTHORITY:
            if not self.authority_id:
                raise ValueError("source_kind=authority requires authority_id")
            if self.classifier_concept_id:
                raise ValueError("source_kind=authority must not set classifier_concept_id")
        else:
            # Unreachable via normal construction (pydantic rejects bad enum
            # values before mode="after"); fail loudly if the enum gains a
            # member without a validator branch.
            raise ValueError(f"unknown source_kind: {self.source_kind!r}")
        return self
class FactBase:
    """The one store findings write to. Supersession and status changes are
    the only mutations; nothing is ever deleted.

    The in-memory `_audit` list is a local mirror for tests and immediate
    inspection. The *case* audit chain is written via `audit_sink`. A
    finding is not considered persisted until the sink has accepted its
    audit entry. The mirror is authoritative for its own contents — the
    sink receives copies and cannot corrupt it.
    """

    def __init__(
        self,
        resolver: EvidenceResolver,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self._resolver = resolver
        self._sink: AuditSink = audit_sink or (lambda _entry: None)
        self._findings: dict[str, Finding] = {}
        self._audit: list[dict[str, Any]] = []

    # -- write paths -----------------------------------------------------

    def add(self, finding: Finding) -> Finding:
        self._validate_for_add(finding)
        audit_id = f"aud_{uuid4().hex[:12]}"
        stored = finding.model_copy(update={"audit_entry_id": audit_id})
        # The payload is the record, not a pointer to it. `replay` rebuilds the
        # store from these entries alone, so an entry carrying only an id would
        # let a restart lose every statement and every citation while the chain
        # still claimed the work had happened.
        self._record({
            "audit_entry_id": audit_id,
            "action": "finding_created",
            "finding_id": stored.id,
            "case_id": stored.case_id,
            "derivation_run_id": stored.derivation_run_id,
            "statement": stored.statement,
            "status": stored.status.value,
            "evidence_ids": list(stored.evidence_ids),
            "source_kind": stored.source_kind.value,
            "classifier_concept_id": stored.classifier_concept_id,
            "authority_id": stored.authority_id,
            "created_at": stored.created_at.isoformat(),
        })
        # Only reachable if _record returned without raising.
        self._findings[stored.id] = stored
        return stored

    def supersede(self, old_id: str, new_finding: Finding) -> tuple[Finding, Finding]:
        old = self._findings.get(old_id)
        if old is None:
            raise KeyError(old_id)
        if old.superseded_by:
            raise ValueError(f"{old_id} already superseded by {old.superseded_by}")

        # add() validates and commits finding_created for the new row.
        # If it raises, old is untouched and no supersede event has fired.
        # If the *supersede* _record raises after add() returns, the state
        # is left with two heads — see "Recovery from partial failure".
        stored = self.add(new_finding)

        updated_old = old.model_copy(update={"superseded_by": stored.id})
        self._record({
            "audit_entry_id": f"aud_{uuid4().hex[:12]}",
            "action": "finding_superseded",
            "old_id": old_id,
            "new_id": stored.id,
            "case_id": updated_old.case_id,
        })
        self._findings[old_id] = updated_old
        return updated_old, stored

    def update_status(self, finding_id: str, new_status: FindingStatus) -> Finding:
        # Reject str early: model_copy would accept it, then _record would
        # fail on new_status.value, after the point of a clean failure.
        if not isinstance(new_status, FindingStatus):
            raise TypeError(
                f"new_status must be a FindingStatus, got {type(new_status).__name__}"
            )
        f = self._findings.get(finding_id)
        if f is None:
            raise KeyError(finding_id)
        if f.superseded_by:
            raise ValueError(f"{finding_id} is superseded; cannot update status")
        # Same-status updates are audit noise on a system whose audit is
        # the point. See docstring "Deferred" for the transition graph.
        if f.status == new_status:
            raise ValueError(f"{finding_id} status already {new_status.value}")

        updated = f.model_copy(update={"status": new_status})
        self._record({
            "audit_entry_id": f"aud_{uuid4().hex[:12]}",
            "action": "finding_status_changed",
            "finding_id": finding_id,
            "from": f.status.value,
            "to": new_status.value,
            "case_id": f.case_id,
        })
        self._findings[finding_id] = updated
        return updated

    # -- read paths ------------------------------------------------------

    def get(self, finding_id: str) -> Finding:
        return self._findings[finding_id]

    def list(self, include_superseded: bool = False) -> list[Finding]:
        items = list(self._findings.values())
        if not include_superseded:
            items = [f for f in items if not f.superseded_by]
        return items

    def audit_trail(self) -> list[dict[str, Any]]:
        # Defensive copy: callers must not be able to mutate internal audit
        # state by editing the returned dicts.
        return [dict(e) for e in self._audit]

    # -- replay path -----------------------------------------------------

    def restore(self, findings: Iterable[Finding]) -> None:
        """Install already-audited findings verbatim. Replay only.

        Bypasses validation and the sink, for two reasons. Every row passed
        here is already in the case chain, so writing it again would duplicate
        the chain; and `_validate_for_add` rejects a preset `audit_entry_id`,
        which is exactly what a restored row must carry — the id of the
        creation event that produced it.

        Callers are responsible for passing findings whose `status` and
        `superseded_by` already reflect the end state of the chain. This is
        the inverse of `add`/`supersede`/`update_status`, not an alternative
        to them.
        """
        for finding in findings:
            self._findings[finding.id] = finding

    # Deliberately no delete(). Findings are append-only history.

    # -- internals -------------------------------------------------------

    def _validate_for_add(self, finding: Finding) -> None:
        # audit_entry_id is assigned by FactBase; a pre-set value means the
        # caller tried to forge or reuse an audit row.
        if finding.audit_entry_id is not None:
            raise ValueError("audit_entry_id is assigned by FactBase; do not set it")
        # A pre-set superseded_by would hide the row from list() with no
        # corresponding finding_superseded event — replay would diverge.
        if finding.superseded_by is not None:
            raise ValueError("cannot add a finding with superseded_by set; use supersede()")
        for eid in finding.evidence_ids:
            if not self._resolver.exists(eid):
                raise ValueError(f"unknown evidence_id: {eid}")
        if finding.id in self._findings:
            raise ValueError(f"finding id collision: {finding.id}")

    def _record(self, entry: dict[str, Any]) -> None:
        """Deliver to the sink before appending to the in-memory mirror.

        If the sink raises, this method does not append and the caller's
        subsequent state commit does not occur. For supersede(), add() has
        already committed the new finding before the supersede event
        reaches this method — if the supersede _record raises, the FactBase
        is left with two heads. See the module docstring "Recovery from
        partial failure" for the correct response; there is no in-module
        recovery.

        The sink receives a shallow copy so it cannot mutate the internal
        mirror. The mirror is authoritative for its own contents.
        """
        self._sink(dict(entry))
        self._audit.append(entry)
