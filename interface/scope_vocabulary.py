"""The words that decide where an IRAC part begins.

Three tables and the flags they are matched with. They are data, not logic, and
they are separated from :mod:`interface.scopes` so the algorithm can be read
without scrolling past them - and so the one thing this file holds, what these
scopes *mean*, has a single address when the product decision the plan calls D-3
is finally taken.

- ``CITATION_PATTERN`` recognises a reporter citation at the head of a document.
- ``CUE_TABLE`` lists, in document order, the phrases that mark where a part
  begins when the document states no structure of its own.
- ``HEADING_TABLE`` lists what a document may call each part when it does state
  its own structure.

Neither table invents a part: a phrase absent from both produces no scope, and
the fallbacks in ``split_scopes`` take over.
"""

from __future__ import annotations

import re

CITATION = "CITATION"
FACTS = "FACTS"
PROCEDURAL_POSTURE = "PROCEDURAL_POSTURE"
ISSUE = "ISSUE"
RULE = "RULE"
REASONING = "REASONING"
HOLDING = "HOLDING"
DISTILLED_RULES = "DISTILLED_RULES"

SETTINGS = re.IGNORECASE | re.DOTALL

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

# What each IRAC part may be called when a document states its own structure,
# as (scope, labels). Labels are compared after `scope_headings.normalise_label`,
# so case, surrounding emphasis and a trailing colon do not matter. Only names
# in this table are recognised: an unlisted heading is left alone rather than
# guessed at, which is why `INTRODUCTION` or `NOTES` cannot invent a part.
HEADING_TABLE: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        CITATION,
        ("citation", "case citation", "reporter citation", "citation and court"),
    ),
    (
        FACTS,
        (
            "facts",
            "statement of facts",
            "statement of the facts",
            "facts and background",
            "factual background",
            "background",
        ),
    ),
    (
        PROCEDURAL_POSTURE,
        (
            "procedural posture",
            "procedural postures",
            "procedural history",
            "procedural background",
            "procedural status",
        ),
    ),
    (
        ISSUE,
        (
            "issue",
            "issues",
            "issue presented",
            "issues presented",
            "issue presented for review",
            "question presented",
            "questions presented",
            "legal issue",
            "legal issues",
        ),
    ),
    (
        RULE,
        (
            "rule",
            "rules",
            "rule of law",
            "rules of law",
            "legal rule",
            "legal rules",
            "applicable law",
            "governing law",
        ),
    ),
    (
        REASONING,
        (
            "reasoning",
            "analysis",
            "discussion",
            "rationale",
            "reasoning and analysis",
            "court's reasoning",
            "court's analysis",
        ),
    ),
    (
        HOLDING,
        (
            "holding",
            "holdings",
            "decision",
            "disposition",
            "conclusion",
            "judgment",
            "judgement",
        ),
    ),
    (
        DISTILLED_RULES,
        (
            "distilled rules",
            "distilled rule",
            "rules distilled",
            "black letter rules",
            "black-letter rules",
            "key takeaways",
            "takeaways",
        ),
    ),
)

#: Normalised heading label -> scope name, the form `heading_starts` consumes.
HEADING_ALIASES: dict[str, str] = {
    label: name for name, labels in HEADING_TABLE for label in labels
}
