"""RFC 8785 JSON Canonicalization for the Anchorum Ledger Proof.

Coverage:
- Object keys sorted (Python sort; UTF-16 order matches for ASCII keys)
- No whitespace between tokens
- UTF-8 output, non-ASCII preserved (no \\u escapes)
- Control characters escaped
- int and float distinguished (42 != 42.0)
- bool and int distinguished (true != 1)
- NaN and Infinity rejected

Out of scope for v1:
- Exact ECMAScript Number::toString for extreme floats
- 2^53 integer precision limit
- Unicode normalization
For ALP keys (message_id, source_sha256, etc.) these do not apply.
"""
import hashlib
import json
from typing import Any


def canonicalize(obj: Any) -> bytes:
    """Return RFC 8785 canonical UTF-8 bytes for obj."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(obj: Any) -> str:
    """SHA-256 of the canonical bytes, lowercase hex."""
    return hashlib.sha256(canonicalize(obj)).hexdigest()
