"""War room dashboard for finding lifecycle visibility.

Contract:
- GET /findings returns findings matching optional filters (case_id,
status, source_kind), sorted by created_at descending.
- status and source_kind are typed as their enums; invalid values
return 422, not an empty list. Silent-empty is a rejected pattern.
- include_superseded=False (default) shows only current findings.
include_superseded=True shows the full history, so the supersession
chain is visible: each superseded row carries superseded_by.
- Pagination: limit (default 500, max 5000), offset (default 0).
`total` is the post-filter count, pre-pagination; len(findings) is
the page size.
- The FactBase is wired into app.state.fact_base. The lifespan refuses
to start when it is not wired — the wiring bug is a startup failure,
not a 424 on the first request. Mirrors the warn-on-noop-sink pattern
in war_room/models.py.

Dependencies: FastAPI, pydantic. No external DB access — reads a FactBase
instance injected by the caller.

Deferred (documented gaps):
- Authentication / authorization. This endpoint has none; `statement`
and `evidence_ids` are returned verbatim. Do not deploy on a public
interface until an auth dependency is added.
- Sorting: only created_at descending is supported. Add a sort query
param when the UI needs more.
- Evidence links: evidence_ids are opaque strings; a hyperlink to the
artifact via EvidenceResolver is a UI concern.
- Cross-case admin view: this endpoint reads a FactBase (case-agnostic
by design) and filters by case_id. Single-case deployments wire one
FactBase; if the store holds multiple cases and you want to forbid
the cross-case view, add require_case_id and 422 when it is missing.
- Response caching / ETag: none. Add when traffic warrants.
"""
from __future__ import annotations
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from fastapi import FastAPI, Query
from pydantic import BaseModel, Field
from dossier_pipeline.war_room.models import (
    FactBase,
    Finding,
    FindingStatus,
    SourceKind,
)


class FindingSummary(BaseModel):
    """A finding's dashboard shape. Fields are typed as the domain enums
    where they are enums, so serialization is a pydantic concern and the
    response shape is enforced, not hand-built."""
    id: str
    case_id: str
    statement: str
    status: FindingStatus
    source_kind: SourceKind
    classifier_concept_id: str | None = None
    authority_id: str | None = None
    evidence_ids: list[str]
    superseded_by: str | None = None
    created_at: datetime


class DashboardResponse(BaseModel):
    findings: list[FindingSummary]
    total: int = Field(
        ...,
        description="Post-filter count, before pagination. "
        "len(findings) is the page size.",
    )
    offset: int
    limit: int
    include_superseded: bool
    filters: dict[str, Any]


def create_dashboard_app(*, factbase: FactBase | None = None) -> FastAPI:
    """Build the war-room dashboard app.

    If `factbase` is provided, it is wired into app.state.fact_base now.
    If not, the caller must set app.state.fact_base before startup. The
    lifespan refuses to start when unwired — a wiring bug should fail
    loudly at startup, not as a 424 on the first request.
    """
    if factbase is not None and not isinstance(factbase, FactBase):
        raise TypeError(
            f"factbase must be a FactBase or None, got "
            f"{type(factbase).__name__}"
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "fact_base", None) is None:
            raise RuntimeError(
                "FactBase not wired. Set app.state.fact_base before "
                "starting the server. This is a wiring bug and should "
                "fail at startup, not as a 424 on the first request."
            )
        yield

    app = FastAPI(
        title="War Room Dashboard",
        description="Finding lifecycle visibility for the war room.",
        version="1.0.0",
        lifespan=lifespan,
    )

    if factbase is not None:
        app.state.fact_base = factbase

    @app.get("/findings", response_model=DashboardResponse)
    def list_findings(
        case_id: str | None = Query(
            None, description="Filter by case ID"
        ),
        status: FindingStatus | None = Query(
            None,
            description=(
                "Filter by finding status. Use the enum's value, e.g. "
                "'proposed'; unknown values return 422."
            ),
        ),
        source_kind: SourceKind | None = Query(
            None,
            description=(
                "Filter by source kind, e.g. 'classifier'. Unknown "
                "values return 422."
            ),
        ),
        include_superseded: bool = Query(
            False,
            description=(
                "Include superseded findings; each row carries "
                "superseded_by so the chain is visible."
            ),
        ),
        limit: int = Query(500, ge=1, le=5000),
        offset: int = Query(0, ge=0),
    ) -> DashboardResponse:
        # Lifespan guarantees fact_base is set.
        fb: FactBase = app.state.fact_base

        items = fb.list(include_superseded=include_superseded)

        if case_id is not None:
            items = [f for f in items if f.case_id == case_id]
        if status is not None:
            items = [f for f in items if f.status == status]
        if source_kind is not None:
            items = [f for f in items if f.source_kind == source_kind]

        # Newest first; stable sort preserves insertion for ties.
        items.sort(key=lambda f: f.created_at, reverse=True)

        total = len(items)
        page = items[offset : offset + limit]

        return DashboardResponse(
            findings=[_to_summary(f) for f in page],
            total=total,
            offset=offset,
            limit=limit,
            include_superseded=include_superseded,
            filters={
                "case_id": case_id,
                "status": status.value if status else None,
                "source_kind": source_kind.value if source_kind else None,
            },
        )

    return app


def _to_summary(f: Finding) -> FindingSummary:
    """Domain-to-DTO mapping in one place, out of the endpoint so the
    endpoint is only about filtering, sorting, and pagination."""
    return FindingSummary(
        id=f.id,
        case_id=f.case_id,
        statement=f.statement,
        status=f.status,
        source_kind=f.source_kind,
        classifier_concept_id=f.classifier_concept_id,
        authority_id=f.authority_id,
        evidence_ids=list(f.evidence_ids),
        superseded_by=f.superseded_by,
        created_at=f.created_at,
    )
