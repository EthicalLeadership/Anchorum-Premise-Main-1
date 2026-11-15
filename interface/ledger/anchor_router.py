"""FastAPI surface for Phase 3 OTS anchoring.

Wire once, in the app factory:
    from interface.ledger.anchor_router import router as ledger_anchor_router
    app.include_router(ledger_anchor_router)

The app must also provide:
    app.state.snapshot_builder: Callable[[str], object]
        A function that takes case_id and returns an object with
        .canonical_bytes() -> bytes.
    app.state.anchor_dir: Path, optional (default: var/anchors)

That keeps the route real (it has a writer) without importing a specific
snapshot constructor the router cannot know.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from .anchor import (
    AnchorError,
    AnchorUnavailable,
    stamp_bytes,
    verify,
)

router = APIRouter(prefix="/ledger", tags=["ledger"])

#: OTS needs an external calendar server, so it cannot run on an air-gapped
#: installation. Default is off: the supported proof path is the local RFC 3161
#: timestamp in `timestamp_router`. Set to 1 only where outbound network access
#: is deliberate.
OTS_ENABLE_ENV = "ANCHORUM_OTS_ENABLED"


def _ots_enabled() -> bool:
    return os.getenv(OTS_ENABLE_ENV, "").strip().lower() in {"1", "true", "yes"}


def _anchor_dir(request: Request, case_id: str) -> Path:
    base = Path(getattr(request.app.state, "anchor_dir", Path("var/anchors")))
    return base / case_id


@router.post("/snapshots/{case_id}/anchor")
def anchor_snapshot(case_id: str, request: Request):
    builder = getattr(request.app.state, "snapshot_builder", None)
    if builder is None:
        raise HTTPException(
            status_code=503,
            detail="snapshot_builder is not configured on app.state",
        )

    if not _ots_enabled():
        raise HTTPException(
            status_code=503,
            detail=(
                "OpenTimestamps anchoring is disabled: it requires an external "
                "calendar server and cannot run on an air-gapped deployment. "
                f"Set {OTS_ENABLE_ENV}=1 to enable it, or use "
                "POST /ledger/snapshots/{case_id}/timestamp for the local "
                "RFC 3161 proof, which needs no network."
            ),
        )

    snapshot = builder(case_id)
    data = snapshot.canonical_bytes()

    try:
        result = stamp_bytes(
            data=data,
            out_dir=_anchor_dir(request, case_id),
            filename="snapshot.alp",
        )
    except AnchorUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AnchorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "case_id": case_id,
        "snapshot_path": str(result.snapshot_path),
        "ots_path": str(result.ots_path),
        "status": "stamped",
    }


@router.get("/snapshots/{case_id}/anchor/verify")
def verify_snapshot(case_id: str, request: Request):
    ots_path = _anchor_dir(request, case_id) / "snapshot.alp.ots"
    try:
        result = verify(ots_path)
    except AnchorUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AnchorError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "case_id": case_id,
        "status": result.status,
        "bitcoin_block": result.bitcoin_block,
        "attested_at": result.attested_at,
        "ots_path": str(result.ots_path),
    }
