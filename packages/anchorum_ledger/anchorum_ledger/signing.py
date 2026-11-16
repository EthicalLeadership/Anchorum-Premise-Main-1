"""Ed25519 signing for the Anchorum Ledger Proof.

Private key material never appears in exceptions or logs.
"""
import base64
from typing import Optional

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives import serialization
    from cryptography.exceptions import InvalidSignature
except ImportError as e:
    raise ImportError(
        "ALP Phase 1 requires 'cryptography'. "
        "Install with: pip install cryptography"
    ) from e


class SigningError(Exception):
    """Raised when signing or verification fails. Does not include key material."""


def load_private_key_raw(raw: bytes) -> Ed25519PrivateKey:
    """Load a 32-byte Ed25519 private key seed."""
    if not isinstance(raw, (bytes, bytearray)):
        raise SigningError("Private key must be bytes")
    if len(raw) != 32:
        raise SigningError(f"Private key must be exactly 32 bytes, got {len(raw)}")
    return Ed25519PrivateKey.from_private_bytes(bytes(raw))


def load_private_key_pem(
    pem: bytes, password: Optional[bytes] = None
) -> Ed25519PrivateKey:
    """Load a PEM-encoded Ed25519 private key."""
    try:
        key = serialization.load_pem_private_key(pem, password=password)
    except (ValueError, TypeError):
        raise SigningError("Failed to load PEM private key") from None
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningError("PEM did not contain an Ed25519 private key")
    return key


def public_key_pem(private_key: Ed25519PrivateKey) -> str:
    """Return the public key as PEM string."""
    pub = private_key.public_key()
    return pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def load_public_key_pem(pem: str) -> Ed25519PublicKey:
    """Load a PEM-encoded Ed25519 public key."""
    return serialization.load_pem_public_key(pem.encode("ascii"))


def sign(private_key: Ed25519PrivateKey, data: bytes) -> str:
    """Sign data. Returns base64 signature. Verifies before returning (ALP-1.3)."""
    signature_bytes = private_key.sign(data)
    signature_b64 = base64.b64encode(signature_bytes).decode("ascii")
    if not verify(private_key.public_key(), signature_b64, data):
        raise SigningError(
            "Internal error: signature did not verify against own public key"
        )
    return signature_b64


def verify(
    public_key: Ed25519PublicKey, signature_b64: str, data: bytes
) -> bool:
    """Verify a base64 signature. Returns True/False; never raises on bad signature."""
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (ValueError, TypeError):
        return False
    try:
        public_key.verify(signature, data)
        return True
    except InvalidSignature:
        return False
