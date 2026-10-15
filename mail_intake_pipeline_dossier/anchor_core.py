"""
Dossier DOSSIER-PIPELINE Anchoring Core

Merkle tree, hash utilities, and canonical payload construction for anchoring
the audit chain tail and evidence checkpoints.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable, List, Sequence


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(payload: Any) -> str:
    if is_dataclass(payload):
        payload = asdict(payload)
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def hash_payload(payload: Any) -> str:
    return sha256_hex(canonical_json(payload).encode("utf-8"))


def merkle_parent(left: str, right: str) -> str:
    return sha256_hex((left + right).encode("utf-8"))


def merkle_root(leaves: Sequence[str]) -> str:
    if not leaves:
        return sha256_hex(b"")
    level = list(leaves)
    while len(level) > 1:
        next_level: List[str] = []
        for index in range(0, len(level), 2):
            left = level[index]
            right = level[index + 1] if index + 1 < len(level) else left
            next_level.append(merkle_parent(left, right))
        level = next_level
    return level[0]


def build_anchor_payload(
    dossier_id: str,
    tail_hash: str,
    record_count: int,
    merkle_root_hash: str,
    namespace: str = "dossier_pipeline.anchor",
) -> Dict[str, Any]:
    return {
        "namespace": namespace,
        "dossier_id": dossier_id,
        "tail_hash": tail_hash,
        "record_count": record_count,
        "merkle_root": merkle_root_hash,
    }


def build_evidence_anchor_payload(
    dossier_id: str,
    chain_hashes: Iterable[str],
    namespace: str = "dossier_pipeline.anchor.evidence",
) -> Dict[str, Any]:
    hashes = list(chain_hashes)
    return {
        "namespace": namespace,
        "dossier_id": dossier_id,
        "packet_count": len(hashes),
        "merkle_root": merkle_root(hashes),
        "leaf_hashes": hashes,
    }
