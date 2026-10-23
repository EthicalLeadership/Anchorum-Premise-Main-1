"""inv_007: every audit row must be chained.

anchorum_api.py:1532 states the invariant: 'verify the audit chain links
from genesis to tip.' The chain is computed by _append_audit() at line 357
and stored in AuditLog.previous_hash / AuditLog.record_hash.

Three sites bypass _append_audit and write raw db.add(AuditLog(...)):
  390:  _custody_log          -> evidence_uploaded, evidence_analysed
  1644: export route          -> export_produced (case ZIP generated)
  1995: change_member_role    -> member_role_changed (privilege escalation)

All three are audit-worthy: upload events, the export itself, and role
changes. None is a candidate for exemption.

The runtime state that exposed the gap: audit_logs 12 rows, 2 chained,
10 unchained. The UI's 'Chain verified' badge would still render green
against that DB because AuditExports.tsx derives `chain` per row from
`failingStep`, not from `record_hash`.

This file uploads evidence and changes a role, then asserts every row in
audit_logs has a non-empty record_hash. Fails today.
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from interface.server import create_app


@pytest.fixture
def client_and_db(tmp_path):
    db_path = tmp_path / "api.db"
    app = create_app(
        f"sqlite:///{db_path}",
        local_api_mode=True,
        evidence_directory=tmp_path / "ev",
    )
    with TestClient(app) as c:
        yield c, db_path


def _create_case(client):
    r = client.post("/cases", json={
        "key": "INV007-TEST", "title": "inv_007 chain test",
        "jurisdiction": "QC", "matterType": "labour",
        "timezone": "UTC", "description": "", "memberIds": [],
    })
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_upload_produces_chained_audit_rows(client_and_db):
    """Uploading evidence must produce chained rows.

    Fails today because _custody_log writes raw db.add(AuditLog(...)).
    """
    client, db_path = client_and_db
    case_id = _create_case(client)

    r = client.post(
        f"/cases/{case_id}/evidence",
        files={"file": ("note.txt", b"Dr. Jean Dupont. Date: 2024-01-12.", "text/plain")},
    )
    assert r.status_code in (200, 201), r.text

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT id, action, record_hash FROM audit_logs WHERE action IN "
        "('evidence_uploaded', 'evidence_analysed', 'evidence_filed_with_date')"
    ).fetchall()
    conn.close()

    assert rows, "no upload-related audit rows written"
    unchained = [(r[0], r[1]) for r in rows if not r[2]]
    assert not unchained, (
        f"{len(unchained)} upload-related audit row(s) have empty record_hash "
        f"(violates inv_007): {unchained}. "
        "Fix: route _custody_log (line 390) through _append_audit."
    )


def test_export_produces_chained_audit_row(client_and_db):
    """The export route must write a chained `export_produced` row.

    Fails today because line 1644 writes raw db.add(AuditLog(...)).
    """
    client, db_path = client_and_db
    case_id = _create_case(client)

    # minimal upload so the export has something to zip
    client.post(
        f"/cases/{case_id}/evidence",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )

    # Export requires a Barreau stamp before it reaches the chain check
    # (403 EXPORT_BLOCKED_BARREAU otherwise). Same fixture as
    # test_export_refuses_empty_record_hash in this file.
    stamp = client.post(f"/cases/{case_id}/stamp", json={
        "stamp_version": "1.0", "approved_by": "test",
    })
    assert stamp.status_code in (200, 201), stamp.text

    r = client.post(f"/cases/{case_id}/export")
    assert r.status_code == 200, r.text

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT id, action, record_hash FROM audit_logs WHERE action = 'export_produced'"
    ).fetchall()
    conn.close()

    assert rows, "export succeeded but no export_produced audit row"
    unchained = [(r[0], r[1]) for r in rows if not r[2]]
    assert not unchained, (
        f"export_produced row(s) have empty record_hash (violates inv_007): "
        f"{unchained}. Fix: route the export route's db.add(AuditLog(...)) "
        "at line 1644 through _append_audit."
    )


def test_role_change_produces_chained_audit_row(client_and_db):
    """Changing a member's role must write a chained row.

    Fails today because line 1995 writes raw db.add(AuditLog(...)).
    """
    client, db_path = client_and_db
    case_id = _create_case(client)

    # invite a member so there is a target for the role change
    r = client.post("/admin/members/invitations", json={
        "email": "target@example.com", "role": "reviewer", "caseIds": [],
    })
    assert r.status_code in (200, 201), r.text
    member_id = r.json().get("id")
    assert member_id, f"no member id in response: {r.text}"

    r = client.patch(
        f"/admin/members/{member_id}/role",
        json={"role": "auditor", "reason": "test"},
    )
    assert r.status_code == 200, r.text

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT id, action, record_hash FROM audit_logs WHERE action = 'member_role_changed'"
    ).fetchall()
    conn.close()

    assert rows, "role change succeeded but no member_role_changed audit row"
    unchained = [(r[0], r[1]) for r in rows if not r[2]]
    assert not unchained, (
        f"member_role_changed row(s) have empty record_hash (violates inv_007): "
        f"{unchained}. Fix: route change_member_role's db.add(AuditLog(...)) "
        "at line 1995 through _append_audit."
    )
