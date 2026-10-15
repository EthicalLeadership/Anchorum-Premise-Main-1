"""Document analysis: extract, segment, project, report coverage.

This is Tier 1 of the plan's two-tier architecture. It touches no signing
material, no FastAPI, no Session and no database: bytes in, a JSON-safe record
out. The API calls it; it knows nothing about the API.

Two error behaviours are deliberate, and neither is the "silence errors"
anti-pattern, because both are *recorded* and returned to the caller:

- an artifact the dispatcher cannot read (a `.docx`, a scan with no text layer)
  becomes ``status: "unsupported"`` carrying the dispatcher's own message, which
  names the artifact type;
- an unexpected failure becomes ``status: "failed"`` carrying the exception type
  and message, so the item never sits in a plausible-looking state that says
  nothing happened.
"""

from __future__ import annotations

import hashlib
from typing import Any

from interface import engine, scopes, submission
from interface.pdf_text import PdfTextError

#: Extraction ceiling. The same figure `intake.EmailIntake.ARCHIVE_MAX_BYTES`
#: uses. Above it extraction is recorded as skipped rather than attempted, so a
#: hostile upload cannot turn the single-process local API into a hang.
MAX_ANALYSIS_BYTES = 25 * 1024 * 1024

#: A submission at least this long that matches nothing is worth a warning.
#: Below it, "no concepts found" is unremarkable.
WARNING_MIN_CHARS = 500

#: A warning about a majority falling back needs at least this many scopes for
#: "the majority" to mean anything.
WARNING_MIN_SCOPES = 3

STATUS_PROCESSED = "processed"
STATUS_UNSUPPORTED = "unsupported"
STATUS_EMPTY = "empty"
STATUS_SKIPPED_OVERSIZE = "skipped_oversize"
STATUS_FAILED = "failed"

EXTRACT_EXTRACTED = "extracted"

FALLBACK = "canonical_projection_fallback"


def extract(data: bytes, filename: str = "") -> str:
    """Return the artifact's text, or raise the dispatcher's own refusal.

    Kept separate from :func:`analyse` so a caller that needs the text itself
    (the API, which stores it in a sidecar file) can get it without the text
    ever entering the analysis record. The record is what gets persisted and
    exported; document text must not ride along in it.
    """
    return submission.extract_text(data, filename)


def extract_or_empty(data: bytes, filename: str = "") -> str:
    """The artifact's text, or "" when no text can be produced from it.

    The API stores the text in a sidecar file so search has something to search.
    A refusal is not an error there: :func:`analyse` has already recorded it on
    the document row, and this call only decides whether a sidecar is written.
    An unexpected extractor failure is treated the same way for the same reason -
    the failure is recorded by :func:`analyse` on the same artifact, so raising
    here would only turn a recorded outcome into a 500 after the bytes and their
    custody row have already been committed.
    """
    try:
        return submission.extract_text(data, filename)
    except (submission.UnsupportedSubmission, PdfTextError):
        return ""
    except Exception:  # noqa: BLE001 - recorded by analyse, not swallowed
        return ""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_block(data: bytes, filename: str, media_type: str) -> dict[str, Any]:
    return {
        "sha256": _sha256(data),
        "bytes": len(data),
        "mediaType": media_type,
        "filename": filename,
    }


def _scope_record(scope: scopes.Scope) -> dict[str, Any]:
    """Project one scope and describe the outcome without embellishment."""
    text = scope.text.strip()
    if not text:
        return {
            "scope": scope.name,
            "chars": 0,
            "conceptId": None,
            "classification": "",
            "admissible": False,
            "matchedConcepts": [],
            "fallbackReason": "empty_scope",
        }
    projection = engine.project_text(text)
    return {
        "scope": scope.name,
        "chars": len(text),
        "conceptId": projection.concept_id,
        "classification": projection.classification,
        "admissible": projection.admissible,
        "matchedConcepts": sorted(projection.concept_distribution),
        "fallbackReason": projection.fallback_reason,
    }


def _coverage(records: list[dict[str, Any]], total_chars: int) -> dict[str, Any]:
    """Coverage is what stops empty scopes reading as "no legal concepts here".

    The engine is right to report `canonical_projection_fallback`: for the engine
    it means "no match", which is a legitimate outcome. What was missing is the
    product saying so. That is this block.
    """
    total = len(records)
    matched = sum(1 for record in records if record["conceptId"] is not None)
    fallback = sum(1 for record in records if record["classification"] == FALLBACK)
    insufficient = sum(
        1 for record in records if record["classification"].endswith("_insufficient")
    )

    warning: str | None = None
    if total and total_chars >= WARNING_MIN_CHARS:
        if matched == 0:
            warning = (
                f"the lexicon matched no concept in {total_chars} characters "
                f"across {total} scopes: this document's language is not covered"
            )
        elif total >= WARNING_MIN_SCOPES and fallback * 2 > total:
            warning = (
                f"the lexicon covered {matched} of {total} scopes; the remaining "
                f"{fallback} fell back to no-match rather than matching"
            )

    return {
        "scopesTotal": total,
        "scopesMatched": matched,
        "scopesFallback": fallback,
        "scopesInsufficient": insufficient,
        "ratio": (matched / total) if total else 0.0,
        "warning": warning,
    }


