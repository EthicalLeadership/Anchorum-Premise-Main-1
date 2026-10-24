"""Export pre-flight: what a package must prove before it leaves the machine.

Two kinds of gate live here, and the difference is deliberate:

* a *blocking* gate stops the export. A broken audit chain or unreadable
  evidence means the package would misrepresent itself, so nothing is written.
* an *advisory* gate is reported and recorded in the manifest but does not
  stop the export. Incomplete provenance is the normal state of an uploaded
  exhibit, and an export that refuses every un-dated document is an export
  nobody can use. The reader is told, in the package itself, what is missing.

Previews and exports read the same gates from this module, so the preview
cannot promise an export that the export route then refuses.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from dossier_pipeline.contracts import ActorType, ClassificationResult, EmailEnvelope
from dossier_pipeline.provenance import ProvenanceCurator
from interface import proofs

RESULT_PASS = proofs.STATUS_PASS
RESULT_FAIL = proofs.STATUS_FAIL
RESULT_NOT_CHECKED = proofs.STATUS_NOT_CHECKED
#: Advisory outcome: the check ran and found something worth showing, but the
#: condition it found is normal and must not stop the export.
RESULT_WARN = "warn"


@dataclass(frozen=True)
class Gate:
    """One pre-flight check and what it found."""

    id: str
    result: str
    blocking: bool = True
    failing_item: Optional[str] = None
    detail: Optional[str] = None

    def as_dict(self) -> dict:
        payload = {
            "id": self.id,
            "result": self.result,
            "blocking": self.blocking,
            "failingItem": self.failing_item,
        }
        if self.detail:
            payload["detail"] = self.detail
        return payload


@dataclass(frozen=True)
class DossierItem:
    """What the dossier itself knows about one artifact.

    These are the fields the product actually holds. A field the connector
    could only invent is left empty rather than filled in, because the
    provenance check treats an invented value as an absent one anyway.
    """

    document_key: str
    filename: str
    content_hash: str
    date: str = ""
    author: str = ""
    issuer: str = ""


def envelope_for(item: DossierItem) -> EmailEnvelope:
    """The message envelope this artifact would have had, from stored facts.

    `message_id` and `subject` are observed: the digest of the bytes and the
    name the file arrived under. Sender, recipient and date are not, and are
    left empty when the analysis did not extract them.
    """
    return EmailEnvelope(
        message_id=f"sha256:{item.content_hash}",
        subject=item.filename,
        sender=item.author,
        recipient=item.issuer,
        date=item.date,
        body_text="",
    )


def _classification() -> ClassificationResult:
    """A classification honest about knowing nothing about an upload's actor."""
    return ClassificationResult(
        labels=[],
        confidence=1.0,
        actor=ActorType.UNKNOWN,
        reasoning=[],
        rule_hits=[],
    )


def provenance_gate(items: Sequence[DossierItem]) -> Gate:
    """Trace completeness of the dossier's own metadata, per artifact.

    Advisory by design: an exhibit with no extracted date is common and the
    export must still work. What the gate refuses to do is stay silent about
    it, or -- worse -- report a synthesised header as observed provenance.
    """
    if not items:
        return Gate("provenance", RESULT_NOT_CHECKED, False, None, "no_evidence")
    curator = ProvenanceCurator()
    classification = _classification()
    missing_union: set[str] = set()
    incomplete: list[str] = []
    for item in items:
        result = curator.curate(classification, envelope_for(item))
        if not result.complete:
            incomplete.append(item.document_key)
            missing_union.update(result.missing_fields)
    if not incomplete:
        return Gate("provenance", RESULT_PASS, False, None, "ok")
    fields = ",".join(sorted(missing_union))
    return Gate(
        "provenance",
        RESULT_WARN,
        False,
        f"{len(incomplete)}/{len(items)}",
        f"incomplete:{fields}",
    )


def gate_from_proof(proof: proofs.Proof, *, blocking: bool) -> Gate:
    """A proof as a pre-flight gate.

    A proof that could not run is reported as `not_checked`, never as a pass:
    "we verified it" and "we could not look" are different sentences and the
    preview must not merge them.
    """
    detail = proof.code
    if proof.status == RESULT_PASS:
        detail = "ok"
    failing = proof.failing_item if proof.status == RESULT_FAIL else None
    return Gate(proof.id, proof.status, blocking, failing, detail)


def blocked(gates: Sequence[Gate]) -> bool:
    """True when a blocking gate failed. Advisory results never block."""
    return any(gate.blocking and gate.result == RESULT_FAIL for gate in gates)


def manifest_record(gates: Sequence[Gate]) -> dict:
    """The pre-flight verdict as it is written into the export manifest."""
    return {
        "blocked": blocked(gates),
        "gates": [gate.as_dict() for gate in gates],
    }
