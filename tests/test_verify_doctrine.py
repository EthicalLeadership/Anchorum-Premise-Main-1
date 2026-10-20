import io
import json
import zipfile
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
        c.post("/cases", json={
            "key": "DOC1", "title": "Doctrine", "jurisdiction": "QC",
            "matterType": "labour", "timezone": "UTC",
            "description": "", "memberIds": [],
        })
        # Use text with actual doctrine terms so the projection is non-trivial.
        c.post("/cases/DOC1/evidence", files={
            "file": ("contract.txt",
                     b"The offer was accepted and consideration was given by the parties.",
                     "text/plain"),
        })
        yield c, db_path


def test_verify_doctrine_match_on_fresh_upload(client_and_db):
    client, _ = client_and_db
    items = client.get("/cases/DOC1/evidence").json()
    ev_id = items[0]["id"]
    r = client.post(f"/evidence/{ev_id}/verify-doctrine")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["match"] is True
    assert body["reason"] is None
    assert body["stored"] == body["recomputed"]


def test_verify_doctrine_detects_tampered_classification(client_and_db):
    client, db_path = client_and_db
    items = client.get("/cases/DOC1/evidence").json()
    ev_id = items[0]["id"]

    # Tamper: replace classification with a wrong one
    import sqlite3
    conn = sqlite3.connect(db_path)
    row = conn.execute("select analysis_json from documents where document_key = ?", (ev_id,)).fetchone()
    data = json.loads(row[0])
    data["doctrine"]["classification"] = "TAMPERED"
    conn.execute("update documents set analysis_json = ? where document_key = ?", (json.dumps(data), ev_id))
    conn.commit()
    conn.close()

    r = client.post(f"/evidence/{ev_id}/verify-doctrine")
    assert r.status_code == 200
    body = r.json()
    assert body["match"] is False
    assert body["reason"] == "classification_changed"


def test_verify_doctrine_rejects_unalysed(client_and_db):
    client, db_path = client_and_db
    items = client.get("/cases/DOC1/evidence").json()
    ev_id = items[0]["id"]

    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("update documents set analysis_json = '' where document_key = ?", (ev_id,))
    conn.commit()
    conn.close()

    r = client.post(f"/evidence/{ev_id}/verify-doctrine")
    assert r.status_code == 200
    body = r.json()
    assert body["match"] is False
    assert body["reason"] == "not_analysed"


def test_verify_doctrine_rejects_missing_bytes(client_and_db):
    """Deleting the stored bytes must yield 400 NO_STORED_BYTES, not a crash.

    This asserts a wire behaviour, so it goes through the route. The helper
    that resolves the path (`stored_evidence_path`) is a closure inside
    `create_app` and is not importable at module level; the storage root it
    reads is published on `app.state.evidence_directory`.
    """
    client, _ = client_and_db
    items = client.get("/cases/DOC1/evidence").json()
    ev_id = items[0]["id"]

    evidence_dir = client.app.state.evidence_directory
    deleted = 0
    for stored_file in evidence_dir.glob("*.bin"):
        stored_file.unlink()
        deleted += 1
    assert deleted == 1, f"expected one stored .bin, deleted {deleted}"

    r = client.post(f"/evidence/{ev_id}/verify-doctrine")
    assert r.status_code == 400, r.text
    assert r.json()["error"] == "NO_STORED_BYTES"
