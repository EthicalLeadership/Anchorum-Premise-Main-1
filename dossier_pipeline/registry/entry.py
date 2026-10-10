"""Signed registry entry. Unit of the append-only log."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from ._canonical import canonical_json, sha256_hex

ENTRY_VERSION = "1"

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

@dataclass(frozen=True)
class RegistryEntry:
    config_hash: str
    vertical_id: str
    engine_version: str
    config_snapshot: dict
    signed_at: str
    signer_id: str
    signature: str
    entry_version: str = ENTRY_VERSION

    def payload_for_signing(self) -> dict:
        d = asdict(self)
        d.pop("signature", None)
        return d

    def canonical_payload(self) -> bytes:
        return canonical_json(self.payload_for_signing()).encode("utf-8")

def sign_entry(*, config_hash, vertical_id, engine_version, config_snapshot,
               private_key: Ed25519PrivateKey, signer_id: str,
               signed_at: Optional[str] = None) -> RegistryEntry:
    unsigned = RegistryEntry(
        config_hash=config_hash, vertical_id=vertical_id,
        engine_version=engine_version, config_snapshot=config_snapshot,
        signed_at=signed_at or _now_iso(), signer_id=signer_id, signature="",
    )
    sig = private_key.sign(unsigned.canonical_payload())
    return RegistryEntry(
        config_hash=config_hash, vertical_id=vertical_id,
        engine_version=engine_version, config_snapshot=config_snapshot,
        signed_at=unsigned.signed_at, signer_id=signer_id, signature=sig.hex(),
    )

def verify_entry(entry: RegistryEntry, public_key: Ed25519PublicKey) -> bool:
    try:
        public_key.verify(bytes.fromhex(entry.signature), entry.canonical_payload())
        return True
    except (InvalidSignature, ValueError):
        return False

def snapshot_hash(snapshot: dict) -> str:
    return sha256_hex(canonical_json(snapshot).encode("utf-8"))
