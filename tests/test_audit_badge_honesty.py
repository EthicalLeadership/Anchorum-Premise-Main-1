"""Badge honesty: 'Chain verified' must only show when the chain is intact.

Two gaps being closed:

  1. get_case_audit derives `chain` from `failingStep` (evidence verification
     outcome), not from record_hash/previous_hash. A case with 10 unchained
     rows shows "Chain verified" because no evidence_verified row failed.
  2. /export's inv_007 loop checks prev.record_hash == new.previous_hash but
     never checks that new.record_hash is non-empty. Two adjacent rows with
     record_hash="" and previous_hash="" pass the invariant.

This test:
  - uploads evidence (creates chained rows after the inv_007 fix)
  - corrupts one row's record_hash to ""
  - asserts get_case_audit exposes recordHash="" for that row
  - asserts get_case_audit returns chainIntegrity="broken" for that row
  - asserts /export refuses with 409 CUSTODY_CHAIN_BROKEN
"""

import sqlite3

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
        "key": "HONESTY-TEST", "title": "chain honesty",
        "jurisdiction": "QC", "matterType": "labour",
        "timezone": "UTC", "description": "", "memberIds": [],
    })
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _upload(client, case_id):
    r = client.post(
        f"/cases/{case_id}/evidence",
        files={"file": ("note.txt", b"Dr. Jean Dupont. Date: 2024-01-12.", "text/plain")},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _corrupt_row(db_path, action):
    """Set record_hash='' on the first row of the given action."""
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT id FROM audit_logs WHERE action = ? ORDER BY id LIMIT 1",
        (action,),
    ).fetchone()
    assert row, f"no audit_logs row with action {action}"
    row_id = row[0]
    conn.execute("UPDATE audit_logs SET record_hash = '' WHERE id = ?", (row_id,))
    conn.commit()
    conn.close()
    return row_id


def test_audit_route_exposes_chain_integrity(client_and_db):
    """get_case_audit must send recordHash, previousHash, chainIntegrity per row."""
    client, db_path = client_and_db
    case_id = _create_case(client)
    _upload(client, case_id)

    # Fresh case, all new rows chained. Expect: chainIntegrity="linked" everywhere.
    r = client.get(f"/cases/{case_id}/audit")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert rows, "no audit rows"
    for row in rows:
        assert "recordHash" in row, f"missing recordHash field: {row}"
        assert "previousHash" in row, f"missing previousHash field: {row}"
        assert "chainIntegrity" in row, f"missing chainIntegrity field: {row}"
        assert row["chainIntegrity"] == "linked", (
            f"fresh upload produced broken integrity on {row['event']}: {row}. "
            "All new rows should be chained after the inv_007 fix."
        )

    # Now corrupt one row.
    corrupted_id = _corrupt_row(db_path, "evidence_uploaded")

    r = client.get(f"/cases/{case_id}/audit")
    rows = r.json()
    corrupted = next(row for row in rows if row["id"] == f"log-{corrupted_id}")
    assert corrupted["recordHash"] == ""
    assert corrupted["chainIntegrity"] == "broken", (
        f"row with empty record_hash still reports linked: {corrupted}"
    )


def test_export_refuses_empty_record_hash(client_and_db):
    """Export must refuse when any row has empty record_hash.

    Today /export's inv_007 loop only checks prev.record_hash == new.previous_hash.
    A last row with record_hash='' and previous_hash='' passes if the prior
    row's hash was also '' (or if it's the first row). This test corrupts a row
    and asserts export 409s.
    """
    client, db_path = client_and_db
    case_id = _create_case(client)
    _upload(client, case_id)

    # Apply Barreau stamp so the route doesn't 403 on missing stamp.
    r = client.post(f"/cases/{case_id}/stamp", json={
        "stamp_version": "1.0", "approved_by": "test",
    })
    if r.status_code not in (200, 201):
        pytest.skip(f"cannot apply stamp: {r.status_code}: {r.text}")

    # Corrupt a row.
    _corrupt_row(db_path, "evidence_uploaded")

    r = client.post(f"/cases/{case_id}/export")
    assert r.status_code == 409, (
        f"export should refuse on empty record_hash, got {r.status_code}: {r.text}"
    )
    body = r.json()
    assert body.get("error") == "CUSTODY_CHAIN_BROKEN", (
        f"wrong error: {body}. Expected CUSTODY_CHAIN_BROKEN."
    )
