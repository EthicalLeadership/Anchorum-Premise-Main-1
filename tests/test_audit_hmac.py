"""Wire 4: every audit row is HMAC-signed when a secret is configured.

Two properties, both fail-closed at the export gate:

  1. With GDC_EVIDENCE_SECRET set, every row written through _append_audit
     carries a signature that verifies against record_hash.
  2. /export refuses when any row's hmac is empty or does not verify. A
     tampered record_hash or hmac — the whole reason for the signature —
     must be detectable at export, not discovered later.

Without the secret configured, rows are stored with hmac="" and export is
permitted: HMAC enforcement is all-or-nothing per environment. This matches
the fail-closed-on-signing-keys convention of test_signing_keys_fail_closed.py:
the signer does not silently operate on an empty key.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from interface.server import create_app


SECRET = "unit-test-hmac-secret"


@pytest.fixture
def client_and_db(tmp_path, monkeypatch):
    monkeypatch.setenv("GDC_EVIDENCE_SECRET", SECRET)
    db_path = tmp_path / "api.db"
    app = create_app(
        f"sqlite:///{db_path}",
        local_api_mode=True,
        evidence_directory=tmp_path / "ev",
    )
    with TestClient(app) as c:
        r = c.post("/cases", json={
            "key": "HMAC-1", "title": "hmac test", "jurisdiction": "QC",
            "matterType": "labour", "timezone": "UTC",
            "description": "", "memberIds": [],
        })
        assert r.status_code in (200, 201), r.text
        c.post("/cases/HMAC-1/evidence",
               files={"file": ("n.txt", b"hello", "text/plain")})
        c.post("/cases/HMAC-1/stamp", json={
            "stamp_version": "1.0", "approved_by": "test",
        })
        yield c, db_path


def _rows(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT id, record_hash, hmac FROM audit_logs ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _corrupt(db_path, column, row_id, value=""):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(f"UPDATE audit_logs SET {column} = ? WHERE id = ?",
                     (value, row_id))
        conn.commit()
    finally:
        conn.close()


def test_append_signs_when_secret_set(client_and_db):
    _client, db_path = client_and_db
    rows = _rows(db_path)
    assert rows, "no audit rows written"
    for row_id, rh, hmac in rows:
        assert rh, f"row {row_id} has empty record_hash"
        assert hmac, f"row {row_id} has empty hmac — signer not applied"
        assert len(hmac) == 64, f"row {row_id} hmac not 64 hex chars: {hmac!r}"


def test_export_succeeds_with_signed_rows(client_and_db):
    client, _db = client_and_db
    r = client.post("/cases/HMAC-1/export")
    assert r.status_code == 200, r.text


def test_export_rejects_tampered_record_hash(client_and_db):
    client, db_path = client_and_db
    first_id = _rows(db_path)[0][0]
    _corrupt(db_path, "record_hash", first_id, value="0" * 64)
    r = client.post("/cases/HMAC-1/export")
    assert r.status_code == 409, r.text
    assert r.json().get("error") == "AUDIT_HMAC_INVALID", r.json()


def test_export_rejects_tampered_hmac(client_and_db):
    client, db_path = client_and_db
    first_id = _rows(db_path)[0][0]
    _corrupt(db_path, "hmac", first_id, value="f" * 64)
    r = client.post("/cases/HMAC-1/export")
    assert r.status_code == 409, r.text
    assert r.json().get("error") == "AUDIT_HMAC_INVALID", r.json()


def test_export_rejects_empty_hmac_when_secret_set(client_and_db):
    client, db_path = client_and_db
    first_id = _rows(db_path)[0][0]
    _corrupt(db_path, "hmac", first_id, value="")
    r = client.post("/cases/HMAC-1/export")
    assert r.status_code == 409, r.text
    assert r.json().get("error") == "AUDIT_HMAC_MISSING", r.json()


def test_export_without_secret_tolerates_empty_hmac(tmp_path, monkeypatch):
    # No secret: signing is off for the whole environment, so rows carry
    # hmac="" and /export must still succeed.
    monkeypatch.delenv("GDC_EVIDENCE_SECRET", raising=False)
    app = create_app(
        f"sqlite:///{tmp_path / 'a.db'}",
        local_api_mode=True,
        evidence_directory=tmp_path / "ev",
    )
    with TestClient(app) as c:
        c.post("/cases", json={
            "key": "HMAC-2", "title": "no secret", "jurisdiction": "QC",
            "matterType": "labour", "timezone": "UTC",
            "description": "", "memberIds": [],
        })
        c.post("/cases/HMAC-2/evidence",
               files={"file": ("n.txt", b"hello", "text/plain")})
        c.post("/cases/HMAC-2/stamp", json={
            "stamp_version": "1.0", "approved_by": "test",
        })
        r = c.post("/cases/HMAC-2/export")
        assert r.status_code == 200, r.text
