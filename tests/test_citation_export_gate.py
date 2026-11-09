import json
import sqlite3

from interface.citation_validator import (
    validate_all_citations,
    validate_citations_against_sources,
)
from interface.preflight import citation_validation_gate
from interface.tools import review_narrative_support
from tests.test_interface_api import app_for, multipart_file, request


class DocumentStub:
    def __init__(self, *, summary_json=None, consultation_json=None, filename="note.txt"):
        self.document_key = "evidence-1"
        self.filename = filename
        self.summary_json = summary_json
        self.consultation_json = consultation_json


def _summary(text, *, quote="Evidence supports the claim."):
    return json.dumps(
        {
            "narrative": {
                "narrative": text,
                "_citation_validation_report": validate_all_citations(text),
            },
            "citation_support": {
                "valid": True,
                "claims": [
                    {
                        "text": "A factual claim.",
                        "quote": quote,
                        "confidence": "direct",
                        "citation": {
                            "file": "note.txt",
                            "page": 1,
                            "lines_start": 1,
                            "lines_end": 1,
                        },
                    }
                ],
            },
        }
    )


def test_reference_validator_checks_source_page_and_local_line_range():
    result = validate_citations_against_sources(
        "Finding [source: note.txt, page 2, lines 1-2].",
        {"note.txt": ["first page", "first line\nsecond line"]},
    )

    assert result["valid"] is True
    assert result["parsed_citations"][0]["source_verified"] is True


def test_reference_validator_rejects_missing_source_page_and_lines():
    for text, sources in (
        ("[source: absent.txt, page 1, lines 1-1]", {"note.txt": ["line"]}),
        ("[source: note.txt, page 2, lines 1-1]", {"note.txt": ["line"]}),
        ("[source: note.txt, page 1, lines 2-2]", {"note.txt": ["line"]}),
    ):
        result = validate_citations_against_sources(text, sources)
        assert result["valid"] is False
        assert result["invalid_citations"]


def test_reference_validator_rejects_malformed_citation_marker():
    result = validate_citations_against_sources(
        "Finding [source: note.txt, page one, lines 1-2].",
        {"note.txt": ["line one", "line two"]},
    )

    assert result["valid"] is False
    assert result["invalid_citations"]


def test_narrative_support_review_verifies_quotes_against_cited_text(monkeypatch):
    monkeypatch.setattr(
        "interface.tools._call_ollama",
        lambda prompt, text: (
            [
                {
                    "text": "The evidence supports the claim.",
                    "quote": "The evidence confirms the claimant's date.",
                    "basis": "explicit",
                }
            ],
            None,
        ),
    )

    result = review_narrative_support(
        "The evidence supports the claim.",
        "The evidence confirms the claimant's date.",
    )

    assert result["valid"] is True
    assert result["validation"]["verified"] == 1


def test_narrative_support_review_fails_when_claim_quote_is_unverifiable(monkeypatch):
    monkeypatch.setattr(
        "interface.tools._call_ollama",
        lambda prompt, text: (
            [{"text": "A claim.", "quote": "fabricated quote", "basis": "explicit"}],
            None,
        ),
    )

    result = review_narrative_support(
        "A claim.",
        "The source contains no such statement.",
    )

    assert result["valid"] is False
    assert result["validation"]["rejected"] == 1


def test_citation_gate_passes_for_valid_stored_summary():
    document = DocumentStub(
        summary_json=_summary(
            "Finding [source: note.txt, page 1, lines 1-1].",
            quote="Evidence supports the claim.",
        )
    )

    gate = citation_validation_gate(
        [document],
        {"note.txt": ["Evidence supports the claim."]},
    )

    assert gate.result == "pass"
    assert gate.blocking is True


def test_citation_gate_fails_for_invalid_stored_summary():
    document = DocumentStub(
        summary_json=_summary("Finding [source: note.txt, page 1, lines 2-1].")
    )

    gate = citation_validation_gate([document], {"note.txt": ["line"]})

    assert gate.result == "fail"
    assert gate.blocking is True


