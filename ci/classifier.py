"""
Failure Classification Engine
==============================
Every failure is classified into an exact category from the closed taxonomy.
No fuzzy or ML-based classification pattern matching + traceback parsing only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

class FailureCategory(Enum):
    # Build
    MISSING_DEPENDENCY = auto()
    VERSION_CONFLICT = auto()
    COMPILATION_ERROR = auto()
    # Test
    ASSERTION_MISMATCH = auto()
    MISSING_TEST_DEPENDENCY = auto()
    FLAKY_TEST = auto()
    # Static
    IMPORT_FAILURE = auto()
    UNDEFINED_REFERENCE = auto()
    TYPE_MISMATCH = auto()
    # Runtime simulation
    CRASH_ON_STARTUP = auto()
    CONFIG_ERROR = auto()
    INITIALIZATION_FAILURE = auto()
    # Security
    UNSAFE_CONFIG = auto()
    EXPOSED_SECRET = auto()
    VULNERABLE_DEPENDENCY = auto()
    # Catch-all – requires human
    UNCLASSIFIED = auto()


class Severity(Enum):
    CRITICAL = "CRITICAL"   # structural – no auto-heal
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# Structural failures cannot be auto-healed
STRUCTURAL_CATEGORIES = frozenset({
    FailureCategory.COMPILATION_ERROR,
    FailureCategory.UNDEFINED_REFERENCE,
    FailureCategory.TYPE_MISMATCH,
    FailureCategory.CRASH_ON_STARTUP,
    FailureCategory.EXPOSED_SECRET,
    FailureCategory.UNCLASSIFIED,
})


@dataclass
class FailureRecord:
    stage: str
    raw_output: str
    category: FailureCategory = FailureCategory.UNCLASSIFIED
    severity: Severity = Severity.HIGH
    detail: str = ""
    is_structural: bool = field(init=False)

    def __post_init__(self) -> None:
        self.is_structural = self.category in STRUCTURAL_CATEGORIES

    def signature(self) -> str:
        """Stable hash key for failure memory deduplication."""
        import hashlib
        blob = f"{self.stage}:{self.category.name}:{self.detail[:120]}"
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Pattern table  (stage → list of (regex, category, severity))
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, re.Pattern[str], FailureCategory, Severity]] = []


def _p(stage_glob: str, pattern: str, cat: FailureCategory, sev: Severity) -> None:
    _PATTERNS.append((stage_glob, re.compile(pattern, re.I | re.S), cat, sev))


# -- build / dependency
_p("*",       r"no module named '?(\S+)'?",              FailureCategory.IMPORT_FAILURE,         Severity.HIGH)
_p("*",       r"modulenotfounderror",                     FailureCategory.IMPORT_FAILURE,         Severity.HIGH)
_p("*",       r"importerror",                             FailureCategory.IMPORT_FAILURE,         Severity.HIGH)
_p("build",   r"could not find a version that satisfies", FailureCategory.MISSING_DEPENDENCY,     Severity.HIGH)
_p("build",   r"no matching distribution found",          FailureCategory.MISSING_DEPENDENCY,     Severity.HIGH)
_p("build",   r"version conflict|conflicting dependencies",FailureCategory.VERSION_CONFLICT,      Severity.MEDIUM)
_p("build",   r"syntaxerror",                             FailureCategory.COMPILATION_ERROR,      Severity.CRITICAL)
# -- tests
_p("test",    r"assertionerror|assert .+ ==",             FailureCategory.ASSERTION_MISMATCH,     Severity.MEDIUM)
_p("test",    r"flaky|rerun|xfail",                       FailureCategory.FLAKY_TEST,             Severity.LOW)
_p("test",    r"fixture '(\S+)' not found",               FailureCategory.MISSING_TEST_DEPENDENCY,Severity.MEDIUM)
_p("test",    r"no module named",                         FailureCategory.MISSING_TEST_DEPENDENCY,Severity.HIGH)
# -- static
_p("static",  r"nameerror|undefined name",                FailureCategory.UNDEFINED_REFERENCE,    Severity.CRITICAL)
_p("static",  r"typeerror",                               FailureCategory.TYPE_MISMATCH,          Severity.CRITICAL)
_p("static",  r"circular import",                         FailureCategory.IMPORT_FAILURE,         Severity.HIGH)
# -- runtime simulation
_p("runtime", r"keyerror|missing key|config",             FailureCategory.CONFIG_ERROR,           Severity.HIGH)
_p("runtime", r"failed to initializ|initialization",      FailureCategory.INITIALIZATION_FAILURE, Severity.HIGH)
_p("runtime", r"segfault|killed|exit code [^0]",          FailureCategory.CRASH_ON_STARTUP,       Severity.CRITICAL)
# -- security
_p("security",r"password|secret|api.?key|token",          FailureCategory.EXPOSED_SECRET,         Severity.CRITICAL)
_p("security",r"insecure|unsafe|deprecated cipher",       FailureCategory.UNSAFE_CONFIG,          Severity.HIGH)
_p("security",r"known vulnerability|cve-",                FailureCategory.VULNERABLE_DEPENDENCY,  Severity.HIGH)


def classify(stage: str, raw_output: str) -> FailureRecord:
    """Return the first matching FailureRecord for the given stage output."""
    text = raw_output.lower()
    for stage_glob, pattern, cat, sev in _PATTERNS:
        if stage_glob != "*" and stage_glob not in stage.lower():
            continue
        if pattern.search(text):
            m = pattern.search(text)
            detail = m.group(0)[:200] if m else ""
            return FailureRecord(stage=stage, raw_output=raw_output,
                                 category=cat, severity=sev, detail=detail)
    return FailureRecord(stage=stage, raw_output=raw_output,
                         category=FailureCategory.UNCLASSIFIED,
                         severity=Severity.CRITICAL, detail="no pattern matched")
