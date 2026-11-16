# anchorum-ledger Package - Status Report

## Files Successfully Created

### Source Module (packages/anchorum_ledger/anchorum_ledger/)

| File | Status | Description |
|------|--------|-------------|
| `__init__.py` | ✓ Complete | Exports all public APIs from the package |
| `canonical.py` | ✓ Complete | RFC 8785 JSON canonicalization + SHA-256 hashing |
| `merkle.py` | ✓ Complete | Deterministic Merkle tree over SHA-256 leaves |
| `signing.py` | ✓ Complete | Ed25519 key generation, signing, verification |
| `snapshot.py` | ✓ Complete | Immutable `LedgerSnapshot` dataclass for ALP claims |
| `timestamp.py` | ✓ Complete | Local RFC 3161 TSA using OpenSSL (written directly) |
| `tsa_export.py` | ✓ Complete | Export helper bundling trust material + timestamps |

### Package Infrastructure

| File | Status | Description |
|------|--------|-------------|
| `pyproject.toml` | ✓ Created | Package metadata, dependencies, build config |
| `README.md` | ✓ Created | User-facing documentation with usage examples |
| `MANIFEST.in` | ✓ Created | File listing for wheel/build artifacts |

### Test Suite (packages/anchorum_ledger/tests/)

| File | Status | Content |
|------|--------|---------|
| `test_canonical.py` | ✓ Complete | Tests for canonical JSON serialization + hashing |
| `test_merkle.py` | ✓ Created | Tests for Merkle tree construction |
| `test_signing.py` | ✓ Complete | Tests for Ed25519 signing/verification |
| `test_timestamp.py` | Created | Placeholder tests (requires OpenSSL/certs) |
| `test_tsa_export.py` | Created | Placeholder tests |

## Files Still in interface/ledger/

The following files remain in the main project as they are **routers** (FastAPI route handlers), not ledger primitives:

- `anchor_router.py` - FastAPI router for anchor endpoints
- `timestamp_router.py` - FastAPI router for timestamp endpoints

These should NOT be copied into the ledger package.

## Verification Commands

```bash
# Test local imports
cd /home/kark/anchorum-prem-main(1)/anchorum-prem-main/packages/anchorum_ledger
python -c "from anchorum_ledger import canonicalize, build_snapshot; print('✓ Package imports correctly')"

# Run test suite
python -m pytest tests/test_canonical.py tests/test_signing.py tests/test_merkle.py -v --tb=short

# Install in editable mode
pip install -e .

# Build wheel for distribution
python -m build --wheel
```

## Docker Integration

The `Dockerfile` at the workspace root is configured to:

1. Use Python 3.12-slim base image
2. Set up virtual environment at `/venv`
3. Install system dependencies (build-essential, git, curl, openssl)
4. Copy all source code including ledger module from `interface/ledger/`
5. Install the ledger package in editable mode

To build and run:

```bash
cd /home/kark/anchorum-prem-main(1)/anchorum-prem-main
docker build -t anchorum-pipeline:latest .
docker run --rm anchorum-pipeline:latest python -m dossier_pipeline.main demo
```

## Usage Examples

### Canonical JSON & Hashing

```python
from anchorum_ledger import canonicalize, canonical_hash

obj = {"message_id": "m-1", "text": "Hello World"}
canonical_bytes = canonicalize(obj)
print(f"Canonical: {canonical_bytes.decode()}")
print(f"Hash: {canonical_hash(obj)}")
```

### Building a Snapshot

```python
from anchorum_ledger import build_snapshot, LedgerSnapshot
from datetime import datetime, timezone

snapshot = build_snapshot(
    case_id="c-1",
    as_of_utc=datetime.now(timezone.utc),
    messages=[{"message_id": "m-1", "text": "Hello"}],
)
print(f"Case {snapshot.case_id} snapshot: {len(snapshot.to_canonical())} canonical keys")
```

### Signing & Timestamping

```python
from anchorum_ledger import sign_bytes, verify
# Requires OpenSSL and TSA certificates configured in var/tsa/

data = b"Hello to be timestamped"
stamped_path = sign_bytes(data, "/tmp/timestamps")
is_verified = verify(stamped_path, "/tmp/snapshot.alp")
print(f"Verified: {is_verified}")
```

## License

Apache-2.0

## Contributing

1. Fork the repository
2. Create a feature branch
3. Write tests for your changes
4. Ensure all tests pass
5. Submit a pull request
