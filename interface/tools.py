"""Non-case on-demand analysis with citation validation."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
TOOLS_LLM_MODEL = os.environ.get("TOOLS_LLM_MODEL", "llama3.1:8b")
MAX_TEXT = 12000
MIN_QUOTE_CHARS = 20
VALID_BASES = frozenset({"explicit", "absence"})


def _load_prompt(mode: str, contract_type: str) -> str:
    p = Path(__file__).parent.parent / "prompts" / "v1" / "extract_claims.txt"
    template = p.read_text(encoding="utf-8")
    return template.replace("{mode}", mode).replace(
        "{contract_type}", contract_type or "general"
    )


def _call_ollama(prompt: str, text: str) -> tuple[list[dict], str | None]:
    """Ask the LLM for structured claims. Returns (claims, error)."""
    try:
        import requests
    except Exception as exc:
        return [], f"requests_missing:{type(exc).__name__}"

    nonce = secrets.token_hex(8)
    full_prompt = (
        f"{prompt}\n\n---SOURCE-{nonce}---\n\n{text[:MAX_TEXT]}\n\n"
        f"---END-SOURCE-{nonce}---\n\nRespond with a JSON array only."
    )
    body = {
        "model": TOOLS_LLM_MODEL,
        "prompt": full_prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }
    try:
        r = requests.post(OLLAMA_URL, json=body, timeout=180)
        r.raise_for_status()
        raw = r.json().get("response", "")
    except Exception as exc:
        logger.warning("tools: ollama failed: %s", exc)
        return [], f"ollama_failed:{type(exc).__name__}"

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("tools: non-JSON from ollama: %r", raw[:200])
        return [], "non_json"

    # The LLM may return the claims in one of several shapes:
    #   [{...}, {...}]                  — bare array (expected)
    #   {"claims": [...]}               — wrapped with "claims" key
    #   {"results": [...]}              — wrapped with some other key
    #   {"claim_1": {...}, ...}         — keyed by index
    #   {"analysis": "..."}             — plain object, no list
    # Extract the first list of dicts found. If none, log what we got
    # so future debugging doesn't require guessing.
    if isinstance(parsed, dict) and "claims" in parsed:
        parsed = parsed["claims"]
    elif isinstance(parsed, dict):
        # Find the first list value that looks like claim objects
        for key, val in parsed.items():
            if isinstance(val, list) and val and isinstance(val[0], dict):
                logger.info("tools: LLM returned claims under key %r", key)
                parsed = val
                break
        else:
            # Could not find a list. If every value is a dict, treat the
            # dict as keyed claims (e.g. {"claim_1": {...}, "claim_2": {...}}).
            if parsed and all(isinstance(v, dict) for v in parsed.values()):
                logger.info(
                    "tools: LLM returned keyed claims: keys=%s",
                    list(parsed.keys())[:5],
                )
                parsed = list(parsed.values())
            else:
                logger.warning(
                    "tools: unexpected dict shape; keys=%s",
                    list(parsed.keys())[:10],
                )
                return [], f"unexpected_shape:dict(keys={list(parsed.keys())[:5]})"

    if not isinstance(parsed, list):
        logger.warning("tools: unexpected top-level type: %s", type(parsed).__name__)
        return [], f"unexpected_shape:{type(parsed).__name__}"

    return [c for c in parsed if isinstance(c, dict)], None


def extract_claims(text: str, mode: str, contract_type: str) -> tuple[list[dict], dict]:
    """Returns (claims, extraction_meta)."""
    prompt = _load_prompt(mode, contract_type)
    raw, error = _call_ollama(prompt, text)
    claims: list[dict] = []
    for c in raw:
        text_val = (c.get("text") or "").strip()
        if not text_val:
            continue
        basis = (c.get("basis") or "explicit").strip()
        if basis not in VALID_BASES:
            basis = "explicit"
        claims.append({
            "text": text_val,
            "quote": (c.get("quote") or "").strip(),
            "basis": basis,
        })
    meta = {"ok": error is None, "raw_count": len(claims), "error": error}
    return claims, meta


def _normalize(s: str) -> str:
    """NFC + whitespace collapse. NFC so NFD-extracted PDFs match NFC LLM quotes."""
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", " ", s).strip()


def validate_claims(raw: list[dict], source_text: str) -> tuple[list[dict], dict]:
    """Check every quote against the source. Reject claims that fail.

    span_normalized is in normalized coordinates — do not index raw text with it.
    attempted_quote is preserved on rejected claims so a reader can distinguish
    a hallucination from extraction mangling.
    """
    source = _normalize(source_text)
    validated: list[dict] = []
    rejected: list[dict] = []
    verified = inferred = 0

    for c in raw:
        claim: dict = {"text": c["text"], "basis": c["basis"]}
        quote = _normalize(c.get("quote", ""))

        if claim["basis"] == "absence":
            claim["confidence"] = "inferred"
            claim["source"] = {"quote": None, "span_normalized": None}
            validated.append(claim)
            inferred += 1
            continue

        if not quote:
            rejected.append({**claim, "attempted_quote": c.get("quote", ""),
                             "reason": "explicit claim has no quote"})
            continue
        if len(quote) < MIN_QUOTE_CHARS:
            rejected.append({**claim, "attempted_quote": c.get("quote", ""),
                             "reason": f"quote too short ({len(quote)} < {MIN_QUOTE_CHARS})"})
            continue

        idx = source.find(quote)
        if idx == -1:
            rejected.append({**claim, "attempted_quote": c.get("quote", ""),
                             "reason": "quote not verbatim in source"})
            continue

        claim["confidence"] = "direct"
        claim["source"] = {"quote": quote,
                           "span_normalized": [idx, idx + len(quote)]}
        validated.append(claim)
        verified += 1

    summary = {
        "total_raw": len(raw),
        "verified": verified,
        "inferred": inferred,
        "rejected": len(rejected),
        "rejected_claims": rejected,
    }
    return validated, summary
