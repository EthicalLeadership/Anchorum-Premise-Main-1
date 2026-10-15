"""The acceptance run the connector remediation plan exists to satisfy.

`docs/audit/CONNECTOR_REMEDIATION_PLAN.md` §3 defines done as: put the brief in
through the product as one item and have it analysed in its scopes. That is two
tracks, and this file is both of them plus the analysis tier underneath.

* Track A (the analysis tier) the brief is read, segmented and projected.
* Track B (the pipeline path) the same bytes ingest to the same identity every
  time and the signed record names the artifact that was actually submitted.
* Track C (the product path) the upload is analysed, and the analysis is
  reachable at a named route, searchable and visible on the item and its custody.

The assertions are written against the properties, not against a snapshot of the
output, so a change that breaks a property fails here with the property named.
Guarded by the brief's presence so a clone without the sample still runs the
synthetic pins in `tests/test_pdf_text.py` and `tests/test_scopes.py`.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.test_interface_api import app_for, multipart_file, request

BRIEF = Path.home() / "Angel v. Murray \u2013 (IRAC) Case Brief Summary.pdf"
BRIEF_SHA256 = "c58fcf248ab877e75975c04606ab60aca294c2f36d2930df858400b0b9c31830"
BRIEF_BYTES = 149_819

#: The audit's §4 term list: what a successful read has to find in the text.
TERMS = (
    "Maher",
    "Murray",
    "Newport",
    "consideration",
    "refuse-collection",
    "contract",
    "unanticipated",
    "Angel",
    "Rhode Island",
    "Supreme Court",
    "1964",
    "89D(a)",
    "Restatement",
    "$20,000",
)

pytestmark = pytest.mark.skipif(
    not BRIEF.exists(), reason="the brief is not present on this machine"
)


@pytest.fixture(scope="module")
def brief() -> bytes:
    return BRIEF.read_bytes()


@pytest.fixture(scope="module")
def brief_text(brief: bytes) -> str:
    from interface import submission

    return submission.extract_text(brief, BRIEF.name)


# --- Track A the analysis tier ----------------------------------------------


def test_a0_identity(brief: bytes) -> None:
    """The bytes under test are the artifact the audit names."""
    assert hashlib.sha256(brief).hexdigest() == BRIEF_SHA256
    assert len(brief) == BRIEF_BYTES


def test_a1_extraction_is_the_document_and_not_mojibake(brief_text: str) -> None:
    flat = re.sub(r"\s+", " ", brief_text)
    for term in TERMS:
        assert term in flat, f"{term!r} did not survive extraction"
    assert brief_text.count("\ufffd") == 0
    # No control character may survive: the brief's font encodes apostrophes and
    # en dashes as C0/C1 bytes, and a control character is not text.
    surviving = [ch for ch in brief_text if ord(ch) < 0x20 and ch not in "\n\r\t"]
    surviving += [ch for ch in brief_text if 0x7F <= ord(ch) <= 0x9F]
    assert surviving == []


def test_a2_whole_document_projection(brief_text: str) -> None:
    from interface import engine

    projection = engine.project_text(brief_text)
    assert projection.concept_id is not None
    assert projection.admissible is False
    assert projection.classification


def test_a3_scopes_are_recovered(brief_text: str) -> None:
    from interface import scopes

    segmented = scopes.split_scopes(brief_text)
    assert [scope.name for scope in segmented] == list(scopes.SCOPE_NAMES)


def test_a4_analysis_record_is_produced(brief: bytes) -> None:
    from interface import analysis, scopes

    record = analysis.analyse(brief, BRIEF.name, "application/pdf")
    assert record["status"] == analysis.STATUS_PROCESSED
    assert len(record["scopes"]) == len(scopes.SCOPE_NAMES)
    assert record["source"]["sha256"] == BRIEF_SHA256
    assert record["projection"]["engineVersion"]
    assert record["coverage"]["scopesTotal"] == len(scopes.SCOPE_NAMES)


# --- Track B the pipeline path ---------------------------------------------


DSTAMP = "ACCEPTANCE-BRIEF"


@pytest.fixture(scope="module")
def pipeline_run(brief: bytes, tmp_path_factory: pytest.TempPathFactory):
    """Ingest the same bytes twice through `interface/document.py::process`."""
    from interface import document

    output_dir = tmp_path_factory.mktemp("acceptance-pipeline")
    config = patch(
        "interface.document._config",
        return_value={
            "dossier_id": DSTAMP,
            "output_dir": str(output_dir),
            "email": "interface@localhost",
        },
    )
    with config:
        first = document.process(raw_bytes=brief, filename=BRIEF.name)
        second = document.process(raw_bytes=brief, filename=BRIEF.name)
    return first, second, output_dir


@pytest.fixture(scope="module")
def committed_payload(pipeline_run):
    """The last committed control record, read back from the pipeline's store."""
    from dossier_pipeline.pipeline import DossierPipeline

    _, _, output_dir = pipeline_run
    with DossierPipeline(dossier_id=DSTAMP, output_dir=str(output_dir)) as pipeline:
        records = pipeline.control.get_all_records()
    assert records, "no control record was committed"
    return records[-1]["payload"]


def test_b1_identity_is_deterministic(pipeline_run) -> None:
    first, second, _ = pipeline_run
    assert first["raw_sha256"] == second["raw_sha256"]
    assert first["message_id"] == second["message_id"]


