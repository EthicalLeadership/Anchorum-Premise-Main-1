"""Tests for anchor_opentimestamps verify semantics.

Covers the F-class fix: verify_timestamp must never report VERIFIED when
the proof was not actually verified by the OpenTimestamps CLI.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from dossier_pipeline.anchor_opentimestamps import (
    PLACEHOLDER_STATUS,
    TimestampStatus,
    create_timestamp_request,
    is_available,
    verify_timestamp,
)


@pytest.fixture
def anchor_file(tmp_path):
    p = tmp_path / "anchor.bin"
    p.write_bytes(b"anchor payload")
    return p


def _no_ots(monkeypatch):
    """Simulate the OTS CLI being absent."""
    monkeypatch.setattr(shutil, "which", lambda name: None)


def _ots_present(monkeypatch, returncode=0, stdout="", stderr=""):
    """Simulate the OTS CLI being present with a controllable exit."""
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/ots")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)


# --- status detection ---------------------------------------------------

def test_missing_file_is_failed(tmp_path):
    status, msg = verify_timestamp(str(tmp_path / "nope.ots"))
    assert status is TimestampStatus.FAILED
    assert "Missing" in msg


def test_placeholder_is_pending_not_verified(anchor_file, tmp_path, monkeypatch):
    """The core regression: a placeholder must never verify as VERIFIED."""
    _no_ots(monkeypatch)
    out = create_timestamp_request(str(anchor_file))
    # File exists and is the JSON placeholder.
    data = json.loads(Path(out).read_text())
    assert data["status"] == PLACEHOLDER_STATUS

    status, msg = verify_timestamp(out)
    assert status is TimestampStatus.PENDING
    assert status is not TimestampStatus.VERIFIED
    assert "placeholder" in msg.lower()


def test_cli_unavailable_non_placeholder_is_unavailable(tmp_path, monkeypatch):
    """A non-placeholder file with no CLI is UNAVAILABLE, not VERIFIED."""
    _no_ots(monkeypatch)
    p = tmp_path / "proof.ots"
    p.write_bytes(b"some binary that isn't JSON")
    status, msg = verify_timestamp(str(p))
    assert status is TimestampStatus.UNAVAILABLE
    assert status is not TimestampStatus.VERIFIED


def test_cli_present_valid_proof_is_verified(tmp_path, monkeypatch):
    _ots_present(monkeypatch, returncode=0, stdout="OK\n")
    p = tmp_path / "proof.ots"
    p.write_bytes(b"real proof bytes")
    status, msg = verify_timestamp(str(p))
    assert status is TimestampStatus.VERIFIED
    assert "OK" in msg


def test_cli_present_bad_proof_is_failed(tmp_path, monkeypatch):
    _ots_present(monkeypatch, returncode=1, stdout="bad proof")
    p = tmp_path / "proof.ots"
    p.write_bytes(b"real proof bytes")
    status, msg = verify_timestamp(str(p))
    assert status is TimestampStatus.FAILED
    assert "bad proof" in msg


def test_cli_invocation_exception_is_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/ots")

    def boom(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(subprocess, "run", boom)
    p = tmp_path / "proof.ots"
    p.write_bytes(b"proof")
    status, msg = verify_timestamp(str(p))
    assert status is TimestampStatus.FAILED
    assert "ots invocation failed" in msg


# --- caller discipline check --------------------------------------------

def test_only_verified_is_truthy_verified(anchor_file, tmp_path, monkeypatch):
    """A caller that writes `if status is TimestampStatus.VERIFIED` gets
    the right answer. A caller doing `if status:` gets the wrong answer
    for PENDING/UNAVAILABLE that's why the docstring insists on identity
    comparison. This test pins the actual truthiness behaviour so a future
    reader can see it explicitly."""
    _no_ots(monkeypatch)
    out = create_timestamp_request(str(anchor_file))
    status, _ = verify_timestamp(out)
    # Enum members are truthy by default. The fix does NOT rely on
    # truthiness. Callers must compare by identity.
    assert status is TimestampStatus.PENDING
    # If a future change ever made non-VERIFIED statuses falsy, this
    # assertion would break and force a re-evaluation.
    assert bool(status) is True


# --- create_timestamp_request -------------------------------------------

def test_create_writes_placeholder_when_cli_absent(anchor_file, monkeypatch):
    _no_ots(monkeypatch)
    out = create_timestamp_request(str(anchor_file))
    data = json.loads(Path(out).read_text())
    assert data["status"] == PLACEHOLDER_STATUS
    assert "input_sha256" in data
    assert len(data["input_sha256"]) == 64


def test_create_writes_ots_file_when_cli_present(anchor_file, tmp_path, monkeypatch):
    """When the CLI is present and produces a file, we move it to
    output_path. Simulated by having fake_run create the .ots file."""
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/ots")
    anchor = anchor_file

    def fake_run(*args, **kwargs):
        # ots stamp writes <source>.ots next to source
        stamped = anchor.with_suffix(anchor.suffix + ".ots")
        stamped.write_bytes(b"real ots proof")
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = create_timestamp_request(str(anchor))
    assert Path(out).read_bytes() == b"real ots proof"
    # And verify sees it as non-placeholder
    status, _ = verify_timestamp(out)
    assert status is TimestampStatus.VERIFIED
