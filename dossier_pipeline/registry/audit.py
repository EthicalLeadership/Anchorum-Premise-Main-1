"""Hash-chained audit log. Append-only. Tamper-evident."""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterator, Optional

from ._canonical import canonical_json, sha256_hex

DEFAULT_AUDIT_PATH = Path(".anchorum/audit.jsonl")

class AuditError(Exception): pass
class ChainBroken(AuditError): pass

@dataclass(frozen=True)
class AuditEntry:
    seq: int
    prev_hash: str
    record: dict
    record_hash: str
    entry_hash: str

def _entry_hash(seq: int, prev_hash: str, record_hash: str) -> str:
    payload = {"seq": seq, "prev_hash": prev_hash, "record_hash": record_hash}
    return sha256_hex(canonical_json(payload).encode("utf-8"))

def _record_hash(record: dict) -> str:
    return sha256_hex(canonical_json(record).encode("utf-8"))

class AuditLog:
    def __init__(self, path: Path = DEFAULT_AUDIT_PATH):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def _last_entry(self) -> Optional[AuditEntry]:
        if not self._path.exists():
            return None
        last = None
        with self._path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    last = json.loads(line)
        if last is None:
            return None
        return AuditEntry(**last)

    def append(self, record: dict) -> AuditEntry:
        last = self._last_entry()
        if last is None:
            seq, prev = 0, ""
        else:
            seq, prev = last.seq + 1, last.entry_hash
        rh = _record_hash(record)
        eh = _entry_hash(seq, prev, rh)
        entry = AuditEntry(seq=seq, prev_hash=prev, record=record,
                           record_hash=rh, entry_hash=eh)
        with self._path.open("a") as f:
            f.write(json.dumps(asdict(entry), sort_keys=True, separators=(",", ":")))
            f.write("\n")
        return entry

    def __iter__(self) -> Iterator[AuditEntry]:
        if not self._path.exists():
            return
        with self._path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    yield AuditEntry(**json.loads(line))

    def verify_chain(self) -> list[tuple[int, str]]:
        errors: list[tuple[int, str]] = []
        expected_seq = 0
        expected_prev = ""
        for e in self:
            if e.seq != expected_seq:
                errors.append((e.seq, f"expected seq {expected_seq}"))
            if e.prev_hash != expected_prev:
                errors.append((e.seq, f"prev_hash mismatch"))
            if e.record_hash != _record_hash(e.record):
                errors.append((e.seq, "record_hash mismatch"))
            if e.entry_hash != _entry_hash(e.seq, e.prev_hash, e.record_hash):
                errors.append((e.seq, "entry_hash mismatch"))
            expected_seq, expected_prev = e.seq + 1, e.entry_hash
        return errors

    def get(self, seq: int) -> AuditEntry:
        for e in self:
            if e.seq == seq:
                return e
        raise AuditError(f"no entry at seq={seq}")
