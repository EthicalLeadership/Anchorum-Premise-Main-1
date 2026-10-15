"""End-to-end trace. Links projection_ids -> decision -> audit_seq."""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ._canonical import canonical_json, sha256_hex

DEFAULT_TRACE_PATH = Path(".anchorum/trace.jsonl")

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

@dataclass(frozen=True)
class TraceRecord:
    trace_id: str
    vertical_id: str
    projection_ids: tuple
    decision: dict
    decision_hash: str
    config_hash: str
    recorded_at: str
    audit_seq: Optional[int] = None

    @staticmethod
    def build(*, vertical_id, projection_ids, decision, config_hash, audit_seq=None):
        dh = sha256_hex(canonical_json(decision).encode("utf-8"))
        payload = {
            "vertical_id": vertical_id,
            "projection_ids": list(projection_ids),
            "decision_hash": dh,
            "config_hash": config_hash,
        }
        tid = sha256_hex(canonical_json(payload).encode("utf-8"))
        return TraceRecord(
            trace_id=tid, vertical_id=vertical_id,
            projection_ids=tuple(projection_ids), decision=decision,
            decision_hash=dh, config_hash=config_hash,
            recorded_at=_now_iso(), audit_seq=audit_seq,
        )

class TraceLog:
    def __init__(self, path: Path = DEFAULT_TRACE_PATH):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, rec: TraceRecord) -> None:
        with self._path.open("a") as f:
            f.write(json.dumps(asdict(rec), sort_keys=True, separators=(",", ":")))
            f.write("\n")

    def __iter__(self):
        if not self._path.exists():
            return
        with self._path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    d = json.loads(line)
                    d["projection_ids"] = tuple(d["projection_ids"])
                    yield TraceRecord(**d)

    def find_by_projection(self, projection_id: str):
        return [r for r in self if projection_id in r.projection_ids]

    def find_by_config(self, config_hash: str):
        return [r for r in self if r.config_hash == config_hash]
