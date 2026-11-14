"""HTTP contract tests for interface/ledger/timestamp_router.py.

Proves the local Trust Engine route:
  * needs snapshot_builder on app.state (503 when unset)
  * writes snapshot.alp plus a .tsr under app.state.timestamp_dir
  * returns 503 when the TSA is not provisioned, rather than a bare 500
  * proxies verify() and reports a missing response as 404

Real OpenSSL is used: a stub would not catch a broken certificate profile,
which is the failure this route exists to expose.
"""
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from interface.ledger.timestamp_router import router as ledger_timestamp_router

REPO_TSA = Path("var/tsa")


class _FakeSnapshot:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def canonical_bytes(self) -> bytes:
        return self._data


def _make_client(tmp_path: Path, *, tsa_dir: Path | None, builder=None) -> TestClient:
    app = FastAPI()
    app.include_router(ledger_timestamp_router)
    app.state.timestamp_dir = tmp_path / "timestamps"
    if tsa_dir is not None:
        app.state.tsa_dir = tsa_dir
    if builder is not None:
        app.state.snapshot_builder = builder
    return TestClient(app)


@pytest.fixture
def provisioned_tsa(tmp_path) -> Path:
    """A real TSA store, copied from the workspace when it has been set up."""
    if not (REPO_TSA / "ca.crt").is_file() or not (REPO_TSA / "tsa.crt").is_file():
        pytest.skip("TSA certificates not provisioned; run scripts/setup_local_tsa.sh")
    target = tmp_path / "tsa"
    target.mkdir()
    for name in ("ca.crt", "tsa.crt", "tsa.cnf"):
        shutil.copy(REPO_TSA / name, target / name)
    # `ts -reply` needs its serial file; without it the reply step fails.
    if (REPO_TSA / "tsaserial").is_file():
        shutil.copy(REPO_TSA / "tsaserial", target / "tsaserial")
    return target


def test_requires_snapshot_builder(tmp_path):
    client = _make_client(tmp_path, tsa_dir=tmp_path / "tsa", builder=None)

    response = client.post("/ledger/snapshots/c-1/timestamp")

    assert response.status_code == 503
    assert "snapshot_builder" in response.json()["detail"]


def test_returns_503_when_tsa_is_not_provisioned(tmp_path):
    client = _make_client(
        tmp_path,
        tsa_dir=tmp_path / "missing-tsa",
        builder=lambda case_id: _FakeSnapshot(b"bytes"),
    )

    response = client.post("/ledger/snapshots/c-1/timestamp")

    assert response.status_code == 503
    assert "TSA config not found" in response.json()["detail"]


def test_stamps_a_snapshot(tmp_path, provisioned_tsa):
    client = _make_client(
        tmp_path,
        tsa_dir=provisioned_tsa,
        builder=lambda case_id: _FakeSnapshot(b"canonical snapshot bytes"),
    )

    response = client.post("/ledger/snapshots/c-1/timestamp")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "timestamped"
    assert Path(body["timestamp_path"]).is_file()
    assert Path(body["snapshot_path"]).read_bytes() == b"canonical snapshot bytes"


def test_verify_reports_failure_for_missing_response(tmp_path, provisioned_tsa):
    client = _make_client(tmp_path, tsa_dir=provisioned_tsa, builder=None)

    response = client.get("/ledger/snapshots/never-stamped/timestamp/verify")

    assert response.status_code == 404


def test_stamp_then_verify_round_trip(tmp_path, provisioned_tsa):
    client = _make_client(
        tmp_path,
        tsa_dir=provisioned_tsa,
        builder=lambda case_id: _FakeSnapshot(b"canonical snapshot bytes"),
    )
    stamped = client.post("/ledger/snapshots/c-1/timestamp")
    assert stamped.status_code == 200, stamped.text

    verified = client.get("/ledger/snapshots/c-1/timestamp/verify")

    assert verified.status_code == 200, verified.text
    assert verified.json()["verified"] is True
