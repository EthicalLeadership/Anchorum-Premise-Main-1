"""
Dossier DOSSIER-PIPELINE Output Leakage Gates

Post-processing controls for outward-facing text. These gates are applied at
the final render boundary so internal reasoning can remain internal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

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

#: A digest must be lowercase-or-uppercase hex and nothing else to qualify for
#: the allowlist: anything else in a "trusted" string would be copied back into
#: the output verbatim, including whatever an operator pasted by mistake.
_HEX_ONLY = re.compile(r"[0-9a-f]+")
#: A run long enough to be caught by a hash rule, wherever it sits in a value.
#: The allowlist accepts `E-<digest>` and `sha256:<digest>` as well as a bare
#: digest, because an evidence key is an id the reader must be able to match
#: against the manifest, and it is suffixed to a digest rather than being one.
_HEX_RUN = re.compile(r"[0-9a-f]{16,}")

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


def sanitize_output(
    text: str,
    *,
    trusted_hashes: Iterable[str] = (),
) -> LeakageReport:
    """Redact internal vocabulary and hashes from outward-facing text.

    `trusted_hashes` is the allowlist. A digest named here is verification
    material — an artifact's own `content_hash` printed in an export line, for
    instance — and redacting it would leave the reader holding a package they
    cannot check. Everything not named is still redacted, so the gate keeps its
    purpose: internal hashes stay internal, and the exemption is a decision
    someone made explicitly rather than a pattern that happens to look alike.
    """
    sanitized = text
    redacted: list[str] = []
    restored: list[tuple[str, str]] = []

    for index, value in enumerate(trusted_hashes):
        digest = (value or "").strip()
        # The caller named this value, so the question is only whether it is
        # long enough to be caught by a rule. A prefixed id qualifies: the guard
        # exists to reject entries that no pattern would redact anyway.
        if not digest or _HEX_RUN.search(digest.lower()) is None:
            continue
        if len(digest) < 16:
            # Shorter than the smallest hash pattern, so it cannot be caught by
            # the rules below; nothing to protect it from.
            continue
        placeholder = f"<<trusted-digest-{index}>>"
        updated = re.sub(
            re.escape(digest), placeholder, sanitized, flags=re.IGNORECASE
        )
        if updated != sanitized:
            restored.append((placeholder, digest))
            sanitized = updated

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

    # Put the allowlisted digests back exactly as they were supplied. Doing it
    # after the section strip matters: a line was kept above because it no
    # longer looked like a hash line, and it must read as a hash line again now.
    for placeholder, digest in restored:
        sanitized = sanitized.replace(placeholder, digest)

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
