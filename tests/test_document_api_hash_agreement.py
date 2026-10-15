"""The one pin that ties the product path and the pipeline path together.

The same bytes reach the system through two different entry points:

* the product path, `POST /cases/{id}/evidence`, which hashes the upload itself
  and stores it as `Document.content_hash`; and
* the pipeline path, `interface.document.process`, which records the artifact as
  `source_sha256` on the signed record.

They were computed independently and nothing required them to agree. `W1` gave
the pipeline the artifact hash and `W3` reported the product's hash as
`sourceSha256`, which makes it look like one value in two places. This test makes
that a requirement: for the same bytes, both hashes must be the same string. If
either path changes how it identifies an artifact and the other does not, this
fails rather than letting the two halves drift apart under a new name.
"""

import hashlib
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select

from dossier_pipeline.schema import Document
from tests.test_interface_api import app_for, multipart_file, request

#: Small and self-contained: this test is about agreement between two hashes, not
#: about any particular artifact.
ARTIFACT = b"Angel v. Murray: the delivery route was left unchanged.\n"


def _product_hash(tmp_path) -> tuple[str, str]:
    """Upload through the API and return (response hash, stored content hash)."""
    app = app_for(tmp_path / "api.db", evidence_directory=tmp_path / "evidence")
    created = request(
        app,
        "POST",
        "/cases",
        {
            "key": "CASE-HASH-AGREEMENT",
            "title": "Hash agreement",
            "jurisdiction": "RI",
            "matterType": "contracts",
            "timezone": "America/Toronto",
            "description": "",
            "memberIds": [],
        },
    )
    assert created.status_code == 201, created.body

    body, content_type = multipart_file("brief.txt", ARTIFACT)
    uploaded = request(
        app,
        "POST",
        f"/cases/{created.json()['id']}/evidence",
        raw_body=body,
        content_type=content_type,
    )
    assert uploaded.status_code == 201, uploaded.body
    response_hash = uploaded.json()["hash"]
    # The upload reports the artifact hash under its own name too, so the
    # product path states the pipeline's value as well as its own.
    assert uploaded.json()["sourceSha256"] == response_hash

    with app.state.db_sessions() as db:
        document = db.scalar(
            select(Document).where(Document.document_key == uploaded.json()["id"])
        )
        assert document is not None
        return response_hash, document.content_hash


def _pipeline_hash(tmp_path, source: Path) -> tuple[str, str]:
    """Submit a document through the pipeline and return its identity fields."""
    from interface import document

    with patch(
        "interface.document._config",
        return_value={
            "dossier_id": "TEST-HASH-AGREEMENT",
            "output_dir": str(tmp_path / "pipeline"),
            "email": "interface@localhost",
        },
    ):
        result = document.process(file_path=str(source), filename=source.name)

    assert result["status"] in {"processed", "duplicate"}, result
    return result["raw_sha256"], result["data"]["source_sha256"]


def test_both_paths_agree_on_the_artifact_hash(tmp_path):
    source = tmp_path / "brief.txt"
    source.write_bytes(ARTIFACT)
    expected = hashlib.sha256(ARTIFACT).hexdigest()

    product_hash, stored_content_hash = _product_hash(tmp_path)
    _, pipeline_source_hash = _pipeline_hash(tmp_path, source)

    assert product_hash == expected
    assert stored_content_hash == expected
    assert pipeline_source_hash == expected
    assert product_hash == pipeline_source_hash, (
        "the product path and the pipeline path disagree about what artifact "
        "they were handed"
    )


def test_the_pipeline_wrapper_is_not_the_artifact(tmp_path):
    """The identity the pipeline records must not be the transport envelope.

    `raw_sha256` hashes the bytes actually ingested, which for a document
    submission is a wrapper this system built. If the two ever coincide here, the
    artifact binding has been lost and the record describes the wrapper again.
    """
    source = tmp_path / "brief.txt"
    source.write_bytes(ARTIFACT)

    raw_sha256, source_sha256 = _pipeline_hash(tmp_path, source)

    assert raw_sha256 != source_sha256
    assert source_sha256 == hashlib.sha256(ARTIFACT).hexdigest()
