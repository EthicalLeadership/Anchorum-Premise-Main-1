"""Deterministic document type classifier (the "receiving clerk").

This module answers exactly one question: "What kind of document is this?"
It does so using a fixed table of regex patterns. It does not use an LLM,
a machine learning model, or an external service.

The vocabulary is closed. The tie-breaker is deterministic (highest score,
then alphabetical). It is a routing hint, not an assertion of authenticity.
"""

import re
import unicodedata
from datetime import datetime
from typing import Dict, Optional


# Closed vocabulary of document types.
DOCUMENT_TYPES = (
    "correspondence",
    "insurer_letter",
    "medical_note",
    "official_report",
    "payroll",
    "unknown",
)

# Minimum number of distinct patterns that must match to avoid "unknown".
MIN_SCORE = 1

# One entry per classifiable type. Values are tuples of regex patterns.
# Patterns are matched case-insensitively.
CLASSIFIER_RULES: dict[str, tuple[str, ...]] = {
    "medical_note": (
        r"\bprescription\b",
        r"\bRx\b",
        r"\bmedecin\b",
        r"\bdiagnos[ie]s?\b",
        r"\bpatient\b",
        r"\bclinical\b",
        r"\bconsultation\b",
        r"\bhopital\b",
        r"\bclinique\b",
    ),
    "official_report": (
        r"\bofficial\b",
        r"\breport\b",
        r"\bgovernment\b",
        r"\bministere\b",
        r"\bautorite\b",
        r"\bcertificate\b",
        r"\bcertificat\b",
        r"\baffidavit\b",
    ),
    "insurer_letter": (
        r"\binsurer\b",
        r"\binsurance\b",
        r"\bassurance\b",
        r"\bassureur\b",
        r"\bclaim\b",
        r"\bpolicy\b",
        r"\bpolice\b",
        r"\bcoverage\b",
        r"\bindemnity\b",
    ),
    "payroll": (
        r"\bpayroll\b",
        r"\bsalary\b",
        r"\bwages\b",
        r"\bgross pay\b",
        r"\bnet pay\b",
        r"\bdeductions\b",
        r"\bpaie\b",
        r"\bsalaire\b",
    ),
    "correspondence": (
        r"\bdear\b",
        r"\bsincerely\b",
        r"\bregards\b",
        r"\bcordialement\b",
        r"\bmonsieur\b",
        r"\bmadame\b",
        r"\bcher\b",
        r"\bchere\b",
    ),
}

# Compile at import time. IGNORECASE only (no DOTALL, so patterns do not
# swallow newlines silently).
_COMPILED: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (type_name, tuple(re.compile(p, re.IGNORECASE) for p in patterns))
    for type_name, patterns in CLASSIFIER_RULES.items()
)


def _normalize(text: str) -> str:
    """Fold accents to ASCII so `médecin` and `medecin` match one pattern."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _score_text(text: str) -> dict[str, int]:
    """Count distinct patterns matched per type."""
    scores: dict[str, int] = {}
    for type_name, patterns in _COMPILED:
        score = sum(1 for p in patterns if p.search(text))
        scores[type_name] = score
    return scores


def classify_text(text: str) -> str:
    """Classify extracted text into a DOCUMENT_TYPES member.

    Deterministic: same text -> same result.
    Ties are broken alphabetically. Scores below MIN_SCORE become "unknown".
    """
    if not text or not text.strip():
        return "unknown"

    normalized = _normalize(text)
    scores = _score_text(normalized)

    # Sort by highest score first, then alphabetical type name as tie-break.
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best_type, best_score = ranked[0]

    if best_score < MIN_SCORE:
        return "unknown"

    return best_type


# ---------------------------------------------------------------------------
# Metadata Extraction (Date, Author, Issuer)
# ---------------------------------------------------------------------------

_MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_NUM = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")
_DATE_TEXT = re.compile(r"\b(?:le\s+)?(\d{1,2})(?:er|re|e|eme|th|st|nd|rd)?\s+(janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre|january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})\b", re.IGNORECASE)

# `(?i:...)` scopes case-insensitivity to the title word alone. A bare
# re.IGNORECASE also makes `[A-Z]` match lowercase, which is how
# "Ministry of Health" ended up captured as "of Health": the capitalisation
# requirement the pattern states was silently switched off.
_TITLE_PREFIX = r"(?i:Dr|Docteur|Doctor|Me|Maitre|Master)"

# A name token: capitalised first letter, then any of letters, apostrophes,
# hyphens and dots. Accepting either case after the first letter is what lets
# "TREMBLAY" survive an all-caps OCR pass while a lowercase word cannot start
# a name.
_NAME = r"[A-Z][A-Za-z'\u2019.-]+"

_AUTHOR = re.compile(rf"\b{_TITLE_PREFIX}\.?\s+({_NAME}(?:\s+{_NAME})?)")

# The organisation head is matched case-insensitively; the words captured after
# it are not, so a run of prose is not mistaken for a name. Lowercase
# connectors are permitted between capitalised words, which is what makes
# "Hopital General de Montreal" come back whole rather than as "General".
_ISSUER_HEAD = r"(?i:Clinique|Hopital|Hospital|Ministere|Ministry|Cour|Court|Tribunal)"
_ISSUER_CONNECTOR = r"(?i:de|du|des|et|of|and|the)"
_ISSUER = re.compile(
    rf"\b({_ISSUER_HEAD}(?:\s+(?:{_NAME}|{_ISSUER_CONNECTOR})){{0,4}})"
)

def extract_metadata(text: str) -> dict[str, str | None]:
    """Extract date, author, and issuer from text deterministically."""
    if not text or not text.strip():
        return {"date": None, "author": None, "issuer": None}

    normalized = _normalize(text)

    date_str = None
    m = _DATE_ISO.search(normalized)
    if m:
        date_str = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    else:
        m = _DATE_NUM.search(normalized)
        if m:
            # Assume YYYY-MM-DD if first group is 4 digits, else DD/MM/YYYY
            d, mo, y = m.group(1), m.group(2), m.group(3)
            if len(y) == 2:
                y = "20" + y
            date_str = f"{y}-{int(mo):02d}-{int(d):02d}"
        else:
            m = _DATE_TEXT.search(normalized)
            if m:
                d = int(m.group(1))
                mo = _MONTHS.get(m.group(2).lower(), 1)
                y = int(m.group(3))
                date_str = f"{y}-{mo:02d}-{d:02d}"

    author = None
    m = _AUTHOR.search(normalized)
    if m:
        # `_NAME` admits a trailing dot so initials survive; a sentence-final
        # period is not part of the name.
        author = m.group(1).strip().rstrip(".,;:")

    issuer = None
    m = _ISSUER.search(normalized)
    if m:
        issuer = m.group(1).strip().rstrip(".,;:")

    return {"date": date_str, "author": author, "issuer": issuer}
