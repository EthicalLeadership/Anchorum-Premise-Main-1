"""
Deterministic and Epistemic Tooling

Provides tools for computing execution context hashes and epistemic status.
These are used to ensure reproducible analysis and track knowledge claims.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def compute_execution_context_hash(dossier_id: Optional[str] = None, case_id: Optional[str] = None) -> str:
    """
    Compute deterministic hash of execution context.
    
    This hash captures all inputs that affect output determinism:
    - Config hashes (lexicon, prompts, engine settings)
    - Environment variables (model names, API endpoints)
    - System state (Python version, platform)
    
    The hash is computed once per dossier/case and cached.
    """
    
    # Capture environment (excluding secrets)
    env_snapshot = {
        "LEXICON_HASH": os.environ.get("LEXICON_HASH", ""),
        "CONFIG_HASH": os.environ.get("CONFIG_HASH", ""),
        "PROMPTS_HASH": os.environ.get("PROMPTS_HASH", ""),
        "CLF_MODEL": os.environ.get("CLF_MODEL", "llama3.1:8b"),
        "OLLAMA_URL": os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate"),
    }
    
    # Build hash input (sorted keys for determinism)
    hash_input = {
        "dossier_id": dossier_id or "",
        "case_id": case_id or "",
        **env_snapshot,
        "python_version": f"{__import__('sys').version_info.major}.{__import__('sys').version_info.minor}",
        "platform": f"{__import__('platform').system()}-{__import__('platform').machine()}",
    }
    
    # Compute SHA-256 hash
    sorted_input = json.dumps(hash_input, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(sorted_input.encode('utf-8')).hexdigest()


def get_epistemic_status(claim_text: str, source: str) -> Dict[str, Any]:
    """
    Get or create epistemic status for a claim.
    
    Returns a dictionary with:
    - claim_id: Unique identifier for this claim
    - claim_text: The claim being evaluated
    - source: Source of the claim
    - status: Current epistemic status (pending, verified, disputed, resolved)
    - rationale: Explanation for current status
    - evidence_items: Supporting evidence
    """
    
    # Generate unique claim ID from content
    content_hash = hashlib.sha256((claim_text + source).encode()).hexdigest()[:16]
    claim_id = f"epistemic-{content_hash}"
    
    return {
        "claim_id": claim_id,
        "claim_text": claim_text,
        "source": source,
        "status": "pending",
        "rationale": None,
        "evidence_items": [],
    }


def update_epistemic_status(
    claim: Dict[str, Any],
    new_status: str,
    rationale: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update epistemic status of a claim.
    
    Args:
        claim: Claim dictionary (must have 'claim_id' key)
        new_status: New status (pending, verified, disputed, resolved)
        rationale: Explanation for status change
    
    Returns:
        Updated claim dictionary
    """
    
    if "claim_id" not in claim:
        raise ValueError("Claim must have 'claim_id' key")
    
    # Map status strings to enum values
    valid_statuses = ["pending", "verified", "disputed", "resolved", "withdrawn"]
    if new_status not in valid_statuses:
        raise ValueError(f"Invalid status: {new_status}. Must be one of {valid_statuses}")
    
    # Update claim
    claim["status"] = new_status
    claim["rationale"] = rationale or f"Status changed to {new_status}"
    claim["status_changed_at"] = datetime.now(timezone.utc).isoformat()
    claim["changed_by"] = os.environ.get("USER", "system")
    
    return claim


