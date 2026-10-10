"""Tests for anchor file self-hash verification.

Covers the fix: verify_anchor_file must refuse to return a payload whose
content does not match its stored anchor_hash. Prior to the fix it was a
bare JSON loader.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dossier_pipeline.anchor import (
    AnchorFileTampered,
    build_control_anchor,
    verify_anchor_file,
    write_anchor_file,
)
from dossier_pipeline.anchor_core import hash_payload


def _valid_payload() -> dict:
    body = {
        "namespace": "dossier_pipeline.anchor",
        "dossier_id": "TEST",
        "tail_hash": "aa" * 32,
        "record_count": 3,
        "merkle_root": "bb" * 32,
        "control_db_path": "/tmp/test_chain.db",
    }
    body["anchor_hash"] = hash_payload(body)
    return body


def _write(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "TEST_anchor.json"
    p.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")),
                 encoding="utf-8")
    return p


# --- verify_anchor_file -------------------------------------------------

def test_valid_file_returns_payload(tmp_path):
    payload = _valid_payload()
    p = _write(tmp_path, payload)
    got = verify_anchor_file(str(p))
    assert got["dossier_id"] == "TEST"
    assert got["anchor_hash"] == payload["anchor_hash"]


def test_field_tamper_detected(tmp_path):
    payload = _valid_payload()
    payload["tail_hash"] = "cc" * 32   # change the tail, keep the old hash
    p = _write(tmp_path, payload)
    with pytest.raises(AnchorFileTampered) as ei:
        verify_anchor_file(str(p))
    assert "mismatch" in str(ei.value).lower()


def test_missing_anchor_hash_detected(tmp_path):
    payload = _valid_payload()
    del payload["anchor_hash"]
    p = _write(tmp_path, payload)
    with pytest.raises(AnchorFileTampered) as ei:
        verify_anchor_file(str(p))
    assert "anchor_hash" in str(ei.value)


def test_non_object_json_detected(tmp_path):
    p = tmp_path / "list.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(AnchorFileTampered):
        verify_anchor_file(str(p))


def test_malformed_json_propagates(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        verify_anchor_file(str(p))


def test_missing_file_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        verify_anchor_file(str(tmp_path / "nope.json"))


# --- build/write/verify round trip --------------------------------------

class _FakeControl:
    def __init__(self, db_path: str, records: list[dict], tail: str):
        self.db_path = db_path
        self._records = records
        self._tail = tail

    def get_all_records(self):
        return list(self._records)

    def get_tail_hash(self):
        return self._tail

    def close(self):
        pass


def test_roundtrip_build_write_verify(tmp_path):
    fake = _FakeControl(
        db_path=str(tmp_path / "TEST_chain.db"),
        records=[{"record_hash": "aa" * 32}, {"record_hash": "bb" * 32}],
        tail="cc" * 32,
    )
    written = write_anchor_file(fake, output_dir=str(tmp_path))
    got = verify_anchor_file(written)
    # Round-trip identity holds.
    assert got["dossier_id"] == "TEST"
    assert got["tail_hash"] == "cc" * 32
    assert got["record_count"] == 2


# --- caller discipline: what does a caller see on each failure ----------

def test_tamper_is_distinguishable_from_missing(tmp_path):
    """A caller that wants to alarm on tamper but tolerate missing must be
    able to tell them apart. FileNotFoundError vs AnchorFileTampered."""
    missing = tmp_path / "absent.json"
    with pytest.raises(FileNotFoundError):
        verify_anchor_file(str(missing))

    payload = _valid_payload()
    payload["record_count"] = 999
    p = _write(tmp_path, payload)
    with pytest.raises(AnchorFileTampered):
        verify_anchor_file(str(p))