def analyse(
    data: bytes,
    filename: str = "",
    media_type: str = "",
    *,
    max_bytes: int = MAX_ANALYSIS_BYTES,
) -> dict[str, Any]:
    """Analyse one artifact and return the record the API serves.

    ``status`` values: ``processed``, ``unsupported``, ``empty``,
    ``skipped_oversize``, ``failed``.
    """
    source = _source_block(data, filename, media_type)

    def result(
        status: str,
        extract_status: str,
        reason: str = "",
        extract_error: str = "",
        text: str = "",
        records: list[dict[str, Any]] | None = None,
        engine_version: str = "",
        lexicon_hash: str = "",
        config_hash: str = "",
        doctrine: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope_records = records or []
        return {
            "status": status,
            "reason": reason,
            "source": source,
            "extract": {
                "status": extract_status,
                "chars": len(text),
                "sha256": _sha256(text.encode("utf-8")) if text else "",
                "error": extract_error,
            },
            "projection": {
                "engineVersion": engine_version,
                "lexiconHash": lexicon_hash,
                "configHash": config_hash,
            },
            "coverage": _coverage(scope_records, len(text)),
            "scopes": scope_records,
            # W5: the doctrine projection is additive. It sits beside the
            # risk projection; it never replaces or reshapes it. Every
            # record carries the key, so a consumer can read it without
            # branching on whether analysis ran (Shape 2, Phase 0.4).
            "doctrine": doctrine or {
                "conceptDistribution": {},
                "scopesMatched": 0,
                "engineVersion": "",
                "lexiconHash": "",
                "configHash": "",
                "classification": "",
                "fallbackReason": None,
            },
        }

    if len(data) > max_bytes:
        return result(
            STATUS_SKIPPED_OVERSIZE,
            STATUS_SKIPPED_OVERSIZE,
            reason=f"artifact is {len(data)} bytes, above the {max_bytes} byte analysis ceiling",
        )

    try:
        text = submission.extract_text(data, filename)
    except (submission.UnsupportedSubmission, PdfTextError) as refusal:
        return result(STATUS_UNSUPPORTED, STATUS_UNSUPPORTED, reason=str(refusal))
    except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
        # Segmentation failures below are recorded rather than raised; an
        # extractor failure must be too, or the record is never built and the
        # caller sees an exception while the document row keeps its defaults.
        # That is the plausible-looking state this module exists to prevent.
        return result(
            STATUS_FAILED,
            STATUS_FAILED,
            reason=f"{type(exc).__name__}: {exc}",
            extract_error=f"{type(exc).__name__}: {exc}",
        )

    if not text.strip():
        return result(STATUS_EMPTY, STATUS_EMPTY, reason="artifact produced no text")

    try:
        segmented = scopes.split_scopes(text)
        records = [_scope_record(scope) for scope in segmented]
    except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
        return result(
            STATUS_FAILED,
            STATUS_FAILED,
            reason=f"{type(exc).__name__}: {exc}",
            text=text,
            extract_error=f"{type(exc).__name__}: {exc}",
        )

    projections = [engine.project_text(scope.text.strip()) for scope in segmented if scope.text.strip()]
    first = projections[0] if projections else None

    # W5: parallel doctrine projection. Separate engine, separate lexicon,
    # aggregated to one document-level distribution. Failure of the doctrine
    # projection must not fail the whole analysis -- the risk projection is
    # the primary record, and a doctrine outage is reported as a reason on
    # the doctrine block, not as a 500 on the route.
    try:
        doctrine_projections = [
            engine.project_doctrine(scope.text.strip())
            for scope in segmented
            if scope.text.strip()
        ]
    except Exception as exc:  # noqa: BLE001 - recorded on the block, not swallowed
        doctrine_block: dict[str, Any] = {
            "conceptDistribution": {},
            "scopesMatched": 0,
            "engineVersion": "",
            "lexiconHash": "",
            "configHash": "",
            "classification": "unavailable",
            "fallbackReason": f"{type(exc).__name__}: {exc}",
        }
    else:
        dfirst = doctrine_projections[0] if doctrine_projections else None
        aggregate: dict[str, int] = {}
        for p in doctrine_projections:
            for k, v in (p.concept_distribution or {}).items():
                aggregate[k] = aggregate.get(k, 0) + v
        matched_scopes = sum(1 for p in doctrine_projections if p.concept_distribution)
        doctrine_block = {
            "conceptDistribution": aggregate,
            "scopesMatched": matched_scopes,
            "engineVersion": dfirst.engine_version if dfirst else "",
            "lexiconHash": dfirst.rules_hash if dfirst else "",
            "configHash": dfirst.config_hash if dfirst else "",
            "classification": dfirst.classification if dfirst else "",
            "fallbackReason": dfirst.fallback_reason if dfirst else None,
        }

    return result(
        STATUS_PROCESSED,
        EXTRACT_EXTRACTED,
        text=text,
        records=records,
        engine_version=first.engine_version if first else "",
        lexicon_hash=first.rules_hash if first else "",
        config_hash=first.config_hash if first else "",
        doctrine=doctrine_block,
    )
