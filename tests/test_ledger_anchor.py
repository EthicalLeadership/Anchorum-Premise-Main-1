import subprocess
from pathlib import Path

import pytest

from interface.ledger.anchor import (
    AnchorError,
    AnchorUnavailable,
    resolve_ots_binary,
    stamp_bytes,
    verify,
)


def _fake_run(rc=0, stdout="", stderr="", create_ots=False):
    def fake(cmd, **kwargs):
        if create_ots and len(cmd) >= 3 and cmd[1] == "stamp":
            Path(cmd[2] + ".ots").write_bytes(b"fake-ots-bytes")
        return subprocess.CompletedProcess(cmd, rc, stdout, stderr)
    return fake


def test_resolve_ots_binary_missing(monkeypatch):
    monkeypatch.setattr("interface.ledger.anchor.shutil.which", lambda _: None)
    with pytest.raises(AnchorUnavailable, match="not found on PATH"):
        resolve_ots_binary()


def test_resolve_ots_binary_found(monkeypatch):
    monkeypatch.setattr(
        "interface.ledger.anchor.shutil.which", lambda _: "/usr/local/bin/ots"
    )
    assert resolve_ots_binary() == "/usr/local/bin/ots"


def test_stamp_bytes_writes_snapshot_and_invokes_ots(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "interface.ledger.anchor.shutil.which", lambda _: "/fake/ots"
    )
    calls = []

    def fake(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[2] + ".ots").write_bytes(b"fake-ots-bytes")
        return subprocess.CompletedProcess(cmd, 0, "stamped", "")

    monkeypatch.setattr("interface.ledger.anchor.subprocess.run", fake)

    result = stamp_bytes(b'{"a":1}', tmp_path, filename="snap.alp")

    assert result.snapshot_path == tmp_path / "snap.alp"
    assert result.snapshot_path.read_bytes() == b'{"a":1}'
    assert result.ots_path == tmp_path / "snap.alp.ots"
    assert result.ots_path.read_bytes() == b"fake-ots-bytes"
    assert calls == [["/fake/ots", "stamp", str(tmp_path / "snap.alp")]]


def test_stamp_bytes_nonzero_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "interface.ledger.anchor.shutil.which", lambda _: "/fake/ots"
    )
    monkeypatch.setattr(
        "interface.ledger.anchor.subprocess.run",
        _fake_run(rc=1, stderr="calendar unreachable"),
    )
    with pytest.raises(AnchorError, match="rc=1"):
        stamp_bytes(b"x", tmp_path, filename="snap.alp")


def test_stamp_bytes_success_without_ots_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "interface.ledger.anchor.shutil.which", lambda _: "/fake/ots"
    )
    monkeypatch.setattr(
        "interface.ledger.anchor.subprocess.run", _fake_run(rc=0)
    )
    with pytest.raises(AnchorError, match="does not exist"):
        stamp_bytes(b"x", tmp_path, filename="snap.alp")


def test_stamp_bytes_timeout_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "interface.ledger.anchor.shutil.which", lambda _: "/fake/ots"
    )

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["ots"], timeout=1)

    monkeypatch.setattr("interface.ledger.anchor.subprocess.run", timeout)
    with pytest.raises(AnchorError, match="timed out"):
        stamp_bytes(b"x", tmp_path, filename="snap.alp", timeout=1)


def _prepare_pair(tmp_path):
    original = tmp_path / "snap.alp"
    original.write_bytes(b"canonical-bytes")
    ots = tmp_path / "snap.alp.ots"
    ots.write_bytes(b"proof")
    return original, ots


def test_verify_confirmed(tmp_path, monkeypatch):
    _, ots = _prepare_pair(tmp_path)
    monkeypatch.setattr(
        "interface.ledger.anchor.shutil.which", lambda _: "/fake/ots"
    )
    monkeypatch.setattr(
        "interface.ledger.anchor.subprocess.run",
        _fake_run(
            rc=0,
            stdout=(
                "Success! Bitcoin block 925847 attests existence "
                "as of 2025-11-30\n"
            ),
        ),
    )

    result = verify(ots)

    assert result.status == "confirmed"
    assert result.bitcoin_block == 925847
    assert result.attested_at == "2025-11-30"


def test_verify_pending_is_not_failure(tmp_path, monkeypatch):
    _, ots = _prepare_pair(tmp_path)
    monkeypatch.setattr(
        "interface.ledger.anchor.shutil.which", lambda _: "/fake/ots"
    )
    monkeypatch.setattr(
        "interface.ledger.anchor.subprocess.run",
        _fake_run(rc=0, stdout="Pending confirmation in Bitcoin blockchain\n"),
    )

    result = verify(ots)

    assert result.status == "pending"
    assert result.bitcoin_block is None


def test_verify_failed_when_no_marker(tmp_path, monkeypatch):
    _, ots = _prepare_pair(tmp_path)
    monkeypatch.setattr(
        "interface.ledger.anchor.shutil.which", lambda _: "/fake/ots"
    )
    monkeypatch.setattr(
        "interface.ledger.anchor.subprocess.run",
        _fake_run(rc=1, stderr="Error: proof hash mismatch\n"),
    )

    result = verify(ots)

    assert result.status == "failed"
    assert result.bitcoin_block is None


def test_verify_requires_original_file(tmp_path, monkeypatch):
    ots = tmp_path / "snap.alp.ots"
    ots.write_bytes(b"proof")
    monkeypatch.setattr(
        "interface.ledger.anchor.shutil.which", lambda _: "/fake/ots"
    )
    with pytest.raises(AnchorError, match="original file missing"):
        verify(ots)


def test_verify_rejects_non_ots_suffix(tmp_path):
    f = tmp_path / "snap.alp"
    f.write_bytes(b"x")
    with pytest.raises(AnchorError, match="expected a .ots"):
        verify(f)


def test_round_trip_stamp_then_verify(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "interface.ledger.anchor.shutil.which", lambda _: "/fake/ots"
    )

    def fake(cmd, **kwargs):
        if cmd[1] == "stamp":
            Path(cmd[2] + ".ots").write_bytes(b"proof")
            return subprocess.CompletedProcess(cmd, 0, "stamped", "")
        return subprocess.CompletedProcess(
            cmd,
            0,
            "Success! Bitcoin block 925847 attests existence as of 2025-11-30\n",
            "",
        )

    monkeypatch.setattr("interface.ledger.anchor.subprocess.run", fake)

    stamped = stamp_bytes(b"canonical", tmp_path, filename="snap.alp")
    result = verify(stamped.ots_path)

    assert result.status == "confirmed"
    assert result.bitcoin_block == 925847
