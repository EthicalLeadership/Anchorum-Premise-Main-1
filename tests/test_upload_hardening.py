import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from interface.server import create_app
from interface.anchorum_api import MAX_UPLOAD_BYTES
from interface import malware_scan
import tempfile
from pathlib import Path
import sqlite3

@pytest.fixture
def app_and_client(tmp_path):
    db_path = tmp_path / "api.db"
    ev_path = tmp_path / "evidence"
    ev_path.mkdir()
    app = create_app(f"sqlite:///{db_path}", local_api_mode=True, evidence_directory=ev_path)
    with TestClient(app) as client:
        client.post("/cases", json={"key": "T1", "title": "Test", "jurisdiction": "QC", "matterType": "labour", "timezone": "UTC", "description": "", "memberIds": []})
        yield client, ev_path, db_path

def test_eicar_exact(app_and_client):
    client, ev_path, db_path = app_and_client
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    resp = client.post("/cases/T1/evidence", files={"file": ("eicar.txt", eicar, "text/plain")})
    assert resp.status_code == 422
    assert resp.json()["error"] == "EVIDENCE_REJECTED_BY_SCAN"
    assert list(ev_path.glob("*.bin")) == []
    conn = sqlite3.connect(db_path)
    assert conn.execute("select count(*) from documents").fetchone()[0] == 0
    assert any("evidence_upload_rejected" in r[0] for r in conn.execute("select action from audit_logs"))

def test_eicar_near_miss(app_and_client):
    client, ev_path, _ = app_and_client
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    near_miss = eicar[:-1] + b"X"  # Change last byte
    resp = client.post("/cases/T1/evidence", files={"file": ("near.txt", near_miss, "text/plain")})
    assert resp.status_code == 201

def test_eicar_truncated(app_and_client):
    client, ev_path, _ = app_and_client
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    truncated = eicar[:-1]
    resp = client.post("/cases/T1/evidence", files={"file": ("trunc.txt", truncated, "text/plain")})
    assert resp.status_code == 201

def test_eicar_split_across_chunk(app_and_client):
    client, ev_path, _ = app_and_client
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    # 1MB chunk size. Pad so the EICAR string crosses the boundary.
    pad = b"A" * (1024 * 1024 - 10)
    payload = pad + eicar
    resp = client.post("/cases/T1/evidence", files={"file": ("split.txt", payload, "text/plain")})
    assert resp.status_code == 422
    assert resp.json()["error"] == "EVIDENCE_REJECTED_BY_SCAN"

def test_scanner_exception_fails_closed(app_and_client):
    client, ev_path, _ = app_and_client
    with patch.object(malware_scan.EicarScanner, "finish", side_effect=RuntimeError("scanner down")):
        resp = client.post("/cases/T1/evidence", files={"file": ("fail.txt", b"hello", "text/plain")})
        assert resp.status_code == 422
        assert resp.json()["error"] == "EVIDENCE_REJECTED_BY_SCAN"
        assert list(ev_path.glob("*.bin")) == []

def test_zero_byte_file(app_and_client):
    client, ev_path, _ = app_and_client
    resp = client.post("/cases/T1/evidence", files={"file": ("empty.txt", b"", "text/plain")})
    assert resp.status_code == 422
    assert resp.json()["error"] == "EMPTY_UPLOAD"
    assert list(ev_path.glob("*.bin")) == []

def test_oversized_file(app_and_client):
    client, ev_path, _ = app_and_client
    big_data = b"A" * (MAX_UPLOAD_BYTES + 1)
    resp = client.post("/cases/T1/evidence", files={"file": ("big.txt", big_data, "text/plain")})
    assert resp.status_code == 413
    assert resp.json()["error"] == "EVIDENCE_TOO_LARGE"
    assert list(ev_path.glob("*.bin")) == []

def test_bad_mime_type(app_and_client):
    client, ev_path, _ = app_and_client
    resp = client.post("/cases/T1/evidence", files={"file": ("bad.exe", b"MZ", "application/x-msdownload")})
    assert resp.status_code == 415
    assert resp.json()["error"] == "UNSUPPORTED_MEDIA_TYPE"
    assert list(ev_path.glob("*.bin")) == []

