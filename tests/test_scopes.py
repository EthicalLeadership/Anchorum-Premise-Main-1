"""Pins for IRAC scope segmentation.

The benchmark assertions run against the real brief when it is present on the
machine, guarded the way `tests/test_pdf_text.py` guards its sample, so a clone
without the sample still runs the synthetic pins.
"""

from pathlib import Path

import pytest

from interface.scopes import (
    CITATION,
    DISTILLED_RULES,
    FACTS,
    HOLDING,
    ISSUE,
    PROCEDURAL_POSTURE,
    REASONING,
    RULE,
    SCOPE_NAMES,
    split_scopes,
)

BRIEF = Path.home() / "Angel v. Murray \u2013 (IRAC) Case Brief Summary.pdf"

#: Per-scope character counts measured in `docs/audit/CONNECTOR_AUDIT.md` §5.
BENCHMARK_CHARS = {
    CITATION: 29,
    FACTS: 2009,
    PROCEDURAL_POSTURE: 188,
    ISSUE: 218,
    RULE: 163,
    REASONING: 1495,
    HOLDING: 137,
    DISTILLED_RULES: 599,
}


def test_split_scopes_empty_raises():
    with pytest.raises(ValueError, match="cannot segment empty text"):
        split_scopes("")
    with pytest.raises(ValueError, match="cannot segment empty text"):
        split_scopes("   ")


def test_split_scopes_single_scope_fallback():
    text = "Just a short text without cues or blank lines."
    scopes = split_scopes(text)
    assert len(scopes) == 1
    assert scopes[0].name == "DOCUMENT"
    assert scopes[0].text == text


def test_split_scopes_blank_lines_fallback():
    text = "Block one text.\n\nBlock two text.\n\nBlock three text."
    scopes = split_scopes(text)
    assert len(scopes) == 3
    assert [scope.name for scope in scopes] == ["DOCUMENT_1", "DOCUMENT_2", "DOCUMENT_3"]


def test_cue_parts_come_out_in_document_order():
    text = (
        "Whether the payment was lawful is the question. "
        "The Court gave careful attention to the facts. "
        "The court reversed the lower court judgment. "
        "Contract modifications are enforceable without new consideration."
    )
    scopes = split_scopes(text)
    assert [scope.name for scope in scopes] == [
        ISSUE,
        REASONING,
        HOLDING,
        DISTILLED_RULES,
    ]
    assert scopes[0].start == 0
    for earlier, later in zip(scopes, scopes[1:]):
        assert earlier.end == later.start


def test_scope_offsets_index_into_the_source_text():
    text = (
        "322 A.2d 630 1974 CONTRACTS A narrative of the facts follows. "
        "Whether it was lawful is the question."
    )
    scopes = split_scopes(text)
    for scope in scopes:
        assert text[scope.start : scope.end] == scope.text


@pytest.mark.skipif(not BRIEF.exists(), reason="benchmark brief not present")
def test_benchmark_brief_segments_into_eight_irac_scopes():
    from interface import submission

    text = submission.extract_text(BRIEF.read_bytes(), BRIEF.name)
    scopes = split_scopes(text)

    assert [scope.name for scope in scopes] == list(SCOPE_NAMES)
    for scope in scopes:
        assert scope.chars == BENCHMARK_CHARS[scope.name], (
            f"{scope.name}: {scope.chars} != {BENCHMARK_CHARS[scope.name]}"
        )
    assert sum(scope.chars for scope in scopes) == sum(BENCHMARK_CHARS.values())
