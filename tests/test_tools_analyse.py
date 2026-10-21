"""Non-case analysis route: citation validator must reject fabricated quotes."""

import pytest
from fastapi.testclient import TestClient

from interface.server import create_app
from interface import tools


@pytest.fixture
def client(tmp_path):
    app = create_app(
        f"sqlite:///{tmp_path / 'api.db'}",
        local_api_mode=True,
        evidence_directory=tmp_path / "ev",
    )
    with TestClient(app) as c:
        yield c


SAMPLE_TEXT = (
    "Dear Samuel Tessier,\n\n"
    "We confirm that benefits are approved until April 27, 2026, "
    "pending a medical reassessment. Failure to attend the reassessment "
    "may result in suspension of benefits.\n\n"
    "Sincerely,\nClaims Department"
)


def test_validator_accepts_verbatim_quote():
    raw = [{
        "text": "Benefits approved until 2026-04-27, contingent on reassessment",
        "quote": "benefits are approved until April 27, 2026, pending a medical reassessment",
        "basis": "explicit",
    }]
    claims, summary = tools.validate_claims(raw, SAMPLE_TEXT)
    assert summary["verified"] == 1
    assert summary["rejected"] == 0
    assert claims[0]["confidence"] == "direct"
    start, end = claims[0]["source"]["span_normalized"]
    norm = tools._normalize(SAMPLE_TEXT)
    assert "April 27, 2026" in norm[start:end]


def test_validator_rejects_fabricated_quote():
    raw = [{
        "text": "Benefits are permanent and unconditional",
        "quote": "this benefit cannot be revoked under any circumstances",
        "basis": "explicit",
    }]
    claims, summary = tools.validate_claims(raw, SAMPLE_TEXT)
    assert summary["verified"] == 0
    assert summary["rejected"] == 1
    assert claims == []
    rejected = summary["rejected_claims"][0]
    assert "not verbatim" in rejected["reason"]
    assert rejected["attempted_quote"] == "this benefit cannot be revoked under any circumstances"


def test_validator_rejects_glued_paraphrase():
    """The motivating example: llama3.1:8b glues 'approved' + 'until'.
    The glued form is a paraphrase, not evidence."""
    raw = [{
        "text": "Benefits approved until 2026-04-27",
        "quote": "benefits are approveduntil April 27, 2026",
        "basis": "explicit",
    }]
    claims, summary = tools.validate_claims(raw, SAMPLE_TEXT)
    assert summary["verified"] == 0
    assert summary["rejected"] == 1
    assert claims == []
    assert summary["rejected_claims"][0]["attempted_quote"] == \
        "benefits are approveduntil April 27, 2026"


def test_validator_marks_absence_as_inferred():
    raw = [{
        "text": "The letter does not state whether arrears are owed",
        "quote": "",
        "basis": "absence",
    }]
    claims, summary = tools.validate_claims(raw, SAMPLE_TEXT)
    assert summary["inferred"] == 1
    assert claims[0]["confidence"] == "inferred"
    assert claims[0]["source"]["quote"] is None


def test_validator_nfc_normalizes_before_match():
    """PDF emits NFD; LLM emits NFC. Both compare equal after NFC."""
    import unicodedata
    nfd = unicodedata.normalize("NFD", "préavis raisonnable de trente jours")
    nfc = unicodedata.normalize("NFC", "préavis raisonnable de trente jours")
    raw = [{"text": "Notice is thirty days", "quote": nfc, "basis": "explicit"}]
    claims, summary = tools.validate_claims(raw, nfd)
    assert summary["verified"] == 1


def test_tools_route_rejects_empty_file(client):
    r = client.post("/tools/analyse", files={"file": ("empty.txt", b"", "text/plain")})
    assert r.status_code == 422
    assert r.json()["error"] == "EMPTY_FILE"


def test_tools_route_pdf_branch(client, monkeypatch):
    """N1 fix: stub extract_text (its return is what we assert on), keep
    looks_like_pdf real. If extract_text is missing at module scope, the
    stub target is gone and the test errors. If looks_like_pdf is missing,
    the route 500s. Neither regression escapes."""
    import interface.anchorum_api as api_mod
    monkeypatch.setattr("interface.tools._call_ollama", lambda p, t: ([], None))
    monkeypatch.setattr(api_mod, "extract_text", lambda d: SAMPLE_TEXT)
    body = b"%PDF-1.4\nplaceholder"
    r = client.post("/tools/analyse",
                    files={"file": ("doc.pdf", body, "application/pdf")},
                    data={"mode": "inbound-analysis"})
    assert r.status_code == 200, r.text
    assert r.json()["document"]["chars"] == len(SAMPLE_TEXT)


def test_tools_route_end_to_end_with_stubbed_llm(client, monkeypatch):
    """Extraction + validation are real; only the LLM is stubbed."""
    monkeypatch.setattr(
        "interface.tools._call_ollama",
        lambda prompt, text: ([
            {"text": "Benefits approved until 2026-04-27",
             "quote": "benefits are approved until April 27, 2026",
             "basis": "explicit"},
            {"text": "The letter makes no mention of arrears",
             "quote": "", "basis": "absence"},
            {"text": "Fabricated claim about penalties",
             "quote": "the insurer will pay a penalty of $500 per day",
             "basis": "explicit"},
        ], None),
    )
    r = client.post(
        "/tools/analyse",
        files={"file": ("letter.txt", SAMPLE_TEXT.encode("utf-8"), "text/plain")},
        data={"mode": "inbound-analysis"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # C1 regression guard only; docType is content-dependent, not asserted
    assert body["extraction"]["analysis_ok"] is True, "analyse() failed silently"
    assert body["validation"]["verified"] == 1
    assert body["validation"]["inferred"] == 1
    assert body["validation"]["rejected"] == 1
    rejected = body["validation"]["rejected_claims"][0]
    assert "not verbatim" in rejected["reason"]
    assert rejected["attempted_quote"] == "the insurer will pay a penalty of $500 per day"