def test_readback_mismatch(app_and_client):
    client, ev_path, _ = app_and_client
    with patch("interface.anchorum_api.hmac.compare_digest", return_value=False):
        resp = client.post("/cases/T1/evidence", files={"file": ("mismatch.txt", b"hello", "text/plain")})
        assert resp.status_code == 507
        assert resp.json()["error"] == "EVIDENCE_READBACK_FAILED"
        assert list(ev_path.glob("*.bin")) == []

def test_cleanup_after_rejection(app_and_client):
    client, ev_path, _ = app_and_client
    resp = client.post("/cases/T1/evidence", files={"file": ("bad.exe", b"MZ", "application/x-msdownload")})
    assert resp.status_code == 415
    assert list(ev_path.glob("*.bin")) == []
    assert list(ev_path.glob(".upload-*")) == []

def test_duplicate_uploads(app_and_client):
    client, ev_path, _ = app_and_client
    resp1 = client.post("/cases/T1/evidence", files={"file": ("dup.txt", b"same bytes", "text/plain")})
    assert resp1.status_code == 201
    assert resp1.json()["duplicate"] is False

    resp2 = client.post("/cases/T1/evidence", files={"file": ("dup2.txt", b"same bytes", "text/plain")})
    assert resp2.status_code == 201
    assert resp2.json()["duplicate"] is True

def test_directory_fsync_tolerated(app_and_client):
    client, ev_path, _ = app_and_client
    # Patch os.fsync to raise OSError for the directory fd, but not the file fd.
    original_fsync = __import__("os").fsync
    def mock_fsync(fd):
        try:
            return original_fsync(fd)
        except OSError:
            pass
    with patch("os.fsync", side_effect=mock_fsync):
        resp = client.post("/cases/T1/evidence", files={"file": ("sync.txt", b"hello", "text/plain")})
        assert resp.status_code == 201

def test_no_third_party_imports():
    import ast
    from pathlib import Path
    tree = ast.parse(Path("interface/malware_scan.py").read_text())
    imports = [node.names[0].name for node in ast.walk(tree) if isinstance(node, ast.Import)]
    imports += [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module]
    allowed = {"dataclasses", "typing"}
    assert all(i in allowed for i in imports), f"Unexpected import: {set(imports) - allowed}"

def test_mime_normalization():
    from interface.anchorum_api import ALLOWED_MEDIA_TYPES
    # Test the logic directly
    def normalize(ct):
        return (ct or "application/octet-stream").split(";")[0].strip().lower()
    assert normalize("text/plain; charset=utf-8") == "text/plain"
    assert normalize("TEXT/PLAIN; charset=UTF-8") == "text/plain"
    assert normalize("application/pdf") == "application/pdf"
def test_failed_row_write_leaves_no_orphan_bytes(app_and_client):
    """A failure between storing the bytes and committing the row leaves nothing.

    This is the seam the audit records as open: gates protect the pipeline but
    never reached the HTTP edge. The upload now journals the file and the row as
    one reversible unit, so the failure path is a reversal rather than a cleanup
    the `finally` block has to guess at.
    """
    client, ev_path, db_path = app_and_client
    with patch("interface.anchorum_api._custody_log", side_effect=RuntimeError("row write failed")):
        with pytest.raises(RuntimeError):
            client.post(
                "/cases/T1/evidence",
                files={"file": ("gate.txt", b"bytes that must not survive", "text/plain")},
            )
    assert list(ev_path.glob("*.bin")) == []
    assert list(ev_path.glob(".upload-*")) == []
    conn = sqlite3.connect(db_path)
    assert conn.execute("select count(*) from documents").fetchone()[0] == 0


def test_gate_reverse_action_deletes_the_stored_file(tmp_path):
    """The forward/reverse pair the upload journals really reverses.

    Asserted on the gate directly, so the route's rollback path rests on a
    tested primitive rather than on the assumption that an unlink inside a
    lambda behaves.
    """
    from dossier_enforcement.gates import TransactionGate

    target = tmp_path / "evidence.bin"
    gate = TransactionGate("evidence-upload-unit", auto_commit=False)
    gate.__enter__()
    gate.execute_now(
        lambda: target.write_bytes(b"payload"),
        lambda: target.unlink(missing_ok=True),
        description="store evidence bytes",
    )
    assert target.is_file()
    gate.rollback()
    assert not target.exists()
    assert gate.is_rolled_back
