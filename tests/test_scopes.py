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

#: Per-scope character counts measured in `docs/audit/CONNECTOR_AUDIT.md` §5,
#: re-measured after `interface/pdf_text.py` stopped emitting the brief's
#: undecodable font glyphs (see `normalise_control_glyphs`).
#:
#: Two counts moved, both by exactly the control bytes that are no longer text,
#: and nothing else changed:
#:
#: * `CITATION` 29 -> 27. Its 29 characters were
#:   `322 A.2d 630 \x011974\x02 CONTRACTS`; two of them were the control bytes
#:   bracketing the year, and the scope now reads `322 A.2d 630 1974 CONTRACTS`.
#: * `REASONING` 1495 -> 1494. One control byte in this scope sat beside a
#:   space, so removing it and collapsing the gap costs one character.
#:
#: The other six scopes, including `FACTS` at 2009 and `DISTILLED_RULES` at 599,
#: are unchanged: their control bytes were in word-medial position and an
#: apostrophe occupies exactly the character the glyph did. The sum falls from
#: 4838 to 4835, against 4,842 extracted characters.
#:
#: These are the counts the code produces today. If they move again, this dict
#: moves with them in the same commit as the change that moved them.
BENCHMARK_CHARS = {
    CITATION: 27,
    FACTS: 2009,
    PROCEDURAL_POSTURE: 188,
    ISSUE: 218,
    RULE: 163,
    REASONING: 1494,
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
def test_benchmark_brief_segments_into_eight_irac_scopes(monkeypatch):
    from interface import submission, pdf_text

    # The BENCHMARK_CHARS table was measured against the built-in
    # content-stream parser. PDFium's text layer extraction differs at
    # word boundaries on this specific PDF (some inter-word spaces are
    # not encoded as space characters in the file). This test measures
    # split_scopes, not extraction quality: force the built-in parser so
    # it continues to test what it was written to test.
    # Re-baselining the benchmark against PDFium output is a separate
    # change, and should not enshrine the missing-space behaviour.
    monkeypatch.setattr(
        pdf_text, "_extract_via_pdfium",
        lambda _data: (_ for _ in ()).throw(RuntimeError("forced builtin")),
    )

    text = submission.extract_text(BRIEF.read_bytes(), BRIEF.name)
    scopes = split_scopes(text)

    assert [scope.name for scope in scopes] == list(SCOPE_NAMES)
    for scope in scopes:
        assert scope.chars == BENCHMARK_CHARS[scope.name], (
            f"{scope.name}: {scope.chars} != {BENCHMARK_CHARS[scope.name]}"
        )
    assert sum(scope.chars for scope in scopes) == sum(BENCHMARK_CHARS.values())
