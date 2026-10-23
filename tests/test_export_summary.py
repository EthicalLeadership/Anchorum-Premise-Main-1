import io
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
            "key": "SUM1", "title": "Summary test", "jurisdiction": "QC",
            "matterType": "labour", "timezone": "UTC",
            "description": "", "memberIds": [],
        })
        c.post("/cases/SUM1/evidence",
               files={"file": ("a.txt", b"hello summary", "text/plain")})
        c.post("/cases/SUM1/stamp", json={"approved_by": "Me. Test"})
        yield c


def test_zip_contains_summary_md(client):
    r = client.post("/cases/SUM1/export")
    assert r.status_code == 200, r.text
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert "SUMMARY.md" in z.namelist()


def test_summary_mentions_case_and_stamp(client):
    r = client.post("/cases/SUM1/export")
    body = zipfile.ZipFile(io.BytesIO(r.content)).read("SUMMARY.md").decode()
    assert "SUM1" in body
    assert "Summary test" in body
    assert "Me. Test" in body
    assert "## Evidence" in body


def test_summary_does_not_contain_internal_hashes(client):
    r = client.post("/cases/SUM1/export")
    body = zipfile.ZipFile(io.BytesIO(r.content)).read("SUMMARY.md").decode()
    # Internal rule/config hashes must not appear
    assert "analysis_rules_hash" not in body
    assert "analysis_config_hash" not in body
    assert "lexiconHash" not in body
    assert "configHash" not in body


def test_manifest_still_has_content_hash(client):
    r = client.post("/cases/SUM1/export")
    import json
    z = zipfile.ZipFile(io.BytesIO(r.content))
    manifest = json.loads(z.read("manifest.json"))
    assert "content_hash" in manifest["documents"][0]


def test_zip_omits_summary_when_disabled(client):
    r = client.post("/cases/SUM1/export?include_summary=false")
    assert r.status_code == 200, r.text
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert "SUMMARY.md" not in z.namelist()
    # manifest and DISCLAIMER still present — only the prose summary is opted out
    assert "manifest.json" in z.namelist()
    assert "DISCLAIMER.md" in z.namelist()
