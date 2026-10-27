"""Wire 8: the `.eml` front door, end to end through the real pipeline stages.

The stages are the dossier pipeline's own deterministic components, so these
tests assert on what those components actually decided — not on a stub. The only
thing that is not real is nothing: `EmailIntake`, `EmailClassifier` and
`PolicyEngine` all run.
"""

from __future__ import annotations

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
        yield c


def _create_case(client, key="INTAKE-TEST"):
    r = client.post(
        "/cases",
        json={
            "key": key,
            "title": "Email intake",
            "jurisdiction": "QC",
            "matterType": "labour",
            "timezone": "America/Toronto",
            "description": "",
            "memberIds": [],
        },
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _eml(subject: str, body: str, *, sender="hr@acme.example", message_id="<m1@acme>"):
    return (
        f"From: {sender}\r\n"
        "To: operator@anchorum.example\r\n"
        f"Subject: {subject}\r\n"
        "Date: Mon, 12 Jan 2026 09:00:00 -0500\r\n"
        f"Message-ID: {message_id}\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: text/plain; charset="utf-8"\r\n'
        "\r\n"
        f"{body}\r\n"
    ).encode("utf-8")


def _post(client, case_id, files):
    return client.post(
        f"/cases/{case_id}/intake/email",
        files=[("files", (name, data, "message/rfc822")) for name, data in files],
    )


def test_clean_message_passes_all_three_stages(client):
    case_id = _create_case(client)
    r = _post(
        client,
        case_id,
        [
            (
                "note.eml",
                _eml(
                    "Confirmation de réception",
                    "Bonjour, merci de confirmer la réception de ce courriel.",
                ),
            )
        ],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["caseId"] == case_id
    result = body["files"][0]

    assert [stage["id"] for stage in result["stages"]] == [
        "received",
        "classified",
        "policy",
    ]
    assert all(stage["status"] == "success" for stage in result["stages"])
    assert result["status"] == "processed"
    assert result["policy"]["allowed"] is True
    # The verdict is explained, not merely asserted.
    assert result["actor"] in {
        "employer",
        "insurer",
        "union",
        "medical",
        "psychologist",
        "legal",
        "self",
        "unknown",
    }
    assert isinstance(result["labels"], list)
    # The message became case evidence, so the front door leads somewhere.
    assert result["evidenceId"]
    listed = client.get(f"/cases/{case_id}/evidence").json()
    assert [item["id"] for item in listed] == [result["evidenceId"]]


def test_privileged_message_is_rejected_by_policy_and_still_kept(client):
    """A policy rejection is the policy working, not a crash."""
    case_id = _create_case(client)
    r = _post(
        client,
        case_id,
        [
            (
                "demand.eml",
                _eml(
                    "Mise en demeure confidentielle",
                    "Vous devez répondre sans faute. Cette lettre est "
                    "confidentielle et sous seing privé.",
                    message_id="<m-priv@acme>",
                ),
            )
        ],
    )
    assert r.status_code == 200, r.text
    result = r.json()["files"][0]

    assert result["status"] == "rejected_policy"
    policy_stage = [s for s in result["stages"] if s["id"] == "policy"][0]
    assert policy_stage["status"] == "failed"
    assert result["policy"]["allowed"] is False
    assert result["policy"]["quarantine"] is True
    assert "Privileged" in result["policy"]["reason"]
    # Rejected, not discarded: the exhibit and its decision both survive.
    assert result["evidenceId"]
    audit = client.get(f"/cases/{case_id}/audit").json()
    actions = [row["event"] for row in audit]
    assert "email_intake_rejected_policy" in actions


def test_second_submission_is_reported_as_duplicate(client):
    case_id = _create_case(client)
    payload = [
        (
            "once.eml",
            _eml(
                "Confirmation de réception",
                "Bonjour, merci de confirmer la réception de ce courriel.",
                message_id="<dupe@acme>",
            ),
        )
    ]
    first = _post(client, case_id, payload)
    assert first.status_code == 200
    assert first.json()["files"][0]["status"] == "processed"

    second = _post(client, case_id, payload)
    assert second.status_code == 200
    result = second.json()["files"][0]
    assert result["status"] == "duplicate"
    skipped = [s for s in result["stages"] if s["status"] == "skipped"]
    assert {s["id"] for s in skipped} == {"classified", "policy"}
    # Only one exhibit: a duplicate must not double the case file.
    assert len(client.get(f"/cases/{case_id}/evidence").json()) == 1


def test_file_that_is_not_an_email_fails_at_the_first_stage(client):
    case_id = _create_case(client)
    r = _post(client, case_id, [("notes.eml", b"just some prose, no headers at all")])
    assert r.status_code == 200, r.text
    result = r.json()["files"][0]
    assert result["status"] == "failed"
    assert len(result["stages"]) == 1
    assert result["stages"][0]["id"] == "received"
    assert result["stages"][0]["status"] == "failed"
    assert result["reason"] == "NOT_AN_EMAIL"


def test_one_bad_file_does_not_abort_the_batch(client):
    case_id = _create_case(client)
    r = _post(
        client,
        case_id,
        [
            ("bad.eml", b"not a message"),
            (
                "good.eml",
                _eml(
                    "Confirmation de réception",
                    "Bonjour, merci de confirmer la réception de ce courriel.",
                    message_id="<good@acme>",
                ),
            ),
        ],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [f["status"] for f in body["files"]] == ["failed", "processed"]
    assert body["summary"] == {
        "processed": 1,
        "rejectedPolicy": 0,
        "duplicate": 0,
        "failed": 1,
    }


def test_empty_batch_is_refused(client):
    case_id = _create_case(client)
    r = client.post(f"/cases/{case_id}/intake/email")
    assert r.status_code == 422
    assert r.json()["error"] == "INVALID_REQUEST"


def test_unknown_case_is_not_found(client):
    r = _post(client, "no-such-case", [("x.eml", _eml("Hi", "Hello please respond."))])
    assert r.status_code == 404
    assert r.json()["error"] == "NOT_FOUND"
