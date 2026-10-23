"""GET /evidence/{id}/text reports what analysis extracted, or why it did not.

The distinction this route exists to preserve: "we read it and found nothing"
and "we never read it" both produce no text, and a viewer that renders both as a
blank pane tells a lawyer their exhibit is empty when the connector simply
cannot read the format. Each non-extracted status therefore reports itself and
its recorded reason instead of an empty string.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from interface.anchorum_api import EXTRACTED_TEXT_LIMIT, create_app

LETTER = (
    "Medical Note\n"
    "Patient: A. Tremblay\n"
    "Date of examination: 2026-03-14\n"
    "Lumbar disc herniation at L4-L5 confirmed by MRI.\n"
)


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


def upload(client: TestClient, name: str, payload: bytes, media_type: str) -> dict:
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
        files={"file": (name, payload, media_type)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_extracted_text_is_returned_with_its_status(client: TestClient):
    created = upload(client, "letter.txt", LETTER.encode(), "text/plain")
    response = client.get(f"/evidence/{created['id']}/text")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "extracted"
    assert "L4-L5" in body["text"]
    assert body["chars"] > 0
    assert body["truncated"] is False
    assert body["chars"] == len(body["text"])


def test_unsupported_type_reports_why_rather_than_returning_empty_text(
    client: TestClient,
):
    # A .docx has no reader in this connector, and is refused before any decode
    # is attempted (`submission.UNIMPLEMENTED_SUFFIXES`). The honest answer is
    # "not read", which is a different fact from "read, and the file was blank".
    # A .zip would not do: its bytes are not refused by suffix, and short
    # archives decode as valid UTF-8, so it reports `extracted`.
    created = upload(
        client,
        "offer.docx",
        b"PK\x03\x04 binary that no reader here opens",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    response = client.get(f"/evidence/{created['id']}/text")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unsupported"
    assert body["text"] is None
    assert body["reason"]


def test_unknown_evidence_is_404(client: TestClient):
    response = client.get("/evidence/E-doesnotexist/text")
    assert response.status_code == 404
    assert response.json()["error"] == "NOT_FOUND"


def test_missing_sidecar_is_410_not_an_empty_success(
    client: TestClient, evidence_dir
):
    created = upload(client, "letter.txt", LETTER.encode(), "text/plain")
    sidecar = next(evidence_dir.glob("*.txt"))
    sidecar.unlink()

    response = client.get(f"/evidence/{created['id']}/text")
    # The row still says extracted, but the bytes are gone. Reporting a
    # successful empty read here would hide a storage fault.
    assert response.status_code == 410
    assert response.json()["error"] == "EXTRACTED_TEXT_MISSING"


def test_long_text_is_truncated_and_says_so(client: TestClient):
    oversized = "a" * (EXTRACTED_TEXT_LIMIT + 500)
    created = upload(client, "long.txt", oversized.encode(), "text/plain")

    body = client.get(f"/evidence/{created['id']}/text").json()
    assert body["truncated"] is True
    assert body["chars"] > len(body["text"])
    assert len(body["text"]) == EXTRACTED_TEXT_LIMIT