def test_citation_gate_fails_closed_for_corrupt_stored_summary():
    gate = citation_validation_gate(
        [DocumentStub(summary_json="{")],
        {"note.txt": ["line"]},
    )

    assert gate.result == "fail"
    assert gate.blocking is True


def test_citation_gate_fails_closed_without_validation_report():
    gate = citation_validation_gate(
        [
            DocumentStub(
                summary_json=json.dumps({"narrative": {"narrative": "Claim."}})
            )
        ],
        {"note.txt": ["line"]},
    )

    assert gate.result == "fail"
    assert gate.blocking is True


def test_citation_gate_fails_when_claim_quote_is_not_in_cited_lines():
    document = DocumentStub(
        summary_json=_summary(
            "Claim [source: note.txt, page 1, lines 1-1].",
            quote="Fabricated support.",
        )
    )

    gate = citation_validation_gate(
        [document],
        {"note.txt": ["Actual source text."]},
    )

    assert gate.result == "fail"
    assert gate.blocking is True


def test_citation_gate_checks_consultation_source_references():
    consultation = json.dumps(
        {
            "_citation_validation_report": {
                "valid": True,
                "invalid_citations": [],
                "parsed_citations": [
                    {
                        "file": "missing.txt",
                        "page": 1,
                        "lines_start": 1,
                        "lines_end": 1,
                    }
                ],
            }
        }
    )

    gate = citation_validation_gate(
        [DocumentStub(consultation_json=consultation)],
        {"note.txt": ["line"]},
    )

    assert gate.result == "fail"


def test_citation_gate_fails_closed_for_corrupt_citation_report():
    consultation = json.dumps(
        {
            "_citation_validation_report": {
                "valid": True,
                "invalid_citations": [],
                "parsed_citations": "not-a-list",
            }
        }
    )

    gate = citation_validation_gate(
        [DocumentStub(consultation_json=consultation)],
        {"note.txt": ["line"]},
    )

    assert gate.result == "fail"


def _create_exportable_case(tmp_path, summary):
    db_path = tmp_path / "export.db"
    app = app_for(db_path, evidence_directory=tmp_path / "evidence")
    created = request(
        app,
        "POST",
        "/cases",
        {
            "key": "CITATION-EXPORT",
            "title": "Citation export test",
            "jurisdiction": "QC",
            "matterType": "labour",
            "timezone": "UTC",
            "description": "",
            "memberIds": [],
        },
    )
    assert created.status_code == 201, created.body
    case_id = created.json()["id"]

    upload_body, content_type = multipart_file("note.txt", b"evidence text")
    uploaded = request(
        app,
        "POST",
        f"/cases/{case_id}/evidence",
        raw_body=upload_body,
        content_type=content_type,
    )
    assert uploaded.status_code in (200, 201), uploaded.body
    stamped = request(
        app,
        "POST",
        f"/cases/{case_id}/stamp",
        {"stamp_version": "1.0", "approved_by": "test"},
    )
    assert stamped.status_code in (200, 201), stamped.body

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE documents SET summary_json = ? WHERE case_id = ?",
            (summary, case_id),
        )
    return app, db_path, case_id


def test_export_blocks_invalid_citation_in_stored_summary(tmp_path):
    app, _db_path, case_id = _create_exportable_case(
        tmp_path,
        _summary(
            "Finding [source: note.txt, page 1, lines 2-2].",
            quote="evidence text",
        ),
    )

    preview = request(
        app,
        "POST",
        f"/cases/{case_id}/exports/preview?type=evidence_index",
    )
    assert preview.status_code == 200
    assert preview.json()["blocked"] is True
    assert next(
        gate for gate in preview.json()["gates"] if gate["id"] == "citations"
    )["result"] == "fail"

    response = request(app, "POST", f"/cases/{case_id}/export")

    assert response.status_code == 409
    assert response.json()["error"] == "EXPORT_PREFLIGHT_FAILED"
    assert "citations" in response.json()["message"]


