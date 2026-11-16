"""Anchorum Ledger Proof primitives.

This package provides cryptographic foundations for the Anchorum Ledger Proof:
- canonicalize(): Produce RFC 8785 canonical JSON bytes from a dict.
- canonical_hash(): SHA-256 of the canonical representation.
- merkle_root(): Deterministic Merkle tree over an ordered set of messages.
- LedgerSnapshot: An immutable claim snapshot that ALP signs and timestamps.
"""

from .canonical import canonicalize, canonical_hash
from .merkle import merkle_root
from .signing import load_private_key_pem, public_key_pem, sign_bytes
from .snapshot import LedgerSnapshot, build_snapshot, SNAPSHOT_VERSION
from .timestamp import stamp_bytes, verify, TimestampError
from .tsa_export import TSAOwnershipError, claim_tsa_owner

__all__ = [
    "canonicalize",
    "canonical_hash",
    "merkle_root",
    "load_private_key_pem",
    "public_key_pem",
    "sign_bytes",
    "LedgerSnapshot",
    "build_snapshot",
    "SNAPSHOT_VERSION",
    "stamp_bytes",
    "verify",
    "TimestampError",
    "TSAOwnershipError",
    "claim_tsa_owner",
]
