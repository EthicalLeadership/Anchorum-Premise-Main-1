"""
Dossier DOSSIER-PIPELINE Barreau Gate

Credential gate that blocks API access unless the caller can present a valid
Barreau membership credential. This is intentionally separate from JWT auth so
the gate can be reused at the API edge and in service logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .auth import fingerprint_credential


@dataclass(frozen=True)
class BarreauGateResult:
    allowed: bool
    reason: str
    credential_fingerprint: str = ""


class BarreauGateError(PermissionError):
    pass


class BarreauGate:
    def __init__(self, allowed_fingerprints: Iterable[str]):
        self.allowed_fingerprints = set(allowed_fingerprints)

    def validate(self, credential: str) -> BarreauGateResult:
        fingerprint = fingerprint_credential(credential)
        if fingerprint not in self.allowed_fingerprints:
            raise BarreauGateError("Barreau credential rejected")
        return BarreauGateResult(
            allowed=True,
            reason="barreau credential accepted",
            credential_fingerprint=fingerprint,
        )
