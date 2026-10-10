"""Governed decision flow.

Runs the full governed pipeline:
    projections -> policy decision -> audit entry -> trace record

Guarantees:
  * Audit is fail-closed. If the audit entry cannot be written, no decision
    is returned. The audit log is the authoritative record.
  * Trace is fail-open. If the trace record cannot be written, the decision
    is still returned with trace_id=None and a stderr log. The trace is an
    index into the audit log, not the source of truth.
  * If a registry is provided, config_hash must exist in it. Unsigned or
    unknown configs are refused before any write.

The engine and policy are duck-typed:

    engine.project(candidates) -> object with at least:
        .semantic_hash : str
        .classification : str
        .admissible : bool

    policy.decide(fields, *, now) -> object with at least:
        .route, .reason, .severity, .citation, .rule_id, .evaluated_at
        Optional: .fields_used, .rule_errors
"""
from __future__ import annotations

import sys
from types import MappingProxyType
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Protocol, Sequence

from dossier_pipeline.registry.audit import AuditLog
from dossier_pipeline.registry.trace import TraceLog, TraceRecord


class GovernedDecisionError(Exception):
    """Raised when a governed decision cannot be completed."""


class ProjectionLike(Protocol):
    semantic_hash: str
    classification: str
    admissible: bool


class EngineLike(Protocol):
    def project(self, candidates) -> ProjectionLike: ...


class PolicyLike(Protocol):
    def decide(self, fields: dict, *, now: int): ...


@dataclass(frozen=True)
class GovernedDecision:
    decision: Any
    projections: tuple
    vertical_id: str
    config_hash: str
    audit_seq: int
    trace_id: Optional[str]


def _log(msg: str) -> None:
    print(f"governance: {msg}", file=sys.stderr)


_PROJECTION_FIELDS = (
    "semantic_hash",
    "classification",
    "admissible",
    "concept_id",
    "canonical_text",
    "confidence_int",
    "confidence_calibration",
    "fallback_reason",
    "engine_version",
    "config_hash",
    "rules_hash",
    "evidence",
    "candidate_count",
    "admissible_count",
    "forbidden_concept_count",
    "below_confidence_count",
    "unmapped_count",
    "rejected_count",
)


def _projection_to_dict(p) -> dict:
    """Serialize a projection for the audit record.

    Duck-typed: only fields named in _PROJECTION_FIELDS are included.
    Recursively serializes dataclasses, tuples, sets, and nested
    mappings so the result is JSON-safe. EvidenceRef and any other
    frozen dataclass become a plain dict.
    """
    out = {}
    for name in _PROJECTION_FIELDS:
        if not hasattr(p, name):
            continue
        out[name] = _serialize_projection_value(getattr(p, name))
    return out


def _serialize_projection_value(v):
    """Recursively convert anything projection-shaped into JSON-safe form.

    Handles frozen dataclasses (EvidenceRef, etc.), Mappings, lists,
    tuples, sets, and any object exposing __dict__. Primitives pass
    through untouched. Fail-soft: unknown types are returned as-is so
    that a future evidence type does not silently break the audit path.
    """
    if v is None or isinstance(v, (str, int, float, bool, bytes)):
        return v
    if hasattr(v, "__dataclass_fields__"):
        return {f: _serialize_projection_value(getattr(v, f))
                for f in v.__dataclass_fields__}
    if isinstance(v, Mapping):
        return {k: _serialize_projection_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_serialize_projection_value(x) for x in v]
    if isinstance(v, (set, frozenset)):
        return sorted(_serialize_projection_value(x) for x in v)
    if hasattr(v, "__dict__"):
        return {k: _serialize_projection_value(x) for k, x in vars(v).items()}
    return v



