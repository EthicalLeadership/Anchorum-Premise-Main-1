"""
Dossier DOSSIER-PIPELINE — Output Leakage Gates

Post-processing controls for outward-facing text. These gates are applied at
the final render boundary so internal reasoning can remain internal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

GOVERNANCE_RULESET_VERSION = "1.0.0"

INTERNAL_TERMS = (
    "internal reasoning",
    "protected analysis",
    "non-public terminology",
    "decision_reasoning",
    "trace",
    "payload_hash",
    "control_hash",
    "previous_hash",
    "legal advice",
    "legal theory",
    "litigation strategy",
    "counsel-only",
    "confidential analysis",
)

_REPLACEMENTS = (
    (r"\bdecision_reasoning\b", "decision summary"),
    (r"\bpayload_hash\b", "artifact hash"),
    (r"\bcontrol_hash\b", "record hash"),
    (r"\bprevious_hash\b", "prior hash"),
    (r"\bdecision-reasoning\b", "decision summary"),
    (r"\bpayload-hash\b", "artifact hash"),
    (r"\bcontrol-hash\b", "record hash"),
    (r"\bprevious-hash\b", "prior hash"),
)

_SENSITIVE_LINE_MARKERS = (
    "decision reasoning",
    "decision_reasoning",
    "payload hash",
    "payload_hash",
    "control hash",
    "control_hash",
    "control-hash",
    "previous hash",
    "previous_hash",
    "previous-hash",
    "internal reasoning",
    "protected analysis",
    "non-public terminology",
)

_HASH_PATTERNS = (
    re.compile(r"\b[a-f0-9]{64}\b", flags=re.IGNORECASE),
    re.compile(r"\b[a-f0-9]{32}\b", flags=re.IGNORECASE),
    re.compile(r"\b[a-f0-9]{16}\b", flags=re.IGNORECASE),
)

_SPLIT_HASH_PATTERNS = (
    re.compile(r"(?:[a-f0-9]{2}[\s\-_:`]?){32}", flags=re.IGNORECASE),
    re.compile(r"(?:[a-f0-9]{2}[\s\-_:`]?){16}", flags=re.IGNORECASE),
    re.compile(r"(?:[a-f0-9]{2}[\s\-_:`]?){8}", flags=re.IGNORECASE),
)


@dataclass(frozen=True)
class LeakageReport:
    sanitized_text: str
    redacted_terms: tuple[str, ...]
    leakage_found: bool


def sanitize_output(text: str) -> LeakageReport:
    sanitized = text
    redacted: list[str] = []

    for pattern, replacement in _REPLACEMENTS:
        if re.search(pattern, sanitized, flags=re.IGNORECASE):
            redacted.append(pattern.strip(r"\b"))
            sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)

    lower_text = sanitized.lower()
    for term in INTERNAL_TERMS:
        if term in lower_text:
            redacted.append(term)

    for pattern in _HASH_PATTERNS:
        if pattern.search(sanitized):
            redacted.append(pattern.pattern)
            sanitized = pattern.sub("[redacted-hash]", sanitized)

    for pattern in _SPLIT_HASH_PATTERNS:
        if pattern.search(sanitized):
            redacted.append(pattern.pattern)
            sanitized = pattern.sub("[redacted-hash]", sanitized)

    leakage_found = bool(redacted)

    if leakage_found:
        sanitized = _strip_sensitive_sections(sanitized)

    return LeakageReport(
        sanitized_text=sanitized,
        redacted_terms=tuple(dict.fromkeys(redacted)),
        leakage_found=leakage_found,
    )


def _strip_sensitive_sections(text: str) -> str:
    lines = text.splitlines()
    filtered: list[str] = []

    for line in lines:
        lowered = line.lower()
        if any(marker in lowered for marker in _SENSITIVE_LINE_MARKERS):
            continue
        if any(pattern.search(line) for pattern in _HASH_PATTERNS):
            continue
        if any(pattern.search(line) for pattern in _SPLIT_HASH_PATTERNS):
            continue
        filtered.append(line)

    return "\n".join(filtered).strip()