def add_epistemic_fields_to_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add epistemic fields to a record for API response.
    
    This ensures all records include deterministic and epistemic metadata.
    """
    
    # Compute execution context hash if not present
    if "execution_context_hash" not in record:
        record["execution_context_hash"] = compute_execution_context_hash(
            dossier_id=record.get("dossier_id"),
            case_id=record.get("case_id"),
        )
    
    # Add epistemic status for claims
    if "claims" in record and isinstance(record["claims"], list):
        for claim in record["claims"]:
            if "status" not in claim:
                claim["status"] = "pending"
            if "claim_id" not in claim:
                claim["claim_id"] = f"epistemic-{hashlib.sha256(claim.get('text', '')).hexdigest()[:16]}"
    
    return record


def enrich_api_response(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich API response with deterministic and epistemic metadata.
    
    This is called before returning responses to ensure all outputs
    include the necessary metadata for verification and audit.
    """
    
    # Add execution context hash
    if "execution_context_hash" not in response:
        response["execution_context_hash"] = compute_execution_context_hash(
            dossier_id=response.get("dossier_id"),
            case_id=response.get("case_id"),
        )
    
    # Add epistemic status for any claims
    if "claims" in response and isinstance(response["claims"], list):
        for claim in response["claims"]:
            update_epistemic_status(claim, claim.get("status", "pending"))
    
    return response
# ---------------------------------------------------------------------------
# Claim extraction and verification
# ---------------------------------------------------------------------------
#
# A narrative is readable, not trustable. The claims below are the trustable
# half of the same answer: each one carries the words from the document that
# support it, and each of those quotes is checked against the extracted text
# before it reaches a reader.
#
# The check is deliberately mechanical. It does not judge whether a claim
# follows from its quote — that is a reviewer's job — it establishes only that
# the quote is really in the document. A model that invents a plausible sentence
# fails here, and the failure is reported rather than hidden.

#: The prompt's own rule, enforced in code. A five-character quote matches
#: almost any document by accident, so a short quote proves nothing.
MINIMUM_EXPLICIT_QUOTE_CHARS = 20

#: A model asked for 5-15 claims that returns four hundred has misunderstood
#: something; the cap keeps one bad answer from filling a drawer.
MAX_CLAIMS = 40

#: How much of the rejected quote is echoed back. Enough to recognise, short
#: enough that a runaway response does not become the screen.
REJECTED_QUOTE_PREVIEW_CHARS = 200


def _normalize(text: str) -> str:
    """The form both sides of a quote comparison are reduced to.

    NFC because a PDF may emit decomposed accents while a model emits composed
    ones: "préavis" as U+0070 U+0072 U+0065 U+0301 U+0061 U+0076 U+0069 U+0073
    and as U+0070 U+0072 U+00E9 U+0061 U+0076 U+0069 U+0073 are the same word
    and compare unequal until one is normalized.

    Whitespace is collapsed to single spaces for a different reason: extracted
    text arrives wrapped at arbitrary widths, and a quote that spans a line
    break is not a paraphrase, it is the same words. Collapsing keeps the
    offsets meaningful because the search runs on this normalized string and
    the span is reported in it.
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip()


def _find_quote(needle: str, haystack: str) -> Tuple[int, int, str] | None:
    """Locate a quote in the normalized document.

    Returns `(start, end, exactness)`. `exactness` is "exact" when the
    characters match as written and "case_insensitive" when only the case
    differs, which is reported rather than smoothed over: a reader checking a
    citation by eye should know the case was not compared.
    """
    if not needle:
        return None
    start = haystack.find(needle)
    if start >= 0:
        return start, start + len(needle), "exact"
    lowered_haystack = haystack.lower()
    lowered_needle = needle.lower()
    start = lowered_haystack.find(lowered_needle)
    if start >= 0:
        # `.lower()` is length-preserving for the scripts in these documents, so
        # the offsets found in the lowered copy index the original.
        return start, start + len(needle), "case_insensitive"
    return None


def _parse_claim_array(raw: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Pull the JSON array out of whatever the model actually returned.

    A local 8B model reliably produces the right array and unreliably produces
    nothing else: prose before it, a markdown fence around it, a trailing
    apology after it. Slicing from the first `[` to the last `]` recovers the
    array in every one of those cases without asking the parser to be lenient
    about the JSON itself.
    """
    text = (raw or "").strip()
    if not text:
        return [], "EMPTY_RESPONSE"

    start = text.find("[")
    end = text.rfind("]")
    candidate = text[start : end + 1] if start >= 0 and end > start else ""
    if candidate:
        try:
            parsed = json.loads(candidate)
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            return _clean_claims(parsed), None

    # A single object instead of an array: a common near-miss, and one that
    # carries real content worth keeping.
    object_start = text.find("{")
    object_end = text.rfind("}")
    if object_start >= 0 and object_end > object_start:
        try:
            single = json.loads(text[object_start : object_end + 1])
        except ValueError:
            single = None
        if isinstance(single, dict):
            return _clean_claims([single]), None

    return [], "UNPARSEABLE_RESPONSE"


