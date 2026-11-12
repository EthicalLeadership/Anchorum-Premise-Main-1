"""Deterministic Merkle tree over SHA-256 leaves.

Leaves MUST be lowercase hex strings of exactly 64 chars.
They are sorted before hashing so callers do not control order.
Duplicate last leaf on odd count (Bitcoin convention).
Empty input → sha256(b"") (null root convention).
"""
import hashlib
from typing import Sequence


def merkle_root(leaves: Sequence[str]) -> str:
    """Return the Merkle root as lowercase hex. Deterministic."""
    if not leaves:
        return hashlib.sha256(b"").hexdigest()

    for leaf in leaves:
        if not isinstance(leaf, str) or len(leaf) != 64:
            raise ValueError(
                f"Leaf must be 64-char hex string, got: "
                f"{type(leaf).__name__}"
                f"({len(leaf) if isinstance(leaf, str) else '?'})"
            )
        try:
            int(leaf, 16)
        except ValueError:
            raise ValueError(f"Leaf is not valid hex: {leaf[:16]}...")

    level = [bytes.fromhex(h) for h in sorted(leaves)]

    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [
            hashlib.sha256(level[i] + level[i + 1]).digest()
            for i in range(0, len(level), 2)
        ]

    return level[0].hex()
