"""IRAC scope segmentation.

Three stages, in the order the remediation plan §7.2 requires, each tried only
when the one before it recovered fewer than two parts:

1. **Headings.** A document that states where its parts begin is segmented by
   those statements (``## ISSUE``, ``FACTS:``, ``HOLDING``). The author's own
   structure outranks anything inferred here.
2. **Cues.** A document with no headings — the brief this product was asked to
   analyse extracts to a single line with neither headings nor blank-line
   blocks — is segmented by a documented, ordered table of phrases that mark
   where each IRAC part begins, with every cut rewound to the start of the
   sentence the cue was found in, so a part never begins mid-sentence. The
   citation is a structural prefix rather than a cue: everything up to the end
   of the reporter citation is CITATION, and the facts follow it.
3. **Blank-line blocks**, and failing that a single DOCUMENT scope.

In stages 1 and 2 a scope is emitted only after the previous cut, so the parts
always come out in document order. The function never invents a part the text
does not contain, and it raises on empty input rather than returning an empty
list.

The vocabulary the stages match on lives in :mod:`interface.scope_vocabulary`
and the heading-line scanner in :mod:`interface.scope_headings`; this module
holds the order the stages run in and the ``Scope`` value they produce.

Flagged in the remediation plan as decision D-3: the cue table is a product
choice about what these scopes mean, and this is the implementation the plan
proposes pending that call. Segmentation decides only *which text* is projected,
never how it is projected, so no projection behaviour depends on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from interface import scope_headings
from interface.scope_vocabulary import (
    CITATION,
    CITATION_PATTERN,
    CUE_TABLE,
    DISTILLED_RULES,
    FACTS,
    HEADING_ALIASES,
    HOLDING,
    ISSUE,
    PROCEDURAL_POSTURE,
    REASONING,
    RULE,
    SETTINGS,
)

__all__ = [
    "CITATION",
    "CITATION_PATTERN",
    "CUE_TABLE",
    "DISTILLED_RULES",
    "DOCUMENT",
    "FACTS",
    "HEADING_ALIASES",
    "HOLDING",
    "ISSUE",
    "PROCEDURAL_POSTURE",
    "REASONING",
    "RULE",
    "SCOPE_NAMES",
    "Scope",
    "SETTINGS",
    "split_scopes",
]

DOCUMENT = "DOCUMENT"

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


def _from_starts(
    text: str, starts: list[tuple[str, int]], *, keep_preamble: bool
) -> list[Scope]:
    """Cut `text` at each start, in the order the starts appear.

    `keep_preamble` decides what becomes of text before the first cut. Headings
    are an explicit structure, so text under no heading at all - a case caption,
    a docket line - is kept as a DOCUMENT part rather than dropped. A cue is an
    inference, and a cue found mid-document already means the text before it
    belongs to no part this module recognises.
    """
    scopes: list[Scope] = []
    first_start = starts[0][1]

    if keep_preamble and first_start > 0 and text[:first_start].strip():
        scopes.append(
            Scope(name=DOCUMENT, text=text[:first_start], start=0, end=first_start)
        )

    for index, (name, start) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else len(text)
        scopes.append(Scope(name=name, text=text[start:end], start=start, end=end))

    return scopes


def split_scopes(text: str) -> list[Scope]:
    """Segment a document into IRAC scopes, or the best honest fallback.

    Stages run in the order the plan §7.2 requires and each is taken only if it
    recovered at least two parts, so the strongest available structure wins:
    the document's own headings, then the cue table, then blank-line blocks,
    then the whole document as one part.

    Raises ValueError for empty input rather than returning an empty list, so an
    empty segmentation can never be mistaken for a document with no content.
    """
    if not text or not text.strip():
        raise ValueError("cannot segment empty text")

    headings = scope_headings.heading_starts(text, HEADING_ALIASES)
    if len(headings) >= 2:
        return _from_starts(text, headings, keep_preamble=True)

    cues = _cue_starts(text)
    if len(cues) >= 2:
        return _from_starts(text, cues, keep_preamble=False)

    blocks = _blank_line_blocks(text)
    if len(blocks) >= 2:
        return blocks

    return [Scope(name=DOCUMENT, text=text, start=0, end=len(text))]
