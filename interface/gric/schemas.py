"""GRIC boundary schemas.

Canonical runtime types are IMPORTED, not mirrored. See INTERFACE_AUDIT.md
section 3. Mirroring invites the F-09d bug into the interface layer.

Only interface-specific types are defined here:

  - request/response bodies for POST /project
  - view models for /manifest
  - typed row for the /gric diff table

If dossier_pipeline.contracts changes, the re-exports below will raise
ImportError at module load. That is intentional: fail loudly, not silently.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# --- canonical (re-exported, not redefined) ---------------------------------
from dossier_pipeline.contracts import (  # noqa: F401
    PipelineResult,
    ResultStatus,
    ErrorEvent,
)

__all__ = [
    "PipelineResult",
    "ResultStatus",
    "ErrorEvent",
    "ProjectionRequest",
    "ProjectionResponse",
    "ManifestEntry",
    "GricDiffRow",
]


class ProjectionRequest(BaseModel):
    """POST /project body."""
    text: str = Field(..., min_length=1, max_length=200_000)
    vertical: str = Field(default="legal", min_length=1, max_length=64)


class ProjectionResponse(BaseModel):
    """Flattened view of the ccsp projection object.

    ccsp.verify returns an object with these fields, some of which are not
    JSON-serializable by default:

      mappingproxy       -> dict
      frozenset          -> sorted list
      tuple              -> list

    This model is the serialization contract. If ccsp adds a field, this
    model must be updated in the same commit. See INTERFACE_AUDIT section 5.
    """
    concept_id: str | None = None
    canonical_text: str = ""
    semantic_hash: str = ""
    classification: str = ""
    admissible: bool = False
    confidence_int: int = 0
    confidence_calibration: str = "unknown"
    evidence: list[str] = Field(default_factory=list)
    alternates: list[str] = Field(default_factory=list)
    concept_distribution: dict[str, int] = Field(default_factory=dict)
    matched_entries: list[str] = Field(default_factory=list)
    candidate_count: int = 0
    admissible_count: int = 0
    forbidden_concept_count: int = 0
    below_confidence_count: int = 0
    unmapped_count: int = 0
    rejected_count: int = 0
    fallback_reason: str | None = None
    engine_version: str = ""
    config_hash: str = ""
    rules_hash: str = ""
    vertical_scope: list[str] = Field(default_factory=list)

    @classmethod
    def from_projection(cls, proj: Any) -> "ProjectionResponse":
        """Convert a ccsp projection object into a JSON-safe model.

        Uses getattr with defaults so a ccsp version that adds fields does
        not break the interface; a ccsp version that REMOVES fields this
        model requires will surface via the defaults, not an exception.
        """
        def _list(v: Any) -> list[str]:
            if v is None:
                return []
            try:
                return [str(x) for x in v]
            except TypeError:
                return [str(v)]

        return cls(
            concept_id=getattr(proj, "concept_id", None),
            canonical_text=getattr(proj, "canonical_text", "") or "",
            semantic_hash=getattr(proj, "semantic_hash", "") or "",
            classification=getattr(proj, "classification", "") or "",
            admissible=bool(getattr(proj, "admissible", False)),
            confidence_int=int(getattr(proj, "confidence_int", 0)),
            confidence_calibration=getattr(proj, "confidence_calibration", "unknown") or "unknown",
            evidence=_list(getattr(proj, "evidence", ())),
            alternates=_list(getattr(proj, "alternates", ())),
            concept_distribution=dict(getattr(proj, "concept_distribution", {}) or {}),
            matched_entries=_list(getattr(proj, "matched_entries", ())),
            candidate_count=int(getattr(proj, "candidate_count", 0)),
            admissible_count=int(getattr(proj, "admissible_count", 0)),
            forbidden_concept_count=int(getattr(proj, "forbidden_concept_count", 0)),
            below_confidence_count=int(getattr(proj, "below_confidence_count", 0)),
            unmapped_count=int(getattr(proj, "unmapped_count", 0)),
            rejected_count=int(getattr(proj, "rejected_count", 0)),
            fallback_reason=getattr(proj, "fallback_reason", None),
            engine_version=getattr(proj, "engine_version", "") or "",
            config_hash=getattr(proj, "config_hash", "") or "",
            rules_hash=getattr(proj, "rules_hash", "") or "",
            vertical_scope=sorted(str(s) for s in (getattr(proj, "vertical_scope", frozenset()) or frozenset())),
        )


class ManifestEntry(BaseModel):
    """One row of tests/fixtures/MANIFEST.sha256, resolved against disk."""
    path: str
    expected_hash: str
    actual_hash: str | None = None
    status: str  # "ok" | "missing" | "mismatch"
    size_bytes: int | None = None


class GricDiffRow(BaseModel):
    """One row of the /gric drift table."""
    field: str
    v1_0: str
    v1_1: str
    contracts_has: str
    status: str  # "aligned" | "drift" | "scheduled" | "removed"
