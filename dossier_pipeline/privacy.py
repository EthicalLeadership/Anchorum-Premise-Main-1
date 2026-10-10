"""
Dossier DOSSIER-PIPELINE — Privacy Compliance Layer

Fail-closed intake gate for declared legal basis, purpose specification,
data minimization, retention scheduling, and access logging.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .contracts import EmailEnvelope


class PrivacyComplianceError(RuntimeError):
    """Raised when privacy metadata is missing or invalid."""


@dataclass(frozen=True)
class PrivacyAccessLogEntry:
    timestamp_utc: str
    message_id: str
    message_key: str
    legal_basis: str
    purpose: str
    reason: str
    excess_fields: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PrivacyComplianceDecision:
    allowed: bool
    reason: str
    legal_basis: str
    purpose: str
    retention_expiry: str
    excess_fields: List[str] = field(default_factory=list)
    access_log_entry: Optional[PrivacyAccessLogEntry] = None


class PrivacyComplianceLayer:
    """
    Validates intake metadata before an email may proceed further.

    Required metadata keys:
      - legal_basis
      - purpose
      - retention_expiry

    Optional metadata keys:
      - consent_status
      - allowed_fields
      - reason

    The layer rejects missing or malformed metadata and records a compact
    access log entry for every allowed ingestion.
    """

    REQUIRED_FIELDS = {"legal_basis", "purpose", "retention_expiry"}
    OPTIONAL_REASON_FIELDS = ("reason", "access_reason", "processing_reason")

    def __init__(self, access_log: Optional[List[Dict[str, Any]]] = None):
        self.access_log = access_log if access_log is not None else []

    def validate(self, envelope: EmailEnvelope, metadata: Dict[str, Any]) -> PrivacyComplianceDecision:
        missing = [field for field in self.REQUIRED_FIELDS if not str(metadata.get(field, "")).strip()]
        if missing:
            raise PrivacyComplianceError(f"Missing privacy metadata: {', '.join(sorted(missing))}")

        legal_basis = str(metadata.get("legal_basis", "")).strip()
        purpose = str(metadata.get("purpose", "")).strip()
        retention_expiry = str(metadata.get("retention_expiry", "")).strip()
        reason = self._extract_reason(metadata)

        self._validate_retention_expiry(retention_expiry)

        excess_fields = self._detect_excess_fields(envelope, metadata)
        if excess_fields:
            raise PrivacyComplianceError(
                "Data minimization violation: excess fields present: "
                + ", ".join(sorted(excess_fields))
            )

        access_log_entry = PrivacyAccessLogEntry(
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            message_id=envelope.message_id,
            message_key=envelope.message_key,
            legal_basis=legal_basis,
            purpose=purpose,
            reason=reason,
            excess_fields=excess_fields,
        )
        self.access_log.append(access_log_entry.__dict__)

        return PrivacyComplianceDecision(
            allowed=True,
            reason=reason,
            legal_basis=legal_basis,
            purpose=purpose,
            retention_expiry=retention_expiry,
            excess_fields=excess_fields,
            access_log_entry=access_log_entry,
        )

    def _extract_reason(self, metadata: Dict[str, Any]) -> str:
        for key in self.OPTIONAL_REASON_FIELDS:
            value = str(metadata.get(key, "")).strip()
            if value:
                return value
        return "privacy intake review"

    def _validate_retention_expiry(self, retention_expiry: str) -> None:
        try:
            parsed = datetime.datetime.fromisoformat(retention_expiry)
        except ValueError as exc:
            raise PrivacyComplianceError(
                "Invalid retention_expiry format; expected ISO-8601 datetime"
            ) from exc

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)

        if parsed <= datetime.datetime.now(datetime.timezone.utc):
            raise PrivacyComplianceError("Retention expiry must be in the future")

    def _detect_excess_fields(self, envelope: EmailEnvelope, metadata: Dict[str, Any]) -> List[str]:
        allowed_fields = metadata.get("allowed_fields")
        if allowed_fields is None:
            return []

        if not isinstance(allowed_fields, Iterable) or isinstance(allowed_fields, (str, bytes)):
            raise PrivacyComplianceError("allowed_fields must be a list of permitted envelope fields")

        allowed = {str(field).strip() for field in allowed_fields if str(field).strip()}
        envelope_fields = {
            "message_id",
            "subject",
            "sender",
            "recipient",
            "date",
            "body_text",
            "attachments",
            "raw_sha256",
            "message_key",
            "original_message_id",
            "ingest_timestamp",
        }

        allowed_without_required = allowed - {"legal_basis", "purpose", "retention_expiry", "reason", "access_reason", "processing_reason"}
        excess = sorted(field for field in envelope_fields if field not in allowed_without_required)
        return excess
