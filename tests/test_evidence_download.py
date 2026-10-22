"""GET /evidence/{id}/download must serve inline, not as an attachment.

The in-app viewer fetches this URL and renders it. PDF.js reads the bytes and
ignores `Content-Disposition`, so an attachment header would not break the
viewer -- but the plain <a href> fallback would download instead of open, and a
legal tool should open the document it is showing. "Download" is a separate,
explicit action in the toolbar.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from interface.anchorum_api import create_app

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


@pytest.fixture()
def evidence_dir(tmp_path):
    return tmp_path / "evidence"


@pytest.fixture()
def client(tmp_path, evidence_dir):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        local_api_mode=True,
        evidence_directory=evidence_dir,
    )
    with TestClient(app) as test_client:
        yield test_client


def upload(client: TestClient, name: str = "letter.pdf") -> str:
    client.post(
        "/cases",
        json={
            "key": "C-1",
            "title": "Matter",
            "jurisdiction": "qc",
            "matterType": "labour",
            "timezone": "America/Toronto",
        },
    )
    response = client.post(
        "/cases/C-1/evidence",
        files={"file": (name, PDF_BYTES, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_download_is_inline(client: TestClient):
    evidence_id = upload(client)
    response = client.get(f"/evidence/{evidence_id}/download")
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("inline;"), disposition
    assert "letter.pdf" in disposition


def test_download_keeps_the_filename(client: TestClient):
    evidence_id = upload(client, name="demand letter.pdf")
    response = client.get(f"/evidence/{evidence_id}/download")
    assert response.status_code == 200
    # A name with a space goes out in the RFC 5987 form, not a quoted string:
    #   inline; filename*=utf-8''demand%20letter.pdf
    # Asserting the encoded value is what actually proves the original name
    # survived, rather than proving that a plain name would have.
    disposition = response.headers["content-disposition"]
    assert "filename*=utf-8''demand%20letter.pdf" in disposition, disposition


def test_download_returns_the_stored_bytes(client: TestClient):
    evidence_id = upload(client)
    response = client.get(f"/evidence/{evidence_id}/download")
    assert response.content == PDF_BYTES


def test_missing_bytes_is_410_not_an_empty_file(client: TestClient, evidence_dir):
    evidence_id = upload(client)
    stored = next(evidence_dir.glob("*.bin"))
    stored.unlink()
    response = client.get(f"/evidence/{evidence_id}/download")
    assert response.status_code == 410
    assert response.json()["error"] == "ORIGINAL_FILE_MISSING"
