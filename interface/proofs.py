"""Cryptographic proof verification for one case.

Every proof here re-derives a value and compares it with what was stored. None
of them reads a stored verdict, because a stored verdict is exactly what an
attacker who can write to the database would edit first.

The proofs are pure: rows, byte strings and file paths come in, plain dicts go
out. No FastAPI, no SQLAlchemy session, no request. That is what makes them
testable at the level they claim to operate on — bytes and hashes — rather than
through an HTTP round trip that could pass for the wrong reason.

Results carry a machine-readable `code` instead of English prose, so the
interface can say the same thing in the reader's language.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_NOT_CHECKED = "not_checked"

#: The chain's genesis link. `_append_audit` writes an empty `previous_hash`
#: on a case's first row, so the recomputation starts there.
GENESIS_LINK = ""


@dataclass(frozen=True)
class Proof:
    """One verifiable claim about the case, and what re-deriving it found."""

    id: str
    status: str
    code: str
    failing_item: Optional[str] = None
    checked: int = 0

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "code": self.code,
            "failingItem": self.failing_item,
            "checked": self.checked,
        }


@dataclass(frozen=True)
class AuditRow:
    """The audit fields a chain proof needs, detached from the ORM."""

    id: int
    action: str
    details: str
    previous_hash: str
    record_hash: str
    hmac: str = ""


@dataclass(frozen=True)
class ContentItem:
    """An artifact's recorded identity, plus its bytes when they were readable."""

    document_key: str
    content_hash: str
    stored_bytes: Optional[bytes]


@dataclass(frozen=True)
class ProjectionRecord:
    """The rules/config hash an analysed artifact recorded."""

    document_key: str
    rules_hash: str
    config_hash: str


def compute_record_hash(previous_hash: str, action: str, details: str) -> str:
    """The chain function, written once and called from both sides.

    `details` is the exact stored string, not a re-serialized dict: key order
    and separators are part of the hashed content, and a JSON round trip would
    silently change the hash of a row that is in fact intact.
    """
    material = f"{previous_hash}|{action}|{details}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def chain_proof(rows: Sequence[AuditRow]) -> Proof:
    """Recompute every link and every record hash of the audit chain."""
    if not rows:
        return Proof("audit_chain", STATUS_NOT_CHECKED, "empty_chain")
    previous = GENESIS_LINK
    total = len(rows)
    for row in rows:
        label = f"log-{row.id}"
        if not row.record_hash:
            return Proof("audit_chain", STATUS_FAIL, "empty_hash", label, total)
        if row.previous_hash != previous:
            return Proof("audit_chain", STATUS_FAIL, "link_mismatch", label, total)
        expected = compute_record_hash(row.previous_hash, row.action, row.details)
        if expected != row.record_hash:
            return Proof("audit_chain", STATUS_FAIL, "hash_mismatch", label, total)
        previous = row.record_hash
    return Proof("audit_chain", STATUS_PASS, "ok", None, total)


def hmac_proof(
    rows: Sequence[AuditRow],
    verify: Optional[Callable[[str, str], bool]],
) -> Proof:
    """Verify each row's HMAC against the key the deployment actually holds.

    `verify(record_hash, signature) -> bool` is passed in rather than the
    signer itself, so a deployment with no key configured reports honestly
    instead of appearing to have checked signatures it never had.
    """
    if not rows:
        return Proof("audit_hmac", STATUS_NOT_CHECKED, "empty_chain")
    if verify is None:
        return Proof("audit_hmac", STATUS_NOT_CHECKED, "no_signing_key")
    total = len(rows)
    for row in rows:
        label = f"log-{row.id}"
        if not row.hmac:
            return Proof("audit_hmac", STATUS_FAIL, "unsigned_row", label, total)
        if not verify(row.record_hash, row.hmac):
            return Proof("audit_hmac", STATUS_FAIL, "signature_mismatch", label, total)
    return Proof("audit_hmac", STATUS_PASS, "ok", None, total)


