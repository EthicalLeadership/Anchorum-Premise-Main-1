"""End-to-end tests for /cases/{id}/audit/verify-proofs and the pre-flight gates.

Each test starts from a clean case and then breaks exactly one thing, because a
proof that only ever sees intact data proves nothing about its ability to see
damage.
"""
from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import select

from dossier_pipeline.schema import AuditLog, Document
from interface.server import create_app


def _app(tmp_path):
    return create_app(
        f"sqlite:///{tmp_path / 'api.db'}",
        local_api_mode=True,
        evidence_directory=tmp_path / "ev",
    )


def _new_case(client, key="P1"):
    client.post(
        "/cases",
        json={
            "key": key, "title": "Proofs", "jurisdiction": "QC",
            "matterType": "labour", "timezone": "UTC",
            "description": "", "memberIds": [],
        },
    )


def _session(client):
    return client.app.state.db_sessions()


def _proof_map(client, case_id) -> dict:
    response = client.post(f"/cases/{case_id}/audit/verify-proofs")
    assert response.status_code == 200, response.text
    body = response.json()
    by_id = {proof["id"]: proof for proof in body["proofs"]}
    by_id["__status"] = body["status"]
    return by_id


def test_verify_proofs_reports_each_proof(tmp_path, monkeypatch):
    # This deployment holds no signing secret, which is the state that must be
    # reported rather than glossed: "we signed it" and "we had no key" are not
    # the same sentence.
    monkeypatch.delenv("GDC_EVIDENCE_SECRET", raising=False)
    with TestClient(_app(tmp_path)) as client:
        _new_case(client)
        client.post(
            "/cases/P1/evidence",
            files={"file": ("a.txt", b"hello world", "text/plain")},
        )
        proofs = _proof_map(client, "P1")
        assert proofs["__status"] == "pass"
        assert proofs["audit_chain"]["status"] == "pass"
        assert proofs["evidence_content"]["status"] == "pass"
        # The lexicon on disk is the one the analysis recorded.
        assert proofs["projection_rules"]["status"] == "pass"
        assert proofs["audit_hmac"]["status"] == "not_checked"
        assert proofs["audit_hmac"]["code"] == "no_signing_key"
        # No control plane on this host either.
        assert proofs["control_chain"]["status"] == "not_checked"
        assert proofs["control_chain"]["code"] == "no_control_chain"


def test_verify_proofs_records_that_it_ran(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        _new_case(client)
        client.post(
            "/cases/P1/evidence",
            files={"file": ("a.txt", b"hello", "text/plain")},
        )
        client.post("/cases/P1/audit/verify-proofs")
        events = [row["event"] for row in client.get("/cases/P1/audit").json()]
        assert "proofs_verified" in events


def test_edited_audit_details_fail_the_chain_proof(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        _new_case(client)
        client.post(
            "/cases/P1/evidence",
            files={"file": ("a.txt", b"hello", "text/plain")},
        )
        client.post("/cases/P1/stamp", json={"approved_by": "Me. Tremblay"})

        session = _session(client)
        try:
            row = session.scalars(
                select(AuditLog)
                .where(AuditLog.action == "evidence_uploaded")
                .order_by(AuditLog.id.asc())
            ).first()
            row_id = row.id
            # Rewrite the payload and leave the stored hash alone: this is what
            # editing a row in place looks like.
            row.details = '{"evidenceId":"E-substituted"}'
            session.commit()
        finally:
            session.close()

        proofs = _proof_map(client, "P1")
        assert proofs["__status"] == "fail"
        assert proofs["audit_chain"]["status"] == "fail"
        assert proofs["audit_chain"]["code"] == "hash_mismatch"
        assert proofs["audit_chain"]["failingItem"] == f"log-{row_id}"

        preview = client.post("/cases/P1/exports/preview?type=evidence_index").json()
        assert preview["blocked"] is True

        # The export refuses. The link check alone would not have caught this:
        # previous_hash still matches, only the record payload changed.
        response = client.post("/cases/P1/export")
        assert response.status_code == 409
        assert response.json()["error"] == "EXPORT_PREFLIGHT_FAILED"


def test_substituted_evidence_bytes_fail_the_content_proof(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        _new_case(client)
        upload = client.post(
            "/cases/P1/evidence",
            files={"file": ("a.txt", b"hello", "text/plain")},
        )
        evidence_id = upload.json()["id"]

        session = _session(client)
        try:
            document = session.scalars(
                select(Document).where(Document.document_key == evidence_id)
            ).one()
            storage_key = document.storage_key
        finally:
            session.close()
        (tmp_path / "ev" / f"{storage_key}.bin").write_bytes(b"different bytes")

        proofs = _proof_map(client, "P1")
        assert proofs["evidence_content"]["status"] == "fail"
        assert proofs["evidence_content"]["code"] == "content_mismatch"
        assert proofs["evidence_content"]["failingItem"] == evidence_id
        assert proofs["__status"] == "fail"


def test_changed_rules_hash_fails_the_projection_proof(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        _new_case(client)
        client.post(
            "/cases/P1/evidence",
            files={"file": ("a.txt", b"hello", "text/plain")},
        )
        session = _session(client)
        try:
            document = session.scalars(select(Document)).one()
            document.analysis_rules_hash = "0" * 64
            session.commit()
        finally:
            session.close()

        proofs = _proof_map(client, "P1")
        assert proofs["projection_rules"]["status"] == "fail"
        assert proofs["projection_rules"]["code"] == "rules_mismatch"

        # Advisory: a rules-hash disagreement is reported, not treated as a
        # reason to withhold the evidence.
        preview = client.post("/cases/P1/exports/preview?type=evidence_index").json()
        gate = next(g for g in preview["gates"] if g["id"] == "projection_rules")
        assert gate["blocking"] is False
        assert gate["result"] == "fail"


def test_signed_rows_verify_and_a_tampered_signature_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("GDC_EVIDENCE_SECRET", "test-secret-for-proofs")
    with TestClient(_app(tmp_path)) as client:
        _new_case(client)
        client.post(
            "/cases/P1/evidence",
            files={"file": ("a.txt", b"hello", "text/plain")},
        )
        assert _proof_map(client, "P1")["audit_hmac"]["status"] == "pass"

        session = _session(client)
        try:
            row = session.scalars(
                select(AuditLog).order_by(AuditLog.id.asc())
            ).first()
            row.hmac = "0" * 64
            session.commit()
        finally:
            session.close()

        proofs = _proof_map(client, "P1")
        assert proofs["audit_hmac"]["status"] == "fail"
        assert proofs["audit_hmac"]["code"] == "signature_mismatch"


def test_export_manifest_carries_the_preflight_verdict(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        _new_case(client)
        client.post(
            "/cases/P1/evidence",
            files={"file": ("a.txt", b"hello", "text/plain")},
        )
        client.post("/cases/P1/stamp", json={"approved_by": "Me. Tremblay"})
        response = client.post("/cases/P1/export")
        assert response.status_code == 200, response.text
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        manifest = json.loads(archive.read("manifest.json"))
        gates = {gate["id"]: gate for gate in manifest["preflight"]["gates"]}
        assert gates["audit_chain"]["result"] == "pass"
        assert manifest["preflight"]["blocked"] is False
        summary = archive.read("SUMMARY.md").decode("utf-8")
        assert "## Pre-flight" in summary
