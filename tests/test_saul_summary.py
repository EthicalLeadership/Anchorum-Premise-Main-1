"""Wire 7: the Saul narrative endpoint, its prompt provenance, and its storage.

The model is stubbed; everything around it is real — prompt rendering from
`prompts/v1/analyze_claim.txt`, quote verification against the extracted text,
storage on its own column, and the audit row.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from interface import prompts
from interface.server import create_app

SOURCE = (
    "Dr. Jean Dupont. Date: 2024-01-12. "
    "Benefits are approved until April 27, 2026, pending a medical reassessment."
)
NARRATIVE = (
    "1. Faits établis par les documents\n"
    "- Les prestations sont approuvées jusqu'au 27 avril 2026 "
    "[source: note.txt, page 1, lines 1-2].\n\n"
    "2. Éléments manquants ou contradictoires\n"
    "- La lettre ne précise pas la date de réévaluation.\n"
)


@pytest.fixture
def client_and_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHORUM_LLM_ENABLED", "1")
    app = create_app(
        f"sqlite:///{tmp_path / 'api.db'}",
        local_api_mode=True,
        evidence_directory=tmp_path / "ev",
    )
    with TestClient(app) as c:
        case = c.post(
            "/cases",
            json={
                "key": "SAUL-TEST",
                "title": "Saul",
                "jurisdiction": "QC",
                "matterType": "labour",
                "timezone": "UTC",
                "description": "",
                "memberIds": [],
            },
        )
        assert case.status_code in (200, 201), case.text
        case_id = case.json()["id"]
        upload = c.post(
            f"/cases/{case_id}/evidence",
            files={"file": ("note.txt", SOURCE.encode("utf-8"), "text/plain")},
        )
        assert upload.status_code in (200, 201), upload.text
        yield c, case_id, upload.json()["id"]


def _stub(monkeypatch, *, narrative=NARRATIVE):
    """Stub the model and the claim extractor; leave verification real."""
    monkeypatch.setattr(
        "interface.llm_classifier.llm_summarize",
        lambda text, **kwargs: {
            "narrative": narrative,
            "backend": "ollama",
            "model": "test-model",
            "cached": False,
            "error": None,
            "prompt": "analyze_claim.txt",
            "promptSha256": "",
            "promptStatus": "verified",
        },
    )
    monkeypatch.setattr(
        "interface.tools._call_ollama",
        lambda prompt, text: (
            [
                {
                    "text": "Benefits run to 2026-04-27",
                    "quote": "Benefits are approved until April 27, 2026",
                    "basis": "explicit",
                },
                {
                    "text": "The letter says penalties apply",
                    "quote": "the insurer will impose a $500 daily penalty",
                    "basis": "explicit",
                },
                {
                    "text": "The letter does not state a reassessment date",
                    "quote": "",
                    "basis": "absence",
                },
            ],
            None,
        ),
    )


def test_summarize_returns_narrative_and_verified_claims(client_and_evidence, monkeypatch):
    client, _, evidence_id = client_and_evidence
    _stub(monkeypatch)

    r = client.post(f"/evidence/{evidence_id}/summarize")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["id"] == evidence_id
    assert body["narrative"]["narrative"].startswith("1. Faits établis")
    assert body["validation"]["verified"] == 1
    assert body["validation"]["inferred"] == 1
    assert body["validation"]["rejected"] == 1
    rejected = body["validation"]["rejected_claims"][0]
    assert "not verbatim" in rejected["reason"]
    assert rejected["attempted_quote"] == "the insurer will impose a $500 daily penalty"
    assert body["generatedAt"]


def test_summary_is_stored_and_readable_without_a_second_model_call(
    client_and_evidence, monkeypatch
):
    client, _, evidence_id = client_and_evidence
    _stub(monkeypatch)
    first = client.post(f"/evidence/{evidence_id}/summarize")
    assert first.status_code == 200

    # Prove the GET cannot reach the model: any call would raise here.
    def explode(*args, **kwargs):
        raise AssertionError("the stored summary must not re-run the model")

    monkeypatch.setattr("interface.llm_classifier.llm_summarize", explode)
    stored = client.get(f"/evidence/{evidence_id}/summarize")
    assert stored.status_code == 200
    body = stored.json()
    assert body["narrative"]["narrative"].startswith("1. Faits établis")
    assert body["cached"] is True
    assert body["generatedAt"] == first.json()["generatedAt"]


def test_get_before_any_summary_says_so(client_and_evidence):
    client, _, evidence_id = client_and_evidence
    r = client.get(f"/evidence/{evidence_id}/summarize")
    assert r.status_code == 200
    body = r.json()
    assert body["narrative"] is None
    assert body["reason"] == "NOT_GENERATED"


def test_summary_does_not_overwrite_the_consultation(client_and_evidence, monkeypatch):
    """A document type and a cited narrative are two answers, not one slot."""
    client, _, evidence_id = client_and_evidence
    _stub(monkeypatch)
    monkeypatch.setattr(
        "interface.llm_classifier.llm_classify",
        lambda text: {
            "documentType": "medical_note",
            "backend": "ollama",
            "model": "test-model",
            "cached": False,
            "error": None,
            "prompt": "classify_document.txt",
        },
    )
    consult = client.post(f"/evidence/{evidence_id}/consult")
    assert consult.status_code == 200, consult.text
    assert consult.json()["consultation"]["documentType"] == "medical_note"

    summarize = client.post(f"/evidence/{evidence_id}/summarize")
    assert summarize.status_code == 200

    item = client.get(f"/evidence/{evidence_id}").json()
    assert item["consultation"]["documentType"] == "medical_note"


def test_summary_writes_a_custody_row(client_and_evidence, monkeypatch):
    client, _, evidence_id = client_and_evidence
    _stub(monkeypatch)
    client.post(f"/evidence/{evidence_id}/summarize")
    custody = client.get(f"/evidence/{evidence_id}/custody").json()
    assert "summarised" in [entry["action"] for entry in custody]


def test_summarize_is_honest_when_the_model_is_off(client_and_evidence, monkeypatch):
    client, _, evidence_id = client_and_evidence
    monkeypatch.setenv("ANCHORUM_LLM_ENABLED", "0")
    r = client.post(f"/evidence/{evidence_id}/summarize")
    assert r.status_code == 200
    body = r.json()
    assert body["narrative"] is None
    assert body["reason"] == "LLM_DISABLED"


def test_model_failure_reports_the_error_rather_than_empty_claims(
    client_and_evidence, monkeypatch
):
    client, _, evidence_id = client_and_evidence
    monkeypatch.setattr(
        "interface.llm_classifier.llm_summarize",
        lambda text, **kwargs: {
            "narrative": "",
            "backend": "ollama",
            "model": "test-model",
            "cached": False,
            "error": "OLLAMA_UNREACHABLE: URLError",
            "prompt": "analyze_claim.txt",
            "promptSha256": "",
            "promptStatus": "verified",
        },
    )
    r = client.post(f"/evidence/{evidence_id}/summarize")
    assert r.status_code == 200
    body = r.json()
    assert body["validation"]["notRun"] == "OLLAMA_UNREACHABLE: URLError"
    assert body["claims"] == []


def test_summarize_unknown_evidence_is_not_found(client_and_evidence):
    client, _, _ = client_and_evidence
    r = client.post("/evidence/E-does-not-exist/summarize")
    assert r.status_code == 404
    assert r.json()["error"] == "NOT_FOUND"


def test_analyze_claim_prompt_is_pinned_and_renders_both_placeholders():
    """The prompt the endpoint sends is the file, verified and filled in."""
    text = prompts.analyze_claim("[fichier: note.txt]\n\nBody text.", topic="Summarise it.")
    assert "[fichier: note.txt]" in text
    assert "Summarise it." in text
    assert "{context}" not in text
    assert "{topic}" not in text
    described = prompts.describe(prompts.ANALYZE_CLAIM)
    assert described["status"] == "verified"


def test_prompt_with_a_missing_placeholder_is_not_silently_blank():
    """An unfilled placeholder stays visible instead of becoming empty text."""
    rendered = prompts.render(prompts.ANALYZE_CLAIM, {"context": "body only"})
    assert "{topic}" in rendered
