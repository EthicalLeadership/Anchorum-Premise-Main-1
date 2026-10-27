"""Anchoring: publish a case digest to DNS, and never claim more than happened.

The failures worth pinning are the quiet ones — an unconfigured host reporting
success, a provider rejection stored as if it were a publication, a digest that
keeps claiming to describe a case whose evidence has since changed.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from dossier_pipeline.schema import AuditLog
from interface import anchoring
from interface.server import create_app


def _app(tmp_path):
    return create_app(
        f"sqlite:///{tmp_path / 'api.db'}",
        local_api_mode=True,
        evidence_directory=tmp_path / "ev",
    )


def _new_case(client, key="A1"):
    client.post(
        "/cases",
        json={
            "key": key, "title": "Anchors", "jurisdiction": "QC",
            "matterType": "labour", "timezone": "UTC",
            "description": "", "memberIds": [],
        },
    )


def _upload(client, case_key="A1", name="exhibit.txt", body=b"the grievor was dismissed"):
    client.post(
        f"/cases/{case_key}/evidence",
        files={"file": (name, body, "text/plain")},
    )


def _audit_actions(client) -> list[str]:
    session = client.app.state.db_sessions()
    try:
        return [
            row.action
            for row in session.scalars(select(AuditLog).order_by(AuditLog.id.asc()))
        ]
    finally:
        session.close()


def test_digest_ignores_upload_order():
    first = anchoring.case_digest(["a" * 64, "b" * 64], "tip")
    second = anchoring.case_digest(["b" * 64, "a" * 64], "tip")
    assert first == second
    assert anchoring.case_digest(["a" * 64], "tip") != anchoring.case_digest(
        ["a" * 64], "other-tip"
    )


def test_record_name_is_dns_safe():
    name = anchoring.record_name_for("2026-0147 Dupont / ACME", "example.test")
    assert name.endswith(".example.test")
    assert " " not in name and "/" not in name


def test_corrupt_record_reads_as_not_anchored():
    assert anchoring.load_record("") is None
    assert anchoring.load_record("{not json") is None
    assert anchoring.load_record('{"recordName": "x"}') is None


def test_unconfigured_host_reports_unconfigured(tmp_path, monkeypatch):
    monkeypatch.delenv(anchoring.ZONE_ENV, raising=False)
    monkeypatch.delenv(anchoring.TOKEN_ENV, raising=False)
    with TestClient(_app(tmp_path)) as client:
        _new_case(client)
        body = client.get("/cases/A1/anchor").json()
        assert body["anchored"] is False
        assert body["configured"] is False
        assert body["expectedName"].endswith(anchoring.DEFAULT_ANCHOR_DOMAIN)

        response = client.post("/cases/A1/anchor")
        assert response.status_code == 501
        assert response.json()["error"] == "ANCHOR_NOT_CONFIGURED"


def test_publish_stores_the_public_record(tmp_path, monkeypatch):
    monkeypatch.setenv(anchoring.ZONE_ENV, "zone-1")
    monkeypatch.setenv(anchoring.TOKEN_ENV, "token-1")
    published: list[anchoring.AnchorRecord] = []

    def fake_publish(record, api_token):
        published.append(record)
        return True, ""

    monkeypatch.setattr(anchoring, "publish", fake_publish)

    with TestClient(_app(tmp_path)) as client:
        _new_case(client)
        _upload(client)
        response = client.post("/cases/A1/anchor")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["anchored"] is True
        assert body["stale"] is False
        assert body["configured"] is True
        assert body["recordContent"] == f"anchor={body['digest']}"
        assert published and published[0].zone_id == "zone-1"

        # A later read must report the same record, not re-derive a new one.
        read = client.get("/cases/A1/anchor").json()
        assert read["digest"] == body["digest"]
        assert "anchor_published" in _audit_actions(client)


def test_provider_rejection_is_not_recorded_as_a_publication(tmp_path, monkeypatch):
    monkeypatch.setenv(anchoring.ZONE_ENV, "zone-1")
    monkeypatch.setenv(anchoring.TOKEN_ENV, "token-1")
    monkeypatch.setattr(
        anchoring, "publish", lambda record, api_token: (False, "invalid token")
    )

    with TestClient(_app(tmp_path)) as client:
        _new_case(client)
        _upload(client)
        response = client.post("/cases/A1/anchor")
        assert response.status_code == 502
        assert response.json()["error"] == "ANCHOR_PUBLISH_FAILED"
        assert client.get("/cases/A1/anchor").json()["anchored"] is False
        actions = _audit_actions(client)
        assert "anchor_failed" in actions
        assert "anchor_published" not in actions


def test_anchor_without_evidence_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv(anchoring.ZONE_ENV, "zone-1")
    monkeypatch.setenv(anchoring.TOKEN_ENV, "token-1")
    def unexpected_publish(record, api_token):
        raise AssertionError("nothing should be published for a case with no evidence")

    monkeypatch.setattr(anchoring, "publish", unexpected_publish)

    with TestClient(_app(tmp_path)) as client:
        _new_case(client)
        response = client.post("/cases/A1/anchor")
        assert response.status_code == 409
        assert response.json()["error"] == "ANCHOR_NO_EVIDENCE"


def test_adding_evidence_makes_the_published_digest_stale(tmp_path, monkeypatch):
    monkeypatch.setenv(anchoring.ZONE_ENV, "zone-1")
    monkeypatch.setenv(anchoring.TOKEN_ENV, "token-1")
    monkeypatch.setattr(anchoring, "publish", lambda record, api_token: (True, ""))

    with TestClient(_app(tmp_path)) as client:
        _new_case(client)
        _upload(client, name="first.txt", body=b"first exhibit")
        assert client.post("/cases/A1/anchor").status_code == 200
        assert client.get("/cases/A1/anchor").json()["stale"] is False

        _upload(client, name="second.txt", body=b"second exhibit")
        after = client.get("/cases/A1/anchor").json()
        assert after["stale"] is True
        # The published value is left untouched: it is evidence, not state.
        assert after["digest"] != after["currentDigest"]