def _clean_claims(parsed: List[Any]) -> List[Dict[str, Any]]:
    """Keep the entries that have a statement, and nothing else.

    The separator rules in the prompt exist for models that emit an empty
    object between real claims to look cooperative. Those objects are dropped
    rather than surfaced as claims with no content.
    """
    cleaned: List[Dict[str, Any]] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        statement = entry.get("text")
        if not isinstance(statement, str) or not statement.strip():
            continue
        quote = entry.get("quote")
        basis = entry.get("basis")
        cleaned.append(
            {
                "text": statement.strip(),
                "quote": quote.strip() if isinstance(quote, str) else "",
                "basis": basis if basis in ("explicit", "absence") else "explicit",
            }
        )
        if len(cleaned) >= MAX_CLAIMS:
            break
    return cleaned


def _call_ollama(prompt: str, text: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Ask the model for claims about `text` under `prompt`.

    `prompt` carries the standing rules and the task; the document is appended
    here so that instruction and content are joined in exactly one place.
    Returns `(claims, error)`. Never raises: a refusal or a dead model is a
    reported condition, not an exception that takes the route down.
    """
    from interface import llm_classifier

    body = f"{prompt}\n\nDOCUMENT:\n{text}"
    completion = llm_classifier.generate(body, namespace="claims", timeout=240)
    if completion["error"]:
        return [], completion["error"]
    claims, parse_error = _parse_claim_array(completion["text"])
    return claims, parse_error


def extract_claims(
    text: str,
    mode: str = "inbound-analysis",
    contract_type: str = "",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Ask the model for claims about `text`, and report how that went.

    The metadata is returned separately rather than wrapped around the claims,
    because the route spreads it into its response next to its own fields and
    a nested shape would collide with them.
    """
    from interface import llm_classifier, prompts

    started = time.monotonic()
    meta: Dict[str, Any] = {
        "mode": mode,
        "contractType": contract_type,
        "model": llm_classifier.LLM_MODEL,
        "prompt": "inline",
        "error": None,
        "claimsReturned": 0,
        "durationMs": 0,
    }

    if not text or not text.strip():
        meta["error"] = "EMPTY_TEXT"
        return [], meta

    try:
        instructions = prompts.claim_instructions(mode=mode, contract_type=contract_type)
        origin = prompts.describe(prompts.EXTRACT_CLAIMS)
        meta["prompt"] = f"{origin['prompt']}@{origin['version']}"
        meta["promptSha256"] = origin["sha256"]
        meta["promptStatus"] = origin["status"]
    except prompts.PromptError:
        instructions = (
            "Extract verifiable claims from the document below as a JSON array. "
            'Each claim is {"text", "quote", "basis"} where basis is "explicit" '
            'or "absence". Return only the array.'
        )
        meta["promptStatus"] = "missing"

    claims, error = _call_ollama(instructions, text)
    meta["error"] = error
    meta["claimsReturned"] = len(claims)
    meta["durationMs"] = int((time.monotonic() - started) * 1000)
    return claims, meta


def validate_claims(
    raw: Optional[List[Dict[str, Any]]],
    text: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Check every claim's quote against the source, and classify the outcome.

    Three outcomes, and the difference between them is the point:

    * **verified** — an explicit claim whose quote is present in the document.
      Its normalized span is returned so a reader can be shown where.
    * **inferred** — a claim about what the document does *not* say. Nothing can
      be quoted for an absence, so it is marked as inference and never counted
      as evidence.
    * **rejected** — an explicit claim whose quote is not in the document. This
      is the case that matters: a fabricated citation is worse than no citation,
      because it looks checkable.
    """
    norm = _normalize(text)
    verified: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    inferred_count = 0

    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        statement = str(entry.get("text") or "").strip()
        basis = entry.get("basis") if entry.get("basis") in ("explicit", "absence") else "explicit"
        quote = str(entry.get("quote") or "").strip()

        if basis == "absence" or not quote:
            # An empty quote on an explicit claim is not an inference the reader
            # should trust; it is an explicit claim with nothing behind it.
            # Only `basis: absence` earns the inferred label, because only it
            # claims something that could not be quoted by definition.
            if basis == "absence":
                inferred_count += 1
                verified.append(
                    {
                        "text": statement,
                        "quote": None,
                        "basis": "absence",
                        "confidence": "inferred",
                        "source": {"quote": None, "span_normalized": None},
                    }
                )
                continue
            rejected.append(
                {
                    "claim_text": statement,
                    "attempted_quote": "",
                    "reason": "explicit claim has no quote, so it is not verifiable",
                }
            )
            continue

        if len(quote) < MINIMUM_EXPLICIT_QUOTE_CHARS:
            rejected.append(
                {
                    "claim_text": statement,
                    "attempted_quote": quote,
                    "reason": (
                        f"quote is shorter than the {MINIMUM_EXPLICIT_QUOTE_CHARS}"
                        "-character minimum for an explicit claim"
                    ),
                }
            )
            continue

        located = _find_quote(_normalize(quote), norm)
        if located is None:
            rejected.append(
                {
                    "claim_text": statement,
                    "attempted_quote": quote[:REJECTED_QUOTE_PREVIEW_CHARS],
                    "reason": "quote is not verbatim in the extracted text",
                }
            )
            continue

        start, end, exactness = located
        verified.append(
            {
                "text": statement,
                "quote": quote,
                "basis": "explicit",
                "confidence": "direct",
                "source": {
                    "quote": quote,
                    "span_normalized": [start, end],
                    "match": exactness,
                },
            }
        )

    summary: Dict[str, Any] = {
        "verified": sum(1 for c in verified if c["confidence"] == "direct"),
        "inferred": inferred_count,
        "rejected": len(rejected),
        "total": len(verified) + len(rejected),
        "minimumQuoteChars": MINIMUM_EXPLICIT_QUOTE_CHARS,
        "rejected_claims": rejected,
    }
    return verified, summary


def review_narrative_support(narrative: str, cited_text: str) -> Dict[str, Any]:
    """Review narrative claims against the source excerpts actually cited.

    The model proposes source quotes; ``validate_claims`` then requires each
    explicit quote to occur verbatim in the cited excerpts. Any inference,
    missing claim set, or model/parse error is unverified.
    """
    from interface import prompts

    try:
        prompt = prompts.validate_citation_support(narrative)
    except prompts.PromptError as exc:
        return {
            "valid": False,
            "claims": [],
            "validation": {"verified": 0, "inferred": 0, "rejected": 0, "total": 0},
            "error": f"PROMPT_UNAVAILABLE: {exc}",
        }

    raw_claims, error = _call_ollama(prompt, cited_text)
    if error:
        return {
            "valid": False,
            "claims": [],
            "validation": {"verified": 0, "inferred": 0, "rejected": 0, "total": 0},
            "error": error,
        }
    if not raw_claims:
        return {
            "valid": False,
            "claims": [],
            "validation": {"verified": 0, "inferred": 0, "rejected": 0, "total": 0},
            "error": "NO_CLAIMS_RETURNED",
        }

    verified, validation = validate_claims(raw_claims, cited_text)
    valid = (
        validation["verified"] == len(raw_claims)
        and validation["rejected"] == 0
        and validation["inferred"] == 0
    )
    return {
        "valid": valid,
        "claims": verified,
        "validation": validation,
        "error": None if valid else "CLAIMS_NOT_VERIFIED",
    }
