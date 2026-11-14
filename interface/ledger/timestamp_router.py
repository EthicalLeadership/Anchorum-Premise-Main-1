"""FastAPI surface for the local RFC 3161 Trust Engine.

Wire once, in the app factory::

    from interface.ledger.timestamp_router import router as ledger_timestamp_router
    app.include_router(ledger_timestamp_router)

The app must also provide::

    app.state.snapshot_builder: Callable[[str], object]
        Takes a case id and returns an object with .canonical_bytes() -> bytes.
    app.state.tsa_dir: Path, optional   (default: var/tsa)
    app.state.timestamp_dir: Path, optional   (default: var/timestamps)

The route stays air-gapped: it shells out to the local OpenSSL TSA and never
touches the network. That is the difference from the OTS route, which needs an
external calendar server.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from .timestamp import TimestampError, stamp_bytes, verify

router = APIRouter(prefix="/ledger", tags=["ledger"])

SNAPSHOT_FILENAME = "snapshot.alp"
_TSA_MISSING_MARKER = "TSA config not found"


def _timestamp_dir(request: Request, case_id: str) -> Path:
    base = Path(getattr(request.app.state, "timestamp_dir", Path("var/timestamps")))
    return base / case_id


def _tsa_dir(request: Request) -> Path:
    return Path(getattr(request.app.state, "tsa_dir", Path("var/tsa")))


@router.post("/snapshots/{case_id}/timestamp")
def timestamp_snapshot(case_id: str, request: Request):
    """Stamp the case snapshot with a local RFC 3161 timestamp."""
    builder = getattr(request.app.state, "snapshot_builder", None)
    if builder is None:
        raise HTTPException(
            status_code=503,
            detail="snapshot_builder is not configured on app.state",
        )

    snapshot = builder(case_id)
    data = snapshot.canonical_bytes()
    out_dir = _timestamp_dir(request, case_id)

    try:
        tsr_path = stamp_bytes(
            data=data,
            out_dir=out_dir,
            tsa_dir=_tsa_dir(request),
            filename=SNAPSHOT_FILENAME,
        )
    except TimestampError as exc:
        message = str(exc)
        # An unconfigured TSA is an installation problem (503); a TSA that is
        # present but refuses the request is an upstream failure (502).
        status_code = 503 if _TSA_MISSING_MARKER in message else 502
        raise HTTPException(status_code=status_code, detail=message) from exc

    return {
        "case_id": case_id,
        "snapshot_path": str(out_dir / SNAPSHOT_FILENAME),
        "timestamp_path": str(tsr_path),
        "status": "timestamped",
    }


@router.get("/snapshots/{case_id}/timestamp/verify")
def verify_timestamp(case_id: str, request: Request):
    """Re-check an existing timestamp response against its snapshot."""
    out_dir = _timestamp_dir(request, case_id)
    tsr_path = out_dir / (SNAPSHOT_FILENAME + ".tsr")
    snapshot_path = out_dir / SNAPSHOT_FILENAME

    if not tsr_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No timestamp response at {tsr_path}",
        )

    tsa_dir = _tsa_dir(request)
    verified = verify(
        tsr_path=tsr_path,
        data_path=snapshot_path,
        ca_cert_path=tsa_dir / "ca.crt",
        tsa_cert_path=tsa_dir / "tsa.crt",
    )

    return {
        "case_id": case_id,
        "timestamp_path": str(tsr_path),
        "verified": verified,
    }
