import hashlib
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from interface.server import create_app
from interface import invariants_bridge


@pytest.fixture
def client(tmp_path):
    app = create_app(
        f"sqlite:///{tmp_path / 'api.db'}",
        local_api_mode=True,
        evidence_directory=tmp_path / "ev",
    )
    with TestClient(app) as c:
        c.post("/cases", json={
            "key": "B1", "title": "Blue team", "jurisdiction": "QC",
            "matterType": "labour", "timezone": "UTC",
            "description": "", "memberIds": [],
        })
        up = c.post("/cases/B1/evidence", files={"file": ("a.txt", b"hello", "text/plain")})
        assert up.status_code == 201
        c.post("/cases/B1/stamp", json={"approved_by": "Me. Tremblay"})
        yield c


def test_preview_no_blue_team_gate(client):
    body = client.post("/cases/B1/exports/preview?type=evidence_index").json()
    ids = [g["id"] for g in body["gates"]]
    assert "blue_team_invariants" not in ids


def test_verify_passes_on_clean(client):
    ev = client.get("/cases/B1/evidence").json()[0]["id"]
    r = client.post(f"/evidence/{ev}/verify")
    assert r.status_code == 200, r.text


def test_bridge_loaded_eight():
    assert len(invariants_bridge.list_invariant_ids()) == 8


def test_run_one_inv_003_pass():
    raw = b"hello"
    env = {"message_id": "sha256:" + hashlib.sha256(raw).hexdigest()}
    assert invariants_bridge.run_one("inv_003", {"raw_bytes": raw, "envelope": env})["status"] == "pass"


def test_run_one_inv_003_fail():
    raw = b"hello"
    env = {"message_id": "sha256:" + hashlib.sha256(b"nope").hexdigest()}
    assert invariants_bridge.run_one("inv_003", {"raw_bytes": raw, "envelope": env})["status"] == "fail"


def test_run_one_unregistered():
    assert invariants_bridge.run_one("inv_999", {})["status"] == "skip"