class GovernedDecisionFlow:
    def __init__(
        self,
        *,
        engine: EngineLike,
        policy: PolicyLike,
        audit: AuditLog,
        trace: TraceLog,
        vertical_id: str,
        config_hash: str,
        registry=None,
        allow_unregistered: bool = False,
    ) -> None:
        if not vertical_id:
            raise GovernedDecisionError("vertical_id must be non-empty")
        if not config_hash or len(config_hash) != 64:
            raise GovernedDecisionError(
                "config_hash must be a 64-char hex digest"
            )
        self._engine = engine
        self._policy = policy
        self._audit = audit
        self._trace = trace
        self._vertical_id = vertical_id
        self._config_hash = config_hash
        self._registry = registry
        if registry is None:
            if not allow_unregistered:
                raise GovernedDecisionError(
                    "registry is required; pass allow_unregistered=True to opt out"
                )
            _log("registry not provided; ungoverned mode (allow_unregistered=True)")
        self._require_registered()

    @property
    def vertical_id(self) -> str:
        return self._vertical_id

    @property
    def config_hash(self) -> str:
        return self._config_hash

    def _require_registered(self) -> None:
        """G3: verify config_hash is registered. Called at construction and at
        decide() time, because the registry can change between them."""
        if self._registry is None:
            return
        try:
            self._registry.get(self._config_hash)
        except Exception as exc:
            raise GovernedDecisionError(
                f"config_hash not in registry: {type(exc).__name__}: {exc}"
            ) from exc

    def decide(
        self,
        candidate_sets: Sequence[Iterable],
        fields: dict,
        *,
        now: int,
    ) -> GovernedDecision:
        if not candidate_sets:
            raise GovernedDecisionError("candidate_sets must be non-empty")

        # G5: snapshot then freeze. The policy sees a read-only view;
        # the audit record sees the same snapshot. Caller mutations
        # after this point cannot alter either.
        fields_snapshot = dict(fields)
        frozen_fields = MappingProxyType(fields_snapshot)

        self._require_registered()

        # 1. Projections
        projections = tuple(
            self._engine.project(c) for c in candidate_sets
        )
        projection_ids = tuple(p.semantic_hash for p in projections)

        # 2. Policy decision
        decision = self._policy.decide(frozen_fields, now=now)

        decision_dict = {
            "route": decision.route,
            "reason": decision.reason,
            "severity": decision.severity,
            "citation": getattr(decision, "citation", ""),
            "rule_id": getattr(decision, "rule_id", ""),
            "evaluated_at": getattr(decision, "evaluated_at", now),
            "fields_used": list(getattr(decision, "fields_used", ()) or ()),
            "rule_errors": list(getattr(decision, "rule_errors", ()) or ()),
        }

        # 3. Audit -- fail-closed
        audit_record = {
            "vertical_id": self._vertical_id,
            "config_hash": self._config_hash,
            "projection_ids": list(projection_ids),
            "fields": fields_snapshot,  # G1/G5
            "projections": [_projection_to_dict(p) for p in projections],  # G2
            "decision": decision_dict,
        }
        try:
            audit_entry = self._audit.append(audit_record)
        except Exception as exc:
            raise GovernedDecisionError(
                f"audit write failed: {type(exc).__name__}: {exc}"
            ) from exc

        # 4. Trace -- fail-open
        trace_id: Optional[str] = None
        try:
            trace_rec = TraceRecord.build(
                vertical_id=self._vertical_id,
                projection_ids=projection_ids,
                decision=decision_dict,
                config_hash=self._config_hash,
                audit_seq=audit_entry.seq,
            )
            self._trace.append(trace_rec)
            trace_id = trace_rec.trace_id
        except Exception as exc:
            _log(
                f"trace write failed for audit_seq={audit_entry.seq}: "
                f"{type(exc).__name__}: {exc}"
            )

        return GovernedDecision(
            decision=decision,
            projections=projections,
            vertical_id=self._vertical_id,
            config_hash=self._config_hash,
            audit_seq=audit_entry.seq,
            trace_id=trace_id,
        )
