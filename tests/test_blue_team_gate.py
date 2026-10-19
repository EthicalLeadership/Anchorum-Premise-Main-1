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
        c.post("/cases/B1/evidence", files={"file": ("a.txt", b"hello", "text/plain")})
        c.post("/cases/B1/stamp", json={"approved_by": "Me. Tremblay"})
        yield c


def test_preview_includes_blue_team_gate(client):
    r = client.post("/cases/B1/exports/preview?type=evidence_index")
    assert r.status_code == 200, r.text
    body = r.json()
    gate_ids = [g["id"] for g in body["gates"]]
    assert "blue_team_invariants" in gate_ids


def test_blue_team_gate_has_introspection_fields(client):
    r = client.post("/cases/B1/exports/preview?type=evidence_index")
    body = r.json()
    gate = next(g for g in body["gates"] if g["id"] == "blue_team_invariants")
    assert "count" in gate
    assert "loadError" in gate
    assert "skipped" in gate
    assert isinstance(gate["count"], int)


def test_blue_team_can_be_disabled_by_env(client, monkeypatch):
    monkeypatch.setenv("ANCHORUM_BLUE_TEAM", "0")
    r = client.post("/cases/B1/exports/preview?type=evidence_index")
    body = r.json()
    gate_ids = [g["id"] for g in body["gates"]]
    assert "blue_team_invariants" not in gate_ids


def test_bridge_lists_what_it_loaded():
    ids = invariants_bridge.list_invariant_ids()
    assert isinstance(ids, list)
    # If invariants.py exists and registers invariants, they should appear.
    # If not, the list is empty and the gate reports pass honestly.
    for inv_id in ids:
        assert isinstance(inv_id, str)
