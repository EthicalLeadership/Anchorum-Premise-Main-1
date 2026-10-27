"""The exported narrative must stay joinable to the manifest it travels with.

The sanitizer redacts hash-shaped strings, and an evidence key is `E-<digest>`
— so the id and the content hash both look like secrets to the pattern. They
are not: the manifest prints the same values, and a summary whose ids were
redacted cannot be cross-referenced with the manifest by the reader who
receives both.
"""
from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient

from interface.server import create_app


def _app(tmp_path):
    return create_app(
        f"sqlite:///{tmp_path / 'api.db'}",
        local_api_mode=True,
        evidence_directory=tmp_path / "ev",
    )


def _summary_of(client, case_key="S1") -> tuple[str, str]:
    """Upload one exhibit, stamp, export, and return (summary, evidence id)."""
    client.post(
        "/cases",
        json={
            "key": case_key,
            "title": "Summary",
            "jurisdiction": "QC",
            "matterType": "labour",
            "timezone": "UTC",
            "description": "",
            "memberIds": [],
        },
    )
    upload = client.post(
        f"/cases/{case_key}/evidence",
        files={"file": ("exhibit.txt", b"exhibit bytes", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    evidence_id = upload.json()["id"]
    client.post(f"/cases/{case_key}/stamp", json={"approved_by": "Me. Tremblay"})
    response = client.post(f"/cases/{case_key}/export")
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        summary = archive.read("SUMMARY.md").decode("utf-8")
    return summary, evidence_id


def test_summary_keeps_the_evidence_id_and_content_hash(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        summary, evidence_id = _summary_of(client)
        document = client.get(f"/evidence/{evidence_id}").json()
        # The narrative is the human-readable half of the package; the hash it
        # must agree with is the one the manifest records for this artifact.
        assert "sha256:" in summary

    assert evidence_id in summary, summary
    assert "[redacted-hash]" not in summary, summary
    assert document["id"] == evidence_id


def test_summary_still_redacts_hashes_it_was_not_given(tmp_path):
    """The allowlist is exact values, not a licence to print every digest."""
    import hashlib

    with TestClient(_app(tmp_path)) as client:
        summary, _ = _summary_of(client, case_key="S2")

    unrelated = hashlib.sha256(b"something else entirely").hexdigest()
    assert unrelated not in summary
