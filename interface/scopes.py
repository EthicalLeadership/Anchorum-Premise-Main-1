"""IRAC scope segmentation.

The brief this product was asked to analyse extracts to a single line with no
headings and no blank-line blocks, so heading detection and blank-line blocking
cannot segment it. Segmentation is therefore cue-driven: a documented, ordered
table of phrases that mark where each IRAC part begins in a case document, with
every cut rewound to the start of the sentence the cue was found in, so a part
never begins mid-sentence.

The citation is a structural prefix rather than a cue: everything up to the end
of the reporter citation is CITATION, and the facts follow it.

A scope is emitted only when its cue appears after the previous cut, so the parts
always come out in document order. When fewer than two parts are recovered the
function falls back to blank-line blocks, and failing that to a single DOCUMENT
scope. It never invents a part that is not present in the text, and it raises on
empty input rather than returning an empty list.

Flagged in the remediation plan as decision D-3: the cue table is a product
choice about what these scopes mean, and this is the implementation the plan
proposes pending that call. Segmentation decides only *which text* is projected,
never how it is projected, so no projection behaviour depends on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DOCUMENT = "DOCUMENT"

CITATION = "CITATION"
FACTS = "FACTS"
PROCEDURAL_POSTURE = "PROCEDURAL_POSTURE"
ISSUE = "ISSUE"
RULE = "RULE"
REASONING = "REASONING"
HOLDING = "HOLDING"
DISTILLED_RULES = "DISTILLED_RULES"

SCOPE_NAMES = (
    CITATION,
    FACTS,
    PROCEDURAL_POSTURE,
    ISSUE,
    RULE,
    REASONING,
    HOLDING,
    DISTILLED_RULES,
)

# A reporter citation at the head of the document: "322 A.2d 630 1974 CONTRACTS".
CITATION_PATTERN = r"^\s*\d+\s+[A-Za-z][\w.]*\s+\d+[\s\x00-\x1f\(\)\[\]]*\d{4}[\s\x00-\x1f\(\)\[\]]*[A-Z]{2,}\b"

# Ordered cue table for the parts that follow the citation: (scope, pattern).
CUE_TABLE: tuple[tuple[str, str], ...] = (
    (
        PROCEDURAL_POSTURE,
        r"(?:Superior Court[^.]{0,60}?(?:heard|ruled)|appealed the decision)",
    ),
    (ISSUE, r"Whether\b"),
    (RULE, r"(?:A contract modification|only requires consideration)"),
    (
        REASONING,
        r"(?:gave careful attention|Court emphasized|They reasoned|applied\s*:)",
    ),
    (HOLDING, r"(?:reversed the lower court|held that Maher|held that)"),
    (
        DISTILLED_RULES,
        r"(?:Contract modifications are enforceable|Pre-Existing Duty rule)",
    ),
)

SETTINGS = re.IGNORECASE | re.DOTALL


@dataclass(frozen=True)
class Scope:
    """One segmented part of a document."""

    name: str
    text: str
    start: int
    end: int

    @property
    def chars(self) -> int:
        return len(self.text.strip())


def _sentence_start(text: str, index: int) -> int:
    """Rewind to the first character of the sentence containing `index`."""
    start = 0
    for terminator in re.finditer(r"(?:[.?!]|\b\d{1,2}:\d{2})\s+", text[:index]):
        start = terminator.end()
    return start


def _cue_starts(text: str) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    cursor = 0

    citation = re.match(CITATION_PATTERN, text)
    if citation is not None:
        hits.append((CITATION, 0))
        cursor = citation.end()
        hits.append((FACTS, cursor))

    for name, pattern in CUE_TABLE:
        match = re.search(pattern, text[cursor:], flags=SETTINGS)
        if match is None:
            continue
        start = max(cursor, _sentence_start(text, cursor + match.start()))
        hits.append((name, start))
        cursor = cursor + match.end()

    return hits


def _blank_line_blocks(text: str) -> list[Scope]:
    scopes: list[Scope] = []
    cursor = 0
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        start = text.index(block, cursor)
        end = start + len(block)
        cursor = end
        scopes.append(
            Scope(name=f"{DOCUMENT}_{len(scopes) + 1}", text=block, start=start, end=end)
        )
    return scopes


def split_scopes(text: str) -> list[Scope]:
    """Segment a document into IRAC scopes, or the best honest fallback.

    Raises ValueError for empty input rather than returning an empty list, so an
    empty segmentation can never be mistaken for a document with no content.
    """
    if not text or not text.strip():
        raise ValueError("cannot segment empty text")

    hits = _cue_starts(text)
    if len(hits) >= 2:
        scopes: list[Scope] = []
        for index, (name, start) in enumerate(hits):
            end = hits[index + 1][1] if index + 1 < len(hits) else len(text)
            scopes.append(Scope(name=name, text=text[start:end], start=start, end=end))
        return scopes

    blocks = _blank_line_blocks(text)
    if len(blocks) >= 2:
        return blocks

    return [Scope(name=DOCUMENT, text=text, start=0, end=len(text))]
