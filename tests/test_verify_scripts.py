"""Tests for the three fresh-process verifier scripts.

Each test runs the script as a subprocess via the venv python, checks
exit code 0 for a valid artifact, then mutates and checks exit code 1.
"""
from __future__ import annotations
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dossier_pipeline.registry import keys as _keys
from dossier_pipeline.registry.audit import AuditLog
from dossier_pipeline.registry.entry import sign_entry, snapshot_hash
from dossier_pipeline.registry.trust import Signer, build_anchor, save_anchor


_REPO = Path(__file__).resolve().parent.parent
_VERIFY_ANCHOR = _REPO / "scripts" / "verify_anchor.py"
_VERIFY_REGISTRY = _REPO / "scripts" / "verify_registry.py"
_VERIFY_AUDIT = _REPO / "scripts" / "verify_audit_chain.py"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True,
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def fixtures(tmp_path):
    kd = tmp_path / "keys"
    root_kp = _keys.generate_keypair("root-A", root=kd)
    signer_kp = _keys.generate_keypair("signer-1", root=kd)

    anchor = build_anchor(
        root_ids=("root-A",),
        threshold=1,
        signers={
            signer_kp.signer_id: Signer(
                pubkey=signer_kp.public_key.public_bytes_raw().hex(),
                authorized_at=_now_iso(),
                revoked_at=None,
            ),
        },
        root_private_keys={"root-A": root_kp.private_key},
        anchor_seq=0,
    )

    anchor_path = tmp_path / "anchor.json"
    roots_path = tmp_path / "roots.txt"
    registry_path = tmp_path / "registry.jsonl"
    audit_path = tmp_path / "audit.jsonl"

    save_anchor(anchor, path=anchor_path)
    roots_path.write_text(
        f"root-A:{root_kp.public_key.public_bytes_raw().hex()}\n"
    )

    snap = {"engine_version": "ccsp-3.3.0", "vertical": "legal"}
    entry = sign_entry(
        config_hash=snapshot_hash(snap),
        vertical_id="legal",
        engine_version="ccsp-3.3.0",
        config_snapshot=snap,
        private_key=signer_kp.private_key,
        signer_id=signer_kp.signer_id,
    )
    registry_path.write_text(
        json.dumps(asdict(entry), sort_keys=True, separators=(",", ":")) + "\n"
    )

    log = AuditLog(audit_path)
    log.append({"projection_id": "p1"})
    log.append({"projection_id": "p2"})

    return {
        "anchor": anchor_path,
        "roots": roots_path,
        "registry": registry_path,
        "audit": audit_path,
    }


# --- verify_anchor ------------------------------------------------------

def test_verify_anchor_script_ok(fixtures):
    r = _run(_VERIFY_ANCHOR,
             "--anchor", str(fixtures["anchor"]),
             "--roots", str(fixtures["roots"]))
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "OK" in r.stdout
    assert "anchor_seq=0" in r.stdout


def test_verify_anchor_rejects_tampered_pubkey(fixtures):
    p = fixtures["anchor"]
    data = json.loads(p.read_text())
    sid = next(iter(data["signers"]))
    data["signers"][sid]["pubkey"] = "ff" * 32
    p.write_text(json.dumps(data))
    r = _run(_VERIFY_ANCHOR, "--anchor", str(p),
             "--roots", str(fixtures["roots"]))
    assert r.returncode == 1
    assert "FAIL" in r.stderr


def test_verify_anchor_rejects_wrong_roots(fixtures, tmp_path):
    wrong_kp = _keys.generate_keypair("wrong", root=tmp_path / "wrongk")
    wrong_roots = tmp_path / "wrong_roots.txt"
    wrong_roots.write_text(
        f"root-A:{wrong_kp.public_key.public_bytes_raw().hex()}\n"
    )
    r = _run(_VERIFY_ANCHOR,
             "--anchor", str(fixtures["anchor"]),
             "--roots", str(wrong_roots))
    assert r.returncode == 1


# --- verify_registry ----------------------------------------------------

def test_verify_registry_script_ok(fixtures):
    r = _run(_VERIFY_REGISTRY,
             "--anchor", str(fixtures["anchor"]),
             "--roots", str(fixtures["roots"]),
             "--registry", str(fixtures["registry"]))
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "OK" in r.stdout
    assert "1 entries" in r.stdout


def test_verify_registry_rejects_tampered_entry(fixtures):
    p = fixtures["registry"]
    lines = p.read_text().splitlines()
    row = json.loads(lines[0])
    row["vertical_id"] = "evil"
    lines[0] = json.dumps(row, sort_keys=True, separators=(",", ":"))
    p.write_text("\n".join(lines) + "\n")
    r = _run(_VERIFY_REGISTRY,
             "--anchor", str(fixtures["anchor"]),
             "--roots", str(fixtures["roots"]),
             "--registry", str(p))
    assert r.returncode == 1
    assert "FAIL" in r.stderr


def test_verify_registry_missing_file_is_ok(fixtures, tmp_path):
    r = _run(_VERIFY_REGISTRY,
             "--anchor", str(fixtures["anchor"]),
             "--roots", str(fixtures["roots"]),
             "--registry", str(tmp_path / "nonexistent.jsonl"))
    assert r.returncode == 0
    assert "empty" in r.stdout.lower() or "absent" in r.stdout.lower()


# --- verify_audit_chain -------------------------------------------------

def test_verify_audit_chain_script_ok(fixtures):
    r = _run(_VERIFY_AUDIT, "--audit", str(fixtures["audit"]))
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "OK" in r.stdout
    assert "2 audit entries" in r.stdout


def test_verify_audit_chain_rejects_broken_chain(fixtures):
    p = fixtures["audit"]
    lines = p.read_text().splitlines()
    lines.pop(0)
    p.write_text("\n".join(lines) + "\n")
    r = _run(_VERIFY_AUDIT, "--audit", str(p))
    assert r.returncode == 1
    assert "FAIL" in r.stderr


def test_verify_audit_chain_rejects_record_tampering(fixtures):
    p = fixtures["audit"]
    lines = p.read_text().splitlines()
    row = json.loads(lines[0])
    row["record"]["projection_id"] = "evil"
    lines[0] = json.dumps(row, sort_keys=True, separators=(",", ":"))
    p.write_text("\n".join(lines) + "\n")
    r = _run(_VERIFY_AUDIT, "--audit", str(p))
    assert r.returncode == 1
    assert "FAIL" in r.stderr


def test_verify_audit_chain_missing_file_is_ok(tmp_path):
    r = _run(_VERIFY_AUDIT, "--audit", str(tmp_path / "nonexistent.jsonl"))
    assert r.returncode == 0
    assert "empty" in r.stdout.lower() or "absent" in r.stdout.lower()
