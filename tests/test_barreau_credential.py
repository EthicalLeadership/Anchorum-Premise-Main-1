import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from interface.server import create_app
from dossier_pipeline.auth import fingerprint_credential


@pytest.fixture
def client(tmp_path):
    app = create_app(
        f"sqlite:///{tmp_path / 'api.db'}",
        local_api_mode=True,
        evidence_directory=tmp_path / "ev",
    )
    with TestClient(app) as c:
        yield c


def test_invite_without_credential_stores_pending(client, monkeypatch):
    monkeypatch.delenv("ANCHORUM_BARREAU_REQUIRED", raising=False)
    r = client.post("/admin/members/invitations", json={"email": "a@x.com", "role": "reviewer"})
    assert r.status_code == 200, r.text
    assert r.json()["credentialFingerprint"] == "pending"


def test_invite_with_valid_credential(client, monkeypatch):
    cred = "BAR-1234"
    fp = fingerprint_credential(cred)
    monkeypatch.setenv("ANCHORUM_BARREAU_ALLOWLIST", fp)
    monkeypatch.delenv("ANCHORUM_BARREAU_REQUIRED", raising=False)
    r = client.post("/admin/members/invitations", json={"email": "b@x.com", "role": "reviewer", "credential": cred})
    assert r.status_code == 200, r.text
    assert r.json()["credentialFingerprint"] == fp


def test_invite_with_wrong_credential_403(client, monkeypatch):
    monkeypatch.setenv("ANCHORUM_BARREAU_ALLOWLIST", fingerprint_credential("GOOD"))
    r = client.post("/admin/members/invitations", json={"email": "c@x.com", "role": "reviewer", "credential": "BAD"})
    assert r.status_code == 403
    assert r.json()["error"] == "BARREAU_CREDENTIAL_REJECTED"


def test_invite_required_without_credential_400(client, monkeypatch):
    monkeypatch.setenv("ANCHORUM_BARREAU_REQUIRED", "1")
    r = client.post("/admin/members/invitations", json={"email": "d@x.com", "role": "reviewer"})
    assert r.status_code == 400
    assert r.json()["error"] == "BARREAU_CREDENTIAL_REQUIRED"