def content_proof(items: Sequence[ContentItem]) -> Proof:
    """Re-hash each stored artifact and compare with its recorded digest."""
    if not items:
        return Proof("evidence_content", STATUS_NOT_CHECKED, "no_evidence")
    total = len(items)
    for item in items:
        if item.stored_bytes is None:
            return Proof(
                "evidence_content",
                STATUS_FAIL,
                "missing_bytes",
                item.document_key,
                total,
            )
        digest = hashlib.sha256(item.stored_bytes).hexdigest()
        if digest != item.content_hash:
            return Proof(
                "evidence_content",
                STATUS_FAIL,
                "content_mismatch",
                item.document_key,
                total,
            )
    return Proof("evidence_content", STATUS_PASS, "ok", None, total)


def projection_proof(
    records: Sequence[ProjectionRecord],
    *,
    expected_rules_hash: str,
    expected_config_hash: str,
) -> Proof:
    """Re-derive the CCSP rules/config hashes from the lexicon on disk.

    The recorded hashes are what the analysis claimed to have used. The engine
    built from today's lexicon produces the same values only if the rules and
    the engine configuration have not changed underneath the case — which is
    the question a reader of an exported index is entitled to have answered.
    """
    if not expected_rules_hash or not expected_config_hash:
        return Proof("projection_rules", STATUS_NOT_CHECKED, "engine_unavailable")
    analysed = [r for r in records if r.rules_hash or r.config_hash]
    if not analysed:
        return Proof("projection_rules", STATUS_NOT_CHECKED, "not_analysed")
    total = len(analysed)
    for record in analysed:
        if record.rules_hash != expected_rules_hash:
            return Proof(
                "projection_rules",
                STATUS_FAIL,
                "rules_mismatch",
                record.document_key,
                total,
            )
        if record.config_hash != expected_config_hash:
            return Proof(
                "projection_rules",
                STATUS_FAIL,
                "config_mismatch",
                record.document_key,
                total,
            )
    return Proof("projection_rules", STATUS_PASS, "ok", None, total)


def control_chain_proof(db_path: Optional[str]) -> Proof:
    """Verify the pipeline's own decision chain, when this host has one.

    Absence is reported as `not_checked`, never as `pass`: a product slice with
    no control plane has verified nothing, and the difference between "nothing
    to verify" and "everything verified" is the whole point of the badge.
    """
    if not db_path or not Path(db_path).is_file():
        return Proof("control_chain", STATUS_NOT_CHECKED, "no_control_chain")
    try:
        from dossier_pipeline.control import ControlPlane

        plane = ControlPlane(db_path)
    except Exception:
        # A configured-but-unusable chain (missing signing key, unreadable
        # file) is not evidence of tampering, so it is not a failure. It is
        # also not a pass, and the reason is reported.
        return Proof("control_chain", STATUS_NOT_CHECKED, "control_chain_unavailable")
    try:
        result = plane.verify_chain()
    except Exception:
        return Proof("control_chain", STATUS_NOT_CHECKED, "control_chain_unavailable")
    finally:
        plane.close()
    total = int(result.get("total_records") or 0)
    if total == 0:
        return Proof("control_chain", STATUS_NOT_CHECKED, "empty_control_chain")
    if not result.get("integrity_pass"):
        mismatches = result.get("mismatches") or []
        first = mismatches[0] if mismatches else {}
        label = f"{first.get('id')}:{first.get('field')}" if first else None
        return Proof("control_chain", STATUS_FAIL, "control_mismatch", label, total)
    return Proof("control_chain", STATUS_PASS, "ok", None, total)


def overall_status(proofs: Iterable[Proof]) -> str:
    """`fail` if any proof failed, else `pass` if any proof actually ran."""
    seen = list(proofs)
    if any(proof.status == STATUS_FAIL for proof in seen):
        return STATUS_FAIL
    if any(proof.status == STATUS_PASS for proof in seen):
        return STATUS_PASS
    return STATUS_NOT_CHECKED
