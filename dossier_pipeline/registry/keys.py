"""Ed25519 key management.

Keys live under a directory (default: ./.anchorum/keys/).
One key = one signer identity. Signer IDs are strings, e.g. "kark-2026-09".
Private keys 0600. Public keys 0644.

Rotation: generate a new key with a new signer_id.

Revocation is deliberately not implemented here. It is a state transition on
the trust anchor (``trust.revoke`` sets the signer's ``revoked_at``), and it is
the store that refuses entries from a revoked signer.

This module used to offer a second, contradictory mechanism as well: it
appended signer IDs to a ``revoked_keys.txt`` beside the key directory. Nothing
called it, nothing enforced it, and no test covered it while ``store``
rejected revoked signers on the basis of the anchor and not the file. A dead
alternative to a live invariant is not harmless: it is what the next reader
adopts by mistake. It was removed (audit finding F-10) and this comment is the
only trace it should leave.
"""
from __future__ import annotations
import os, stat
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

DEFAULT_KEY_DIR = Path(".anchorum/keys")

_SIGNER_ID_RE = __import__("re").compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validate_signer_id(signer_id: str) -> str:
    """Reject anything that could escape the key directory.

    Rules: must start with an alphanumeric, must be 1..128 chars, and may
    only contain alphanumerics, dot, underscore, and hyphen. Notably:
      * no leading dot  -> blocks "..", ".hidden"
      * no "/" or "\\" -> blocks "..\\..", "/etc/passwd", "subdir/x"
    """
    if not isinstance(signer_id, str):
        raise ValueError(f"signer_id must be a str, got {type(signer_id).__name__}")
    if not _SIGNER_ID_RE.match(signer_id):
        raise ValueError(
            f"invalid signer_id {signer_id!r}: must match "
            r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
        )
    return signer_id

@dataclass(frozen=True)
class KeyPair:
    signer_id: str
    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey

def key_dir(root: Optional[Path] = None) -> Path:
    d = root or DEFAULT_KEY_DIR
    d.mkdir(parents=True, exist_ok=True)
    # K3: the directory holds private key material. Ensure 0700. Idempotent.
    try:
        os.chmod(d, stat.S_IRWXU)  # 0o700
    except OSError:
        # Non-POSIX filesystems: don't fail startup, callers can audit.
        pass
    if root is None:
        # Also tighten the .anchorum/ parent when using the default path.
        try:
            os.chmod(d.parent, stat.S_IRWXU)
        except OSError:
            pass
    return d

def generate_keypair(signer_id: str, *, root: Optional[Path] = None) -> KeyPair:
    _validate_signer_id(signer_id)
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    d = key_dir(root)
    priv_path = d / f"{signer_id}.priv"
    pub_path = d / f"{signer_id}.pub"

    priv_bytes = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )

    # K2: create the private key atomically with 0600 set from the outset.
    # The old write-then-chmod sequence left a window during which the file
    # existed with default permissions (typically 0644 with umask 022).
    # O_EXCL also gives us the "already exists" check for free.
    fd = os.open(priv_path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(priv_bytes)
    except Exception:
        priv_path.unlink(missing_ok=True)
        raise

    pub_path.write_bytes(pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ))
    os.chmod(pub_path, 0o644)
    return KeyPair(signer_id, priv, pub)

def load_private_key(signer_id: str, *, root: Optional[Path] = None) -> Ed25519PrivateKey:
    _validate_signer_id(signer_id)
    p = key_dir(root) / f"{signer_id}.priv"
    if not p.exists():
        raise FileNotFoundError(f"no private key for {signer_id!r} at {p}")
    return Ed25519PrivateKey.from_private_bytes(p.read_bytes())

def load_public_key(signer_id: str, *, root: Optional[Path] = None) -> Ed25519PublicKey:
    _validate_signer_id(signer_id)
    p = key_dir(root) / f"{signer_id}.pub"
    if not p.exists():
        raise FileNotFoundError(f"no public key for {signer_id!r} at {p}")
    return Ed25519PublicKey.from_public_bytes(p.read_bytes())

def list_signers(*, root: Optional[Path] = None) -> list[str]:
    return sorted(p.stem for p in key_dir(root).glob("*.pub"))

# Revocation of a signer is NOT defined here. Use trust.revoke to produce a new
# anchor with revoked_at set, and construct the store with that anchor; store
# refuses entries from a revoked signer. See the module docstring and F-10.
