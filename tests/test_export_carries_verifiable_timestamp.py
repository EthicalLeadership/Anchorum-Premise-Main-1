"""An exported case must be verifiable by whoever receives it.

This is the product claim under test: hand the archive to opposing counsel and
they can check the timestamp with stock OpenSSL, without our code and without
us. The test therefore does exactly that: export, unpack, shell out to
`openssl ts -verify` using only files from the archive.

If the certificates or the stamped snapshot are missing from the archive, the
last two tests fail the same way a recipient's attempt would.
"""
import io
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from interface.server import create_app

REPO_TSA = Path("var/tsa")


class _Snapshot:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def canonical_bytes(self) -> bytes:
        return self._data


def _provision_tsa(evidence_dir: Path) -> None:
    if not (REPO_TSA / "ca.crt").is_file() or not (REPO_TSA / "tsa.crt").is_file():
        pytest.skip("TSA certificates not provisioned; run scripts/setup_local_tsa.sh")
    target = evidence_dir / "tsa"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("ca.crt", "tsa.crt", "tsa.cnf", "tsaserial"):
        source = REPO_TSA / name
        if source.is_file():
            shutil.copy(source, target / name)


@pytest.fixture
def exported(tmp_path):
    """A case with evidence, a stamp, and one local timestamp, exported to zip."""
    evidence_dir = tmp_path / "ev"
    app = create_app(
        f"sqlite:///{tmp_path / 'api.db'}",
        local_api_mode=True,
        evidence_directory=evidence_dir,
    )
    with TestClient(app) as client:
        client.post("/cases", json={
            "key": "TSA1", "title": "Timestamp pack", "jurisdiction": "QC",
            "matterType": "labour", "timezone": "UTC",
            "description": "", "memberIds": [],
        })
        client.post(
            "/cases/TSA1/evidence",
            files={"file": ("a.txt", b"hello timestamp", "text/plain")},
        )
        client.post("/cases/TSA1/stamp", json={"approved_by": "Me. Test"})

        _provision_tsa(evidence_dir)
        app.state.snapshot_builder = lambda case_id: _Snapshot(
            b'{"case":"TSA1","bytes":"canonical"}'
        )
        stamped = client.post("/ledger/snapshots/TSA1/timestamp")
        assert stamped.status_code == 200, stamped.text

        response = client.post("/cases/TSA1/export")
        assert response.status_code == 200, response.text
        yield zipfile.ZipFile(io.BytesIO(response.content))


def test_archive_ships_both_certificates(exported):
    names = exported.namelist()

    assert "trust/tsa.crt" in names
    assert "trust/ca.crt" in names


def test_archive_ships_the_stamped_snapshot_and_response(exported):
    names = exported.namelist()

    assert "trust/timestamps/snapshot.alp" in names
    assert "trust/timestamps/snapshot.alp.tsr" in names


def test_archive_explains_how_to_verify(exported):
    assert "trust/VERIFY_TIMESTAMP.md" in exported.namelist()


def test_archive_contains_no_private_keys(exported):
    assert not [name for name in exported.namelist() if name.endswith(".key")]


def test_recipient_can_verify_with_stock_openssl(exported, tmp_path):
    """The point of the export: verification with nothing but the archive."""
    unpacked = tmp_path / "unpacked"
    exported.extractall(unpacked)

    result = subprocess.run(
        [
            "openssl", "ts", "-verify",
            "-in", str(unpacked / "trust" / "timestamps" / "snapshot.alp.tsr"),
            "-data", str(unpacked / "trust" / "timestamps" / "snapshot.alp"),
            "-CAfile", str(unpacked / "trust" / "ca.crt"),
            "-untrusted", str(unpacked / "trust" / "tsa.crt"),
            "-no_nonce",
        ],
        capture_output=True,
    )
    combined = (result.stdout + result.stderr).decode(errors="replace")

    assert "Verification: OK" in combined, combined


def test_tampering_with_the_snapshot_breaks_verification(exported, tmp_path):
    """A pack that verifies everything is not evidence; the check must bite."""
    unpacked = tmp_path / "unpacked-tampered"
    exported.extractall(unpacked)
    snapshot = unpacked / "trust" / "timestamps" / "snapshot.alp"
    snapshot.write_bytes(b'{"case":"TSA1","bytes":"changed"}')

    result = subprocess.run(
        [
            "openssl", "ts", "-verify",
            "-in", str(unpacked / "trust" / "timestamps" / "snapshot.alp.tsr"),
            "-data", str(snapshot),
            "-CAfile", str(unpacked / "trust" / "ca.crt"),
            "-untrusted", str(unpacked / "trust" / "tsa.crt"),
            "-no_nonce",
        ],
        capture_output=True,
    )
    combined = (result.stdout + result.stderr).decode(errors="replace")

    assert "Verification: OK" not in combined
    assert result.returncode != 0