def test_export_audits_citations_validity(tmp_path):
    app, db_path, case_id = _create_exportable_case(
        tmp_path,
        _summary(
            "Finding [source: note.txt, page 1, lines 1-1].",
            quote="evidence text",
        ),
    )

    response = request(app, "POST", f"/cases/{case_id}/export")

    assert response.status_code == 200
    with sqlite3.connect(db_path) as connection:
        citations_valid, details = connection.execute(
            "SELECT citations_valid, details FROM audit_logs "
            "WHERE action = 'export_produced'"
        ).fetchone()
    assert citations_valid == 1
    assert json.loads(details)["citations_valid"] is True


def test_pdf_export_audits_citations_validity(tmp_path, monkeypatch):
    monkeypatch.setattr("interface.export_pdf.build_pdf", lambda **kwargs: b"%PDF-test")
    app, db_path, case_id = _create_exportable_case(
        tmp_path,
        _summary(
            "Finding [source: note.txt, page 1, lines 1-1].",
            quote="evidence text",
        ),
    )

    response = request(app, "POST", f"/cases/{case_id}/export?format=pdf")

    assert response.status_code == 200
    with sqlite3.connect(db_path) as connection:
        citations_valid = connection.execute(
            "SELECT citations_valid FROM audit_logs "
            "WHERE action = 'export_produced' AND details LIKE '%pdf%'"
        ).fetchone()[0]
    assert citations_valid == 1


def test_summarize_persists_page_local_support_for_export(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHORUM_LLM_ENABLED", "1")
    app = app_for(
        tmp_path / "summary.db",
        evidence_directory=tmp_path / "evidence",
    )
    created = request(
        app,
        "POST",
        "/cases",
        {
            "key": "CITATION-SUMMARY",
            "title": "Citation summary test",
            "jurisdiction": "QC",
            "matterType": "labour",
            "timezone": "UTC",
            "description": "",
            "memberIds": [],
        },
    )
    assert created.status_code == 201
    case_id = created.json()["id"]
    upload_body, content_type = multipart_file(
        "note.txt",
        b"Evidence supports the claim.",
    )
    uploaded = request(
        app,
        "POST",
        f"/cases/{case_id}/evidence",
        raw_body=upload_body,
        content_type=content_type,
    )
    assert uploaded.status_code in (200, 201)
    evidence_id = uploaded.json()["id"]
    narrative = "The evidence supports the claim. [source: note.txt, page 1, lines 1-1]."
    monkeypatch.setattr(
        "interface.llm_classifier.llm_summarize",
        lambda text, **kwargs: {
            "narrative": narrative,
            "backend": "ollama",
            "model": "test",
            "cached": False,
            "error": None,
            "_citation_validation_report": validate_citations_against_sources(
                narrative,
                {"note.txt": ["Evidence supports the claim."]},
            ),
            "unverified_claims": [],
        },
    )
    monkeypatch.setattr(
        "interface.tools.extract_claims",
        lambda *args: ([], {"error": None}),
    )
    monkeypatch.setattr(
        "interface.tools.review_narrative_support",
        lambda text, cited_text: {
            "valid": True,
            "claims": [
                {
                    "text": "The evidence supports the claim.",
                    "quote": "Evidence supports the claim.",
                    "confidence": "direct",
                }
            ],
            "validation": {
                "verified": 1,
                "inferred": 0,
                "rejected": 0,
                "total": 1,
            },
            "error": None,
        },
    )

    summarized = request(
        app,
        "POST",
        f"/evidence/{evidence_id}/summarize",
    )
    assert summarized.status_code == 200
    assert summarized.json()["citation_support"]["valid"] is True
    stored = request(app, "GET", f"/evidence/{evidence_id}/summarize")
    assert stored.status_code == 200
    assert stored.json()["citation_support"]["valid"] is True
    stamped = request(
        app,
        "POST",
        f"/cases/{case_id}/stamp",
        {"stamp_version": "1.0", "approved_by": "test"},
    )
    assert stamped.status_code in (200, 201)
    exported = request(app, "POST", f"/cases/{case_id}/export")
    assert exported.status_code == 200, exported.body
