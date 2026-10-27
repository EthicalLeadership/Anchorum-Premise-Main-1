"""Barreau credential validation for admin-initiated invites.
Framework-agnostic. Callers supply a registry and (optionally) an audit sink.
Never logs raw credentials or fingerprints.
"""
from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Protocol

BAR_ID_RE = re.compile(r"^[0-9]{7}$")


class Status(str, Enum):
    VALID = "valid"
    INVALID_FORMAT = "invalid_format"
    NOT_FOUND = "not_found"
    FINGERPRINT_MISMATCH = "fingerprint_mismatch"
    INACTIVE = "inactive"
    REGISTRY_ERROR = "registry_error"


@dataclass(frozen=True)
class BarreauCredential:
    bar_id: str
    fingerprint_hex: str


@dataclass(frozen=True)
class RegistryRecord:
    bar_id: str
    fingerprint_hex: str
    active: bool


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    status: Status
    bar_id_normalized: Optional[str] = None
    reason: str = ""

    @classmethod
    def fail(cls, status: Status, reason: str) -> "ValidationResult":
        return cls(ok=False, status=status, reason=reason)

    @classmethod
    def success(cls, bar_id: str) -> "ValidationResult":
        return cls(ok=True, status=Status.VALID, bar_id_normalized=bar_id)


class Registry(Protocol):
    def lookup(self, bar_id: str) -> Optional[RegistryRecord]: ...


class AuditSink(Protocol):
    def record(self, event: dict) -> None: ...


def _normalize_bar_id(raw: str) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    norm = raw.strip().upper()
    return norm if BAR_ID_RE.fullmatch(norm) else None


def _is_hex64(s: str) -> bool:
    if not isinstance(s, str) or len(s) != 64:
        return False
    try:
        int(s, 16)
    except ValueError:
        return False
    return True


class BarreauGate:
    def __init__(self, registry: Registry, audit: Optional[AuditSink] = None):
        self._registry = registry
        self._audit = audit

    def validate(
        self,
        credential: BarreauCredential,
        *,
        actor_id: str,
        now: Optional[datetime] = None,
    ) -> ValidationResult:
        now = now or datetime.now(timezone.utc)
        bar_id = _normalize_bar_id(credential.bar_id)

        if bar_id is None:
            result = ValidationResult.fail(Status.INVALID_FORMAT, "bar_id")
        elif not _is_hex64(credential.fingerprint_hex):
            result = ValidationResult.fail(Status.INVALID_FORMAT, "fingerprint")
        else:
            result = self._check_registry(bar_id, credential.fingerprint_hex)

        self._emit(result, actor_id=actor_id, bar_id=bar_id, now=now)
        return result

    def _check_registry(self, bar_id: str, fp: str) -> ValidationResult:
        try:
            record = self._registry.lookup(bar_id)
        except Exception:
            return ValidationResult.fail(Status.REGISTRY_ERROR, "registry unavailable")
        if record is None:
            return ValidationResult.fail(Status.NOT_FOUND, "not in registry")
        if not record.active:
            return ValidationResult.fail(Status.INACTIVE, "inactive")
        if not hmac.compare_digest(record.fingerprint_hex.lower(), fp.lower()):
            return ValidationResult.fail(Status.FINGERPRINT_MISMATCH, "mismatch")
        return ValidationResult.success(bar_id)

    def _emit(self, result, *, actor_id, bar_id, now):
        if self._audit is None:
            return
        self._audit.record({
            "event": "barreau_validation",
            "at": now.isoformat(),
            "actor_id": actor_id,
            "bar_id": bar_id,
            "ok": result.ok,
            "status": result.status.value,
        })