def test_b2_the_committed_record_binds_the_artifact(committed_payload) -> None:
    assert committed_payload.get("source_sha256") == BRIEF_SHA256
    assert committed_payload.get("source_bytes") == BRIEF_BYTES
    assert committed_payload.get("source_filename") == BRIEF.name
    assert committed_payload.get("transport") == "document"


def test_b3_a_resubmission_is_a_duplicate(pipeline_run) -> None:
    first, second, _ = pipeline_run
    assert first["status"] == "processed"
    assert second["status"] == "duplicate"


def test_b4_no_correspondent_is_invented_for_a_court_filing(
    committed_payload,
) -> None:
    """The email-shaped fields are named as synthesised, and the actor is not."""
    assert committed_payload.get("actor") == "unknown"
    assert committed_payload.get("classification_scope_warning")
    synthesised = set(committed_payload.get("synthesised_fields") or ())
    assert synthesised == {"message_id", "subject", "sender", "recipient", "date"}


# --- Track C the product path ----------------------------------------------


@pytest.fixture(scope="module")
def uploaded(tmp_path_factory: pytest.TempPathFactory, brief: bytes):
    """Create a case and put the brief in through the product API."""
    base = tmp_path_factory.mktemp("acceptance-api")
    app = app_for(base / "api.db", evidence_directory=base / "evidence")

    created = request(
        app,
        "POST",
        "/cases",
        {
            "key": "CASE-ACCEPTANCE-BRIEF",
            "title": "Angel v. Murray",
            "jurisdiction": "RI",
            "matterType": "contracts",
            "timezone": "America/Toronto",
            "description": "",
            "memberIds": [],
        },
    )
    assert created.status_code == 201, created.body
    case_id = created.json()["id"]

    body, content_type = multipart_file(
        "angel-v-murray.pdf", brief, content_type="application/pdf"
    )
    response = request(
        app,
        "POST",
        f"/cases/{case_id}/evidence",
        raw_body=body,
        content_type=content_type,
    )
    assert response.status_code == 201, response.body
    return app, case_id, response.json()


def test_c1_the_upload_is_analysed_rather_than_only_stored(uploaded) -> None:
    _, _, evidence = uploaded
    assert evidence["hash"] == BRIEF_SHA256
    assert evidence["sourceSha256"] == BRIEF_SHA256
    # "stored" was the hard-coded answer before the analysis path existed; the
    # response now reports what the read actually did.
    assert evidence["processingStatus"] == "extracted"


def test_c2_the_analysis_is_reachable(uploaded) -> None:
    from interface import scopes

    app, _, evidence = uploaded
    response = request(app, "GET", f"/evidence/{evidence['id']}/analysis")
    assert response.status_code == 200, response.body

    record = response.json()
    assert record["status"] == "processed"
    assert record["source"]["sha256"] == BRIEF_SHA256
    assert len(record["scopes"]) == len(scopes.SCOPE_NAMES)
    # The coverage block is what stops seven empty scopes reading as "this
    # document contains no legal concepts".
    assert record["coverage"]["scopesTotal"] == len(scopes.SCOPE_NAMES)
    assert record["coverage"]["warning"]


def test_c3_the_extracted_text_is_searchable(uploaded) -> None:
    app, case_id, evidence = uploaded
    response = request(app, "GET", f"/cases/{case_id}/search?q=Murray")
    assert response.status_code == 200

    hits = response.json()
    assert isinstance(hits, list)
    assert {hit["id"] for hit in hits} == {evidence["id"]}
    assert all(hit["excerpt"] for hit in hits)
    assert response.headers["x-anchorum-search-method"] == "substring"


def test_c4_the_timeline_reports_the_documents_own_events(uploaded) -> None:
    app, case_id, _ = uploaded
    response = request(app, "GET", f"/cases/{case_id}/timeline")
    assert response.status_code == 200

    events = response.json()
    kinds = {event["event"] for event in events}
    assert {"case_created", "evidence_uploaded", "evidence_analysed"} <= kinds
    for event in events:
        assert event["event"] in {
            "case_created",
            "evidence_uploaded",
            "evidence_verified",
            "evidence_analysed",
        }
        assert event["people"] == ["system"]


def test_c5_the_item_status_advances_and_agrees_with_the_route(uploaded) -> None:
    app, _, evidence = uploaded
    item = request(app, "GET", f"/evidence/{evidence['id']}").json()
    record = request(app, "GET", f"/evidence/{evidence['id']}/analysis").json()

    assert item["status"] == "processed"
    assert item["badges"] == ["received", "processed"]
    assert item["analysis"]["status"] == record["status"]
    assert item["analysis"]["scopesTotal"] == record["coverage"]["scopesTotal"]
    assert item["analysis"]["analysedAt"] is not None


def test_c6_custody_says_what_was_and_was_not_checked(uploaded) -> None:
    app, _, evidence = uploaded
    custody = request(app, "GET", f"/evidence/{evidence['id']}/custody").json()

    assert [entry["action"] for entry in custody] == ["uploaded", "analysed"]
    for entry in custody:
        # This host has no control plane, so `linked` would claim a check that
        # never happened.
        assert entry["chain"] == "not_checked"
        assert entry["chainDetail"]
