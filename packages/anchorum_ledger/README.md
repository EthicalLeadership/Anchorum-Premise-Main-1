# Anchorum Ledger Proof Primitives

This package provides cryptographic foundations for the Anchorum Ledger Proof (ALP), a locally-verifiable timestamping system that does not require external blockchains or internet connectivity.

## Components

| Module | Function |
|--------|----------|
| [`canonical.py`](canononical.py) | RFC 8785 JSON canonicalization and SHA-256 hashing |
| [`merkle.py`](merkle.py) | Deterministic Merkle tree over message hashes |
| [`signing.py`](signing.py) | Ed25519 key generation, signing, and verification |
| [`snapshot.py`](snapshot.py) | Immutable `LedgerSnapshot` dataclass representing case state at a specific time |
| [`timestamp.py`](timestamp.py) | Local RFC 3161 Timestamp Authority using OpenSSL |
| [`tsa_export.py`](tsa_export.py) | Export helper: bundles trust material and timestamps into archives |

## Installation

```bash
pip install anchorum-ledger
```

Alternatively, install from the local workspace:

```bash
cd packages/anchorum_ledger
pip install -e .
```

## Usage Example

```python
from anchorum_ledger import (
    canonicalize,
    build_snapshot,
    stamp_bytes,
    verify,
)

# Create a snapshot of case state at a moment in time
snapshot = build_snapshot(
    case_id="c-1",
    as_of_utc="2026-11-16T12:34:56.789Z",
    messages=[{"message_id": "m-1", "text": "Hello"}],
)

# Canonicalize and hash the snapshot for signing
canonical_bytes = canonicalize(snapshot.to_canonical())
print("Canonical bytes:", canonical_bytes.hex()[:64])  # truncated
```

## License

Apache-2.0
