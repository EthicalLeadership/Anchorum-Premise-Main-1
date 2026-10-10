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


@dataclass(frozen=True)
class AuthToken:
    access_token: str
    token_type: str = "bearer"


def fingerprint_credential(credential: str) -> str:
    return sha256(credential.encode("utf-8")).hexdigest()


def _normalize_secret_key(secret_key: str) -> str:
    if len(secret_key) >= MIN_SECRET_KEY_LENGTH:
        return secret_key
    return sha256(secret_key.encode("utf-8")).hexdigest()


def issue_token(subject: str, secret_key: str, *, roles: Iterable[str], expires_minutes: int = 60) -> AuthToken:
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


def decode_token(token: str, secret_key: str) -> Dict[str, Any]:
    normalized_secret_key = _normalize_secret_key(secret_key)
    decoded = jwt.decode(token, normalized_secret_key, algorithms=["HS256"])
    if not isinstance(decoded, dict):
        raise ValueError("Invalid token payload")
    return decoded


def has_role(payload: Dict[str, Any], role: str) -> bool:
    roles = payload.get("roles", [])
    return role in set(roles if isinstance(roles, list) else [])


def validate_bearer_token(token: str, secret_key: str, *, required_role: Optional[str] = None) -> Dict[str, Any]:
    payload = decode_token(token, secret_key)
    if required_role and not has_role(payload, required_role):
        raise PermissionError(f"Missing required role: {required_role}")
    return payload
