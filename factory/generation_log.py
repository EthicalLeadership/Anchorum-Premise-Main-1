"""Append-only hash-chained generation log.

One JSON object per line at `<log_path>` (default: <factory_home>/generation_log.jsonl).

Each entry:

    {
      "seq": 42,
      "prev_hash": "hex64",         # entry_hash of previous, or "0"*64 for genesis
      "generation_id": "01J...",
      "gateway_name": "...",
      "factory_version": "0.3.0",
      "lifecycle": "DRAFT",
      "inputs_sha256": "hex64",
      "manifest_signature": "hex" | null,
      "recorded_at": "iso8601",
      "entry_hash": "hex64"         # sha256 of canonical JSON minus entry_hash
    }

Verification is a linear walk: recompute each entry_hash, confirm each
prev_hash matches the previous entry_hash. A tamper anywhere breaks the
chain at that point.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

GENESIS_PREV = "0" * 64


class LogError(Exception):
    pass


def _canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_hex(b: bytes) -> str:
    import hashlib
    return hashlib.sha256(b).hexdigest()


def _entry_hash(entry_no_hash: dict) -> str:
    return _sha256_hex(_canonical(entry_no_hash))


@dataclass(frozen=True)
class LogEntry:
    seq: int
    prev_hash: str
    generation_id: str
    gateway_name: str
    factory_version: str
    lifecycle: str
    inputs_sha256: str
    manifest_signature: str | None
    recorded_at: str
    entry_hash: str

    def to_json(self) -> dict:
        return {
            "seq": self.seq,
            "prev_hash": self.prev_hash,
            "generation_id": self.generation_id,
            "gateway_name": self.gateway_name,
            "factory_version": self.factory_version,
            "lifecycle": self.lifecycle,
            "inputs_sha256": self.inputs_sha256,
            "manifest_signature": self.manifest_signature,
            "recorded_at": self.recorded_at,
            "entry_hash": self.entry_hash,
        }

    def body(self) -> dict:
        return {k: v for k, v in self.to_json().items() if k != "entry_hash"}


def _last_entry(path: Path) -> LogEntry | None:
    if not path.is_file():
        return None
    last_line = ""
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                last_line = line
    if not last_line:
        return None
    return _parse_entry(json.loads(last_line), path)


def _parse_entry(data: dict, path: Path) -> LogEntry:
    required = {
        "seq": int, "prev_hash": str, "generation_id": str,
        "gateway_name": str, "factory_version": str, "lifecycle": str,
        "inputs_sha256": str, "recorded_at": str, "entry_hash": str,
    }
    for k, t in required.items():
        if not isinstance(data.get(k), t):
            raise LogError(f"{path}: entry missing or wrong-typed {k!r}")
    sig = data.get("manifest_signature")
    if sig is not None and not isinstance(sig, str):
        raise LogError(f"{path}: manifest_signature must be a string or null")
    return LogEntry(
        seq=data["seq"], prev_hash=data["prev_hash"],
        generation_id=data["generation_id"], gateway_name=data["gateway_name"],
        factory_version=data["factory_version"], lifecycle=data["lifecycle"],
        inputs_sha256=data["inputs_sha256"], manifest_signature=sig,
        recorded_at=data["recorded_at"], entry_hash=data["entry_hash"],
    )


def append(
    log_path: Path,
    *,
    generation_id: str,
    gateway_name: str,
    factory_version: str,
    lifecycle: str,
    inputs_sha256: str,
    manifest_signature: str | None,
) -> LogEntry:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    previous = _last_entry(log_path)
    seq = (previous.seq + 1) if previous else 1
    prev_hash = previous.entry_hash if previous else GENESIS_PREV
    body = {
        "seq": seq,
        "prev_hash": prev_hash,
        "generation_id": generation_id,
        "gateway_name": gateway_name,
        "factory_version": factory_version,
        "lifecycle": lifecycle,
        "inputs_sha256": inputs_sha256,
        "manifest_signature": manifest_signature,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    eh = _entry_hash(body)
    entry = LogEntry(entry_hash=eh, **body)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry.to_json(), sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return entry


def verify_chain(log_path: Path) -> tuple[bool, str, int]:
    """Return (ok, reason, n_entries)."""
    if not log_path.is_file():
        return False, f"log not found: {log_path}", 0
    expected_prev = GENESIS_PREV
    expected_seq = 1
    n = 0
    with log_path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                return False, f"line {lineno}: invalid JSON: {exc}", n
            entry = _parse_entry(data, log_path)
            if entry.seq != expected_seq:
                return False, (
                    f"line {lineno}: seq {entry.seq} does not match "
                    f"expected {expected_seq}"
                ), n
            if entry.prev_hash != expected_prev:
                return False, (
                    f"line {lineno}: prev_hash {entry.prev_hash!r} does not "
                    f"match previous entry_hash {expected_prev!r}"
                ), n
            recomputed = _entry_hash(entry.body())
            if recomputed != entry.entry_hash:
                return False, (
                    f"line {lineno}: entry_hash {entry.entry_hash!r} does "
                    f"not match content hash {recomputed!r}"
                ), n
            expected_prev = entry.entry_hash
            expected_seq += 1
            n += 1
    return True, "", n


def find_generation(log_path: Path, generation_id: str) -> LogEntry | None:
    if not log_path.is_file():
        return None
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            entry = _parse_entry(json.loads(line), log_path)
            if entry.generation_id == generation_id:
                return entry
    return None
