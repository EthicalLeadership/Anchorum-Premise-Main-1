import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from interface.server import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(
        f"sqlite:///{tmp_path / 'api.db'}",
        local_api_mode=True,
        evidence_directory=tmp_path / "ev",
    )
    with TestClient(app) as c:
        c.post("/cases", json={
            "key": "B1", "title": "Barreau test", "jurisdiction": "QC",
            "matterType": "labour", "timezone": "UTC",
            "description": "", "memberIds": [],
        })
        c.post("/cases/B1/evidence", files={"file": ("a.txt", b"hello", "text/plain")})
        yield c


def test_preview_blocks_without_stamp(client):
    r = client.post("/cases/B1/exports/preview?type=evidence_index")
    assert r.status_code == 200
    body = r.json()
    assert body["blocked"] is True
    barreau = next(g for g in body["gates"] if g["id"] == "barreau")
    assert barreau["result"] == "fail"
    assert "stamp" in barreau["failingItem"].lower()


def test_export_403_without_stamp(client):
    r = client.post("/cases/B1/export")
    assert r.status_code == 403
    assert r.json()["error"] == "EXPORT_BLOCKED_BARREAU"


def test_stamp_then_preview_passes(client):
    r = client.post("/cases/B1/stamp", json={"approved_by": "Me. Tremblay"})
    assert r.status_code == 200
    body = r.json()
    assert body["stamped"] is True
    assert body["approved_by"] == "Me. Tremblay"
    assert body["stamp_version"] == "1.0.0"

    p = client.post("/cases/B1/exports/preview?type=evidence_index").json()
    assert p["blocked"] is False
    gates = {g["id"]: g for g in p["gates"]}
    # Gates include advisory verdicts now (provenance, control chain), so
    # "everything passes" is no longer the contract. "Nothing blocking failed"
    # is.
    assert [g for g in gates.values() if g["result"] == "fail"] == []
    assert gates["barreau"]["result"] == "pass"
    assert gates["audit_chain"]["result"] == "pass"


def test_stamp_then_export_downloads(client):
    client.post("/cases/B1/stamp", json={"approved_by": "Me. Tremblay"})
    r = client.post("/cases/B1/export")
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert "manifest.json" in names
    assert "DISCLAIMER.md" in names

    import json as _json
    manifest = _json.loads(z.read("manifest.json"))
    assert manifest["schema_version"] == "1.0"
    assert manifest["barreau_stamp"]["approved_by"] == "Me. Tremblay"
    assert manifest["barreau_stamp"]["version"] == "1.0.0"

    # Curated analysis: no raw analysis_json, no internal hashes.
    for doc in manifest["documents"]:
        # content_hash is legitimate and preserved for verification.
        assert "content_hash" in doc
        analysis = doc["analysis"]
        if analysis is None:
            continue
        assert "analysis_rules_hash" not in _json.dumps(analysis)
        assert "analysis_config_hash" not in _json.dumps(analysis)
        assert "lexiconHash" not in _json.dumps(analysis)
        # documentType still present when the parser produced one.
        assert "documentType" in analysis


def test_stamp_is_idempotent(client):
    r1 = client.post("/cases/B1/stamp", json={"approved_by": "Me. Tremblay"})
    r2 = client.post("/cases/B1/stamp", json={"approved_by": "Me. Tremblay"})
    assert r1.json()["applied_at"] == r2.json()["applied_at"]
    assert r2.json().get("already_stamped") is True


def test_stamp_requires_approved_by(client):
    r = client.post("/cases/B1/stamp", json={})
    assert r.status_code == 400
    assert r.json()["error"] == "INVALID_FORM"


def test_get_stamp_unstamped(client):
    r = client.get("/cases/B1/stamp")
    assert r.status_code == 200
    assert r.json()["stamped"] is False
