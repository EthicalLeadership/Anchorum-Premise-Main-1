"""`/summarize` must return validated claims alongside the narrative.

/tools/analyse validates every explicit claim's quote against the source
(validate_claims). /summarize does not — it returns llm_summarize(text)
directly, so a user clicking 'Ask Saul to summarize' gets an unverified
narrative.

The fix: after producing the narrative, also run tools.extract_claims +
tools.validate_claims against the source text, and return both. The
narrative is a readable guide; the claims are the trustable output.

Test stubs both LLM entry points (llm_summarize uses requests.post
directly; tools.extract_claims uses tools._call_ollama) so the test
runs without Ollama.
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from interface.server import create_app


@pytest.fixture
def client_and_db(tmp_path, monkeypatch):
    # /summarize short-circuits with LLM_DISABLED when this isn't set
    monkeypatch.setenv("ANCHORUM_LLM_ENABLED", "1")
    db_path = tmp_path / "api.db"
    app = create_app(
        f"sqlite:///{db_path}",
        local_api_mode=True,
        evidence_directory=tmp_path / "ev",
    )
    with TestClient(app) as c:
        yield c, db_path


def _upload(client, case_id):
    r = client.post(
        f"/cases/{case_id}/evidence",
        files={"file": ("note.txt",
                        b"Dr. Jean Dupont. Date: 2024-01-12. "
                        b"Benefits are approved until April 27, 2026.",
                        "text/plain")},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _create_case(client):
    r = client.post("/cases", json={
        "key": "SUMMARIZE-TEST", "title": "summarize",
        "jurisdiction": "QC", "matterType": "labour",
        "timezone": "UTC", "description": "", "memberIds": [],
    })
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_summarize_returns_validated_claims(client_and_db, monkeypatch):
    client, _ = client_and_db
    case_id = _create_case(client)
    ev_id = _upload(client, case_id)

    # Stub narrative (direct requests.post path)
    # `**kwargs` because the route passes the document's filename through so the
    # prompt's citation format can name the file it is citing. The stub stands in
    # for the model, not for the call's exact arguments.
    monkeypatch.setattr(
        "interface.llm_classifier.llm_summarize",
        lambda text, **kwargs: {
            "narrative": "Benefits are approved until 2026-04-27.",
            "backend": "ollama", "model": "test", "cached": False, "error": None,
        },
    )

    # Stub claim extraction with two claims: one verbatim (should verify),
    # one fabricated (should be rejected with attempted_quote).
    monkeypatch.setattr(
        "interface.tools._call_ollama",
        lambda prompt, text: ([
            {"text": "Benefits approved until 2026-04-27",
             "quote": "Benefits are approved until April 27, 2026",
             "basis": "explicit"},
            {"text": "Fabricated claim about penalties",
             "quote": "the insurer will pay a penalty of $500 per day",
             "basis": "explicit"},
        ], None),
    )

    r = client.post(f"/evidence/{ev_id}/summarize")
    assert r.status_code == 200, r.text
    body = r.json()

    # Existing contract preserved
    assert body["id"] == ev_id
    assert body["narrative"]["narrative"].startswith("Benefits are approved")

    # New contract: validated claims
    assert "claims" in body, "missing 'claims' — /summarize still returns raw narrative"
    assert "validation" in body, "missing 'validation'"

    v = body["validation"]
    assert v["verified"] == 1, (
        f"expected 1 verified claim, got {v['verified']}. "
        f"claims={body['claims']}, rejected={v.get('rejected_claims')}"
    )
    assert v["rejected"] == 1, (
        f"expected 1 rejected claim, got {v['rejected']}"
    )
    rejected = v["rejected_claims"][0]
    assert "not verbatim" in rejected["reason"]
    assert rejected["attempted_quote"] == "the insurer will pay a penalty of $500 per day"
