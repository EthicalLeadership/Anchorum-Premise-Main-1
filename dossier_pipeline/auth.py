"""
Dossier DOSSIER-PIPELINE — JWT Auth

Simple JWT issuance and verification helpers for governed API access.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Dict, Iterable, Optional

import jwt

MIN_SECRET_KEY_LENGTH = 32


class WeakSecretKey(ValueError):
    """Raised when a JWT signing secret is too short to be a secret at all."""


@dataclass(frozen=True)
class AuthToken:
    access_token: str
    token_type: str = "bearer"


def fingerprint_credential(credential: str) -> str:
    return sha256(credential.encode("utf-8")).hexdigest()


def _normalize_secret_key(secret_key: Optional[str]) -> str:
    """Return the signing key, or refuse to sign with a weak one.

    This used to SHA-256 any secret shorter than ``MIN_SECRET_KEY_LENGTH``.
    That made the value 64 characters long but added no entropy: a
    five-character password became a sixty-four-character digest that was
    still exactly as guessable, and the caller was never told. Hashing is not
    a way to manufacture a secret, so it is no longer attempted (audit
    finding F-18).

    A slow KDF (PBKDF2, scrypt, Argon2) was the alternative and was rejected.
    It treats the signing key as a human password, which is what made the
    original code look defensible; the key here is configuration, and the
    correct response to a configuration value with too little entropy is to
    reject it rather than to slow down whoever guesses it.

    Secrets of at least ``MIN_SECRET_KEY_LENGTH`` characters are returned
    unchanged, which is what the old code did too, so tokens signed with a
    properly-sized secret before this change still verify.
    """
    if secret_key is None:
        raise WeakSecretKey(
            "No JWT signing secret provided. A secret of at least "
            f"{MIN_SECRET_KEY_LENGTH} characters is required."
        )
    if len(secret_key) < MIN_SECRET_KEY_LENGTH:
        raise WeakSecretKey(
            f"JWT signing secret is {len(secret_key)} characters; at least "
            f"{MIN_SECRET_KEY_LENGTH} are required. Short secrets are no longer "
            "stretched with SHA-256, because that added length without entropy "
            "and hid the weakness instead of reporting it."
        )
    return secret_key


def issue_token(subject: str, secret_key: Optional[str], *, roles: Iterable[str], expires_minutes: int = 60) -> AuthToken:
    normalized_secret_key = _normalize_secret_key(secret_key)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "roles": list(roles),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
    }
    token = jwt.encode(payload, normalized_secret_key, algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return AuthToken(access_token=token)


def decode_token(token: str, secret_key: Optional[str]) -> Dict[str, Any]:
    normalized_secret_key = _normalize_secret_key(secret_key)
    decoded = jwt.decode(token, normalized_secret_key, algorithms=["HS256"])
    if not isinstance(decoded, dict):
        raise ValueError("Invalid token payload")
    return decoded


def has_role(payload: Dict[str, Any], role: str) -> bool:
    roles = payload.get("roles", [])
    return role in set(roles if isinstance(roles, list) else [])


def validate_bearer_token(token: str, secret_key: Optional[str], *, required_role: Optional[str] = None) -> Dict[str, Any]:
    payload = decode_token(token, secret_key)
    if required_role and not has_role(payload, required_role):
        raise PermissionError(f"Missing required role: {required_role}")
    return payload
