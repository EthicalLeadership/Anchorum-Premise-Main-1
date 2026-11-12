"""HTTP contract tests for interface/ledger/anchor_router.py — Phase 3.

Proves the route:
  * requires snapshot_builder on app.state (503 if unset)
  * writes snapshot.alp + .ots under app.state.anchor_dir via stamp_bytes
  * returns 503 when the ots CLI is unavailable
  * returns 502 when ots fails
  * proxies verify() results (confirmed / 404 missing)
No real ots binary or network needed.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from interface.ledger.anchor import AnchorError, AnchorResult, AnchorUnavailable, VerifyResult
from interface.ledger.anchor_router import router as ledger_anchor_router


class _FakeSnapshot:
    def __init__(self, data: bytes):
        self._data = data

    def canonical_bytes(self) -> bytes:
        return self._data


def _make_client(anchor_dir: Path, builder=None):
    app = FastAPI()
    app.include_router(ledger_anchor_router)
    app.state.anchor_dir = anchor_dir
    if builder is not None:
        app.state.snapshot_builder = builder
    return TestClient(app)


def test_anchor_requires_builder(tmp_path):
    client = _make_client(tmp_path, builder=None)
    r = client.post("/ledger/snapshots/c-1/anchor")
    assert r.status_code == 503
    assert "snapshot_builder" in r.json()["detail"]


def test_anchor_stamps_snapshot(tmp_path, monkeypatch):
    from interface.ledger import anchor_router as mod

    def fake_stamp(data, out_dir, filename):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        snap = out_dir / filename
        ots = out_dir / (filename + ".ots")
        snap.write_bytes(data)
        ots.write_bytes(b"fake-proof")
        return AnchorResult(
            snapshot_path=snap, ots_path=ots, stdout="stamped", stderr=""
        )

    monkeypatch.setattr(mod, "stamp_bytes", fake_stamp)

    client = _make_client(
        tmp_path, builder=lambda case_id: _FakeSnapshot(b'{"case":"c-1"}')
    )
    r = client.post("/ledger/snapshots/c-1/anchor")

    assert r.status_code == 200
    body = r.json()
    assert body["case_id"] == "c-1"
    assert body["status"] == "stamped"
    assert body["snapshot_path"].endswith("snapshot.alp")
    assert body["ots_path"].endswith("snapshot.alp.ots")

    # Files actually landed under app.state.anchor_dir / case_id
    written = tmp_path / "c-1" / "snapshot.alp"
    assert written.read_bytes() == b'{"case":"c-1"}'
    assert (tmp_path / "c-1" / "snapshot.alp.ots").read_bytes() == b"fake-proof"


def test_anchor_returns_503_when_ots_missing(tmp_path, monkeypatch):
    from interface.ledger import anchor_router as mod

    def fake_stamp(*args, **kwargs):
        raise AnchorUnavailable("ots CLI not installed")

    monkeypatch.setattr(mod, "stamp_bytes", fake_stamp)

    client = _make_client(tmp_path, builder=lambda c: _FakeSnapshot(b"x"))
    r = client.post("/ledger/snapshots/c-1/anchor")

    assert r.status_code == 503
    assert "ots CLI not installed" in r.json()["detail"]


def test_anchor_returns_502_on_anchor_error(tmp_path, monkeypatch):
    from interface.ledger import anchor_router as mod

    def fake_stamp(*args, **kwargs):
        raise AnchorError("calendar unreachable")

    monkeypatch.setattr(mod, "stamp_bytes", fake_stamp)

    client = _make_client(tmp_path, builder=lambda c: _FakeSnapshot(b"x"))
    r = client.post("/ledger/snapshots/c-1/anchor")

    assert r.status_code == 502
    assert "calendar unreachable" in r.json()["detail"]


def test_verify_returns_confirmed(tmp_path, monkeypatch):
    from interface.ledger import anchor_router as mod

    case_dir = tmp_path / "c-1"
    case_dir.mkdir()
    (case_dir / "snapshot.alp").write_bytes(b"canonical")
    ots_path = case_dir / "snapshot.alp.ots"
    ots_path.write_bytes(b"proof")

    def fake_verify(path):
        return VerifyResult(
            status="confirmed",
            bitcoin_block=925847,
            attested_at="2025-11-30",
            ots_path=Path(path),
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(mod, "verify", fake_verify)

    client = _make_client(tmp_path, builder=lambda c: _FakeSnapshot(b""))
    r = client.get("/ledger/snapshots/c-1/anchor/verify")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "confirmed"
    assert body["bitcoin_block"] == 925847
    assert body["attested_at"] == "2025-11-30"


def test_verify_returns_404_when_proof_missing(tmp_path, monkeypatch):
    from interface.ledger import anchor_router as mod

    def fake_verify(path):
        raise AnchorError(f"proof file does not exist: {path}")

    monkeypatch.setattr(mod, "verify", fake_verify)

    client = _make_client(tmp_path, builder=lambda c: _FakeSnapshot(b""))
    r = client.get("/ledger/snapshots/c-1/anchor/verify")

    assert r.status_code == 404
    assert "proof file does not exist" in r.json()["detail"]
