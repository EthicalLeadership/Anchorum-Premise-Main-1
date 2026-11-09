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

import json
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from dossier_pipeline.contracts import ActorType, ClassificationResult, EmailEnvelope
from dossier_pipeline.provenance import ProvenanceCurator
from interface.citation_validator import validate_citations_against_sources
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


def citation_validation_gate(
    documents: Sequence[object],
    sources: Mapping[str, Sequence[str]] | None = None,
) -> Gate:
    """Block export unless persisted AI citations and support match evidence."""
    sources = sources or {}
    outputs = 0
    invalid: list[str] = []

    def check_report(report: object, document_key: str) -> None:
        if not isinstance(report, dict) or not isinstance(report.get("valid"), bool):
            invalid.append(f"{document_key}:missing_validation_report")
        elif not report["valid"] or report.get("invalid_citations"):
            invalid.append(f"{document_key}:unverified_citations")
        elif not isinstance(report.get("parsed_citations"), list):
            invalid.append(f"{document_key}:missing_parsed_citations")

    for document in documents:
        document_key = getattr(document, "document_key", "<unknown>")
        for field in ("consultation_json", "summary_json"):
            serialized = getattr(document, field, None)
            if not serialized:
                continue
            outputs += 1
            try:
                record = json.loads(serialized)
            except (TypeError, ValueError):
                invalid.append(f"{document_key}:corrupt_{field}")
                continue
            if not isinstance(record, dict):
                invalid.append(f"{document_key}:invalid_{field}")
                continue

            if field == "consultation_json":
                report = record.get("_citation_validation_report")
                check_report(report, document_key)
                citations = (
                    report.get("parsed_citations", [])
                    if isinstance(report, dict)
                    and isinstance(report.get("parsed_citations"), list)
                    else []
                )
                if citations:
                    if any(not isinstance(citation, dict) for citation in citations):
                        invalid.append(f"{document_key}:invalid_parsed_citations")
                        continue
                    reconstructed = " ".join(
                        "[source: {file}, page {page}, lines {start}-{end}]".format(
                            file=citation.get("file", ""),
                            page=citation.get("page", ""),
                            start=citation.get("lines_start", ""),
                            end=citation.get("lines_end", ""),
                        )
                        for citation in citations
                    )
                    source_report = validate_citations_against_sources(
                        reconstructed, sources
                    )
                    if not source_report["valid"]:
                        invalid.append(f"{document_key}:unverified_source_reference")
                continue

            narrative = record.get("narrative")
            if isinstance(narrative, dict):
                report = narrative.get("_citation_validation_report")
                text = narrative.get("narrative")
            elif isinstance(narrative, str):
                report = None
                text = narrative
            else:
                invalid.append(f"{document_key}:invalid_summary_shape")
                continue

            if (
                isinstance(narrative, dict)
                and narrative.get("error")
                and not (isinstance(text, str) and text.strip())
            ):
                continue

            fresh_report: dict = {"parsed_citations": []}
            if report is not None:
                check_report(report, document_key)
            else:
                invalid.append(f"{document_key}:missing_validation_report")
            if isinstance(text, str) and text.strip():
                fresh_report = validate_citations_against_sources(text, sources)
                if not fresh_report["valid"]:
                    invalid.append(f"{document_key}:unverified_source_reference")
                elif not fresh_report["parsed_citations"]:
                    invalid.append(f"{document_key}:missing_citations")
            elif isinstance(narrative, dict) and narrative.get("error"):
                continue
            else:
                invalid.append(f"{document_key}:missing_narrative")

            support = record.get("citation_support")
            claims = support.get("claims") if isinstance(support, dict) else None
            if not isinstance(support, dict) or support.get("valid") is not True:
                invalid.append(f"{document_key}:semantic_support_unverified")
                continue
            if not isinstance(claims, list) or not claims:
                invalid.append(f"{document_key}:semantic_support_missing_claims")
                continue

            citations = fresh_report.get("parsed_citations", [])
            cited_lines = []
            for citation in citations:
                pages = sources.get(citation["file"])
                if pages is None or citation["page"] > len(pages):
                    continue
                lines = pages[citation["page"] - 1].splitlines()
                cited_lines.extend(
                    lines[citation["lines_start"] - 1 : citation["lines_end"]]
                )
            cited_text = " ".join(" ".join(cited_lines).split()).casefold()
            for claim in claims:
                quote = claim.get("quote") if isinstance(claim, dict) else None
                if (
                    not isinstance(claim, dict)
                    or claim.get("confidence") != "direct"
                    or not isinstance(quote, str)
                    or not quote.strip()
                    or " ".join(quote.split()).casefold() not in cited_text
                ):
                    invalid.append(f"{document_key}:claim_not_supported_by_cited_lines")
                    break

    if invalid:
        return Gate(
            "citations",
            RESULT_FAIL,
            True,
            f"{len(invalid)}",
            ",".join(invalid),
        )
    detail = "ok" if outputs else "no_generated_ai_outputs"
    return Gate("citations", RESULT_PASS, True, None, detail)
