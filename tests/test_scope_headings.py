"""Pins for heading detection, the first stage of IRAC segmentation.

Two properties are pinned separately: what counts as a heading line
(`heading_lines`), and which headings name a scope (`heading_starts`). The
segmentation that consumes them is pinned in `tests/test_scopes.py`.

Per the plan's pin rule, each test fails when the behaviour it describes is
reverted: the label and offset pins fail if heading detection is deleted, and
the alias pins fail if an unknown heading is allowed to invent a scope.
"""

import pytest

from interface.scope_headings import (
    MAX_LABEL_CHARS,
    heading_lines,
    heading_starts,
    normalise_label,
)
from interface.scope_vocabulary import FACTS, HEADING_ALIASES, HOLDING, ISSUE


class TestNormaliseLabel:
    def test_case_whitespace_and_trailing_colon_are_removed(self):
        assert normalise_label("  STATEMENT   of Facts:  ") == "statement of facts"

    def test_trailing_period_is_removed(self):
        assert normalise_label("Holding.") == "holding"

    def test_surrounding_emphasis_is_removed(self):
        assert normalise_label("**FACTS**") == "facts"
        assert normalise_label("_Issue_") == "issue"

    def test_a_bare_label_is_unchanged_apart_from_case(self):
        assert normalise_label("Distilled Rules") == "distilled rules"


class TestHeadingLine:
    def test_markdown_atx_heading_is_found(self):
        assert heading_lines("## Facts\nbody text\n")[0][1] == "facts"

    def test_markdown_heading_tolerates_closing_hashes(self):
        assert heading_lines("### ISSUE ###\nbody\n")[0][1] == "issue"

    def test_bold_label_line_is_found(self):
        assert heading_lines("**FACTS**\nbody text\n")[0][1] == "facts"

    def test_uppercase_label_with_colon_is_found(self):
        assert heading_lines("HOLDING:\nbody text\n")[0][1] == "holding"

    def test_offsets_are_line_starts(self):
        # "first line" is heading-shaped too - short and unpunctuated - so the
        # candidate list is not the scope list. The alias lookup in
        # `heading_starts` is what rejects it.
        text = "first line\n## Facts\nbody\n"
        offset = dict((label, offset) for offset, label in heading_lines(text))["facts"]
        assert text.index("## Facts") == offset

    def test_prose_lines_are_not_headings(self):
        text = (
            "The court held that the modification was unenforceable.\n"
            "Murray collected rubbish under a fixed annual contract.\n"
        )
        assert heading_lines(text) == []

    def test_a_label_over_the_length_ceiling_is_rejected(self):
        line = "a" * (MAX_LABEL_CHARS + 1) + "\n"
        assert heading_lines(line) == []

    def test_numeric_and_punctuated_lines_are_not_headings(self):
        assert heading_lines("1. Facts\n---\n(R.I. 1974)\n") == []

    def test_blank_input_has_no_headings(self):
        assert heading_lines("") == []
        assert heading_lines("\n\n") == []


class TestHeadingStart:
    def test_known_labels_map_to_their_scope_in_document_order(self):
        text = "## Facts\none\n\n## Issue\ntwo\n\n## Holding\nthree\n"
        assert [name for name, _ in heading_starts(text, HEADING_ALIASES)] == [
            FACTS,
            ISSUE,
            HOLDING,
        ]

    def test_unknown_labels_are_ignored_rather_than_guessed_at(self):
        text = "# Introduction\none\n\n# Notes\ntwo\n"
        assert heading_starts(text, HEADING_ALIASES) == []

    def test_a_repeated_scope_heading_is_emitted_once_at_its_first_occurrence(self):
        text = "## Facts\none\n\n## Facts\ntwo\n\n## Holding\nthree\n"
        starts = heading_starts(text, HEADING_ALIASES)
        assert [name for name, _ in starts] == [FACTS, HOLDING]
        assert starts[0][1] == 0

    def test_starts_are_strictly_increasing(self):
        text = "## Issue\none\n\n## Facts\ntwo\n\n## Holding\nthree\n"
        offsets = [offset for _, offset in heading_starts(text, HEADING_ALIASES)]
        assert offsets == sorted(offsets)
        assert len(set(offsets)) == len(offsets)

    def test_a_single_heading_is_returned_as_a_single_start(self):
        # The two-part threshold belongs to the caller; this function reports
        # what it found and does not decide whether that is enough to segment on.
        starts = heading_starts("## Facts\ntext\n", HEADING_ALIASES)
        assert len(starts) == 1


@pytest.mark.parametrize("label", ["facts", "issue", "holding", "rule", "reasoning"])
def test_every_sampled_alias_resolves_to_a_scope_name(label):
    assert isinstance(HEADING_ALIASES[label], str)
