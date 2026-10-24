"""Unit tests for the pure proof functions.

These do not touch HTTP or SQLAlchemy: each proof takes rows or bytes and
returns a verdict, so a failure here is unambiguously a logic failure rather
than a wiring one.
"""
from __future__ import annotations

from interface import preflight, proofs


def _chain(*rows: tuple[str, str]) -> list[proofs.AuditRow]:
    """Build a correctly chained set of rows from (action, details) pairs."""
    built: list[proofs.AuditRow] = []
    previous = ""
    for index, (action, details) in enumerate(rows, start=1):
        record = proofs.compute_record_hash(previous, action, details)
        built.append(
            proofs.AuditRow(
                id=index,
                action=action,
                details=details,
                previous_hash=previous,
                record_hash=record,
                hmac="",
            )
        )
        previous = record
    return built


def test_chain_proof_passes_on_a_correct_chain():
    rows = _chain(("case_created", "{}"), ("evidence_uploaded", '{"evidenceId":"E-1"}'))
    result = proofs.chain_proof(rows)
    assert result.status == proofs.STATUS_PASS
    assert result.checked == 2


def test_chain_proof_rejects_edited_details():
    rows = _chain(("case_created", "{}"), ("evidence_uploaded", '{"evidenceId":"E-1"}'))
    tampered = list(rows)
    tampered[1] = proofs.AuditRow(
        id=rows[1].id,
        action=rows[1].action,
        details='{"evidenceId":"E-2"}',
        previous_hash=rows[1].previous_hash,
        record_hash=rows[1].record_hash,
    )
    result = proofs.chain_proof(tampered)
    assert result.status == proofs.STATUS_FAIL
    assert result.code == "hash_mismatch"
    assert result.failing_item == f"log-{rows[1].id}"


def test_chain_proof_rejects_a_relinked_row():
    rows = _chain(("case_created", "{}"), ("evidence_uploaded", "{}"))
    tampered = list(rows)
    tampered[1] = proofs.AuditRow(
        id=rows[1].id,
        action=rows[1].action,
        details=rows[1].details,
        previous_hash="0" * 64,
        record_hash=rows[1].record_hash,
    )
    result = proofs.chain_proof(tampered)
    assert result.status == proofs.STATUS_FAIL
    assert result.code == "link_mismatch"


def test_chain_proof_on_no_rows_is_not_a_pass():
    result = proofs.chain_proof([])
    assert result.status == proofs.STATUS_NOT_CHECKED
    assert result.code == "empty_chain"


def test_hmac_proof_without_a_key_claims_nothing():
    rows = _chain(("case_created", "{}"))
    result = proofs.hmac_proof(rows, None)
    assert result.status == proofs.STATUS_NOT_CHECKED
    assert result.code == "no_signing_key"


def test_hmac_proof_rejects_an_unsigned_row():
    rows = _chain(("case_created", "{}"))
    result = proofs.hmac_proof(rows, lambda message, signature: True)
    assert result.status == proofs.STATUS_FAIL
    assert result.code == "unsigned_row"


def test_hmac_proof_rejects_a_bad_signature():
    rows = _chain(("case_created", "{}"))
    signed = [proofs.AuditRow(**{**row.__dict__, "hmac": "f" * 64}) for row in rows]
    result = proofs.hmac_proof(signed, lambda message, signature: False)
    assert result.status == proofs.STATUS_FAIL
    assert result.code == "signature_mismatch"


def test_hmac_proof_passes_with_a_matching_signature():
    rows = _chain(("case_created", "{}"))
    signed = [proofs.AuditRow(**{**row.__dict__, "hmac": "a" * 64}) for row in rows]
    result = proofs.hmac_proof(signed, lambda message, signature: signature == "a" * 64)
    assert result.status == proofs.STATUS_PASS


def test_content_proof_rejects_missing_bytes():
    result = proofs.content_proof(
        [proofs.ContentItem("E-1", "a" * 64, None)]
    )
    assert result.status == proofs.STATUS_FAIL
    assert result.code == "missing_bytes"
    assert result.failing_item == "E-1"


def test_content_proof_rejects_changed_bytes():
    result = proofs.content_proof(
        [proofs.ContentItem("E-1", "a" * 64, b"substituted")]
    )
    assert result.status == proofs.STATUS_FAIL
    assert result.code == "content_mismatch"


def test_content_proof_passes_on_matching_bytes():
    import hashlib

    payload = b"hello"
    result = proofs.content_proof(
        [proofs.ContentItem("E-1", hashlib.sha256(payload).hexdigest(), payload)]
    )
    assert result.status == proofs.STATUS_PASS


def test_projection_proof_reports_a_rules_change():
    result = proofs.projection_proof(
        [proofs.ProjectionRecord("E-1", "old", "cfg")],
        expected_rules_hash="new",
        expected_config_hash="cfg",
    )
    assert result.status == proofs.STATUS_FAIL
    assert result.code == "rules_mismatch"


def test_projection_proof_without_an_engine_claims_nothing():
    result = proofs.projection_proof(
        [proofs.ProjectionRecord("E-1", "old", "cfg")],
        expected_rules_hash="",
        expected_config_hash="",
    )
    assert result.status == proofs.STATUS_NOT_CHECKED
    assert result.code == "engine_unavailable"


def test_control_chain_absent_is_not_a_pass():
    result = proofs.control_chain_proof(None)
    assert result.status == proofs.STATUS_NOT_CHECKED
    assert result.code == "no_control_chain"


def test_overall_status_ignores_checks_that_never_ran():
    assert proofs.overall_status([
        proofs.Proof("a", proofs.STATUS_NOT_CHECKED, "no_evidence"),
        proofs.Proof("b", proofs.STATUS_NOT_CHECKED, "no_control_chain"),
    ]) == proofs.STATUS_NOT_CHECKED
    assert proofs.overall_status([
        proofs.Proof("a", proofs.STATUS_FAIL, "x"),
        proofs.Proof("b", proofs.STATUS_PASS, "ok"),
    ]) == proofs.STATUS_FAIL


def test_provenance_gate_passes_when_every_field_is_known():
    item = preflight.DossierItem(
        document_key="E-1",
        filename="letter.txt",
        content_hash="a" * 64,
        date="2026-01-02",
        author="Dr. Roy",
        issuer="Clinic",
    )
    assert preflight.provenance_gate([item]).result == preflight.RESULT_PASS


def test_provenance_gate_warns_without_blocking():
    item = preflight.DossierItem(
        document_key="E-1",
        filename="scan.pdf",
        content_hash="a" * 64,
    )
    gate = preflight.provenance_gate([item])
    assert gate.result == preflight.RESULT_WARN
    assert gate.blocking is False
    assert gate.failing_item == "1/1"
    assert "date" in (gate.detail or "")


def test_provenance_gate_with_no_evidence_is_not_checked():
    gate = preflight.provenance_gate([])
    assert gate.result == preflight.RESULT_NOT_CHECKED


def test_advisory_failure_does_not_block_the_export():
    advisory = preflight.Gate("provenance", preflight.RESULT_WARN, False, "1/1", "incomplete")
    blocking = preflight.Gate("audit_chain", "pass", True, None, "ok")
    assert preflight.blocked([advisory, blocking]) is False
    assert preflight.blocked([preflight.Gate("audit_chain", "fail", True, "log-3", "x")]) is True


def test_manifest_record_carries_every_gate():
    record = preflight.manifest_record(
        [preflight.Gate("audit_chain", "pass", True, None, "ok")]
    )
    assert record["blocked"] is False
    assert record["gates"][0]["id"] == "audit_chain"
    assert record["gates"][0]["blocking"] is True
