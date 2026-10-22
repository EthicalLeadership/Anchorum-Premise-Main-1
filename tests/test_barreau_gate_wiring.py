"""End-to-end: does /admin/members/invitations honor ANCHORUM_BARREAU_REQUIRED?

The BarreauGate module exists (dossier_pipeline/barreau_gate.py).
The UI collects a credential (Administration.tsx, field "member-credential").
The question this file answers: does the backend route actually read the flag
and validate the credential?

These are integration tests. If the route exists but does not call
BarreauGate, test_invite_without_credential_fails_when_required will fail
and that failure IS the wire. If it passes, the wire is already in place.

Run:
    .venv/bin/python -m pytest tests/test_barreau_gate_wiring.py -v
"""

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


def _invite_payload(**overrides):
    base = {
        "email": "advocate@example.com",
        "role": "reviewer",
        "caseIds": [],
    }
    base.update(overrides)
    return base


def test_invite_without_credential_fails_when_required(client, monkeypatch):
    """Flag set, no credential sent → route must reject with BARREAU_* error.

    If this FAILS with 200/201, the invite route does not enforce the gate
    even when ANCHORUM_BARREAU_REQUIRED=1. That is the wire.
    """
    monkeypatch.setenv("ANCHORUM_BARREAU_REQUIRED", "1")
    monkeypatch.setenv("ANCHORUM_BARREAU_ALLOWLIST", "")

    r = client.post("/admin/members/invitations", json=_invite_payload())
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}

    # FastAPI body-validation error: {"detail": [ {...}, ... ]}.
    # That means our payload shape is wrong, not that Barreau is broken.
    if isinstance(body.get("detail"), list):
        pytest.fail(
            "payload rejected by FastAPI (wrong body shape), not by Barreau. "
            f"Response: {body}. "
            "Check the route signature at anchorum_api.py:1904 — "
            "if it uses Form() not Body(), this test must use data= not json=."
        )

    assert r.status_code in (400, 422), (
        f"expected 400/422 (credential required when flag set), got "
        f"{r.status_code}: {body}. "
        "If this is 200/201, the route does not read ANCHORUM_BARREAU_REQUIRED — "
        "the wire is missing."
    )
    err = (body.get("error") or "").upper()
    assert "BARREAU" in err or "CREDENTIAL" in err, (
        f"rejected with the wrong error code: {body}. "
        "Expected BARREAU_CREDENTIAL_REQUIRED (or similar). "
        "A different 422 means the flag isn't wired as a Barreau check."
    )


def test_invite_with_credential_succeeds_when_required(client, monkeypatch):
    """Flag set, valid credential in allowlist → invite succeeds.

    If this fails after test_invite_without_credential passes, the gate is
    present but the allowlist comparison is broken (wrong fingerprint format,
    wrong env var name, or the credential isn't passed through).
    """
    try:
        from dossier_pipeline.barreau_gate import fingerprint_credential
    except ImportError:
        pytest.skip("fingerprint_credential helper not importable")

    raw = "VALID-CREDENTIAL-001"
    good = fingerprint_credential(raw)
    monkeypatch.setenv("ANCHORUM_BARREAU_REQUIRED", "1")
    monkeypatch.setenv("ANCHORUM_BARREAU_ALLOWLIST", good)

    # Try the credential as the raw string first; if rejected, try as the
    # fingerprint. One of the two is what the route compares against.
    r = client.post(
        "/admin/members/invitations",
        json=_invite_payload(credential=raw),
    )
    if r.status_code not in (200, 201):
        r = client.post(
            "/admin/members/invitations",
            json=_invite_payload(credential=good),
        )
    assert r.status_code in (200, 201), (
        f"expected 200/201 with valid credential, got {r.status_code}: {r.text}. "
        "The gate may be enforcing, but the allowlist format is off."
    )


def test_invite_without_credential_succeeds_when_not_required(client, monkeypatch):
    """Baseline: flag unset, no credential → invite succeeds. Should pass
    whether or not the gate is wired. Failure means something else broke."""
    monkeypatch.delenv("ANCHORUM_BARREAU_REQUIRED", raising=False)
    r = client.post("/admin/members/invitations", json=_invite_payload())
    assert r.status_code in (200, 201), (
        f"expected 200/201 with flag unset, got {r.status_code}: {r.text}"
    )
