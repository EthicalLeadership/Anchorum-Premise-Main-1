"""Find the heading lines of a document, with their offsets.

This is the first stage of :func:`interface.scopes.split_scopes`: a document
that carries its own headings is segmented by them, ahead of the cue table and
ahead of blank-line blocking, because a heading is the author stating where a
part begins rather than the product inferring it.

The module decides only what a heading line *is* — a markdown ATX heading, or a
line carrying nothing but a short label (optionally ending in a colon or a
period) — and hands back every candidate with its offset. Whether a label names
a scope is the caller's decision: the vocabulary belongs with the other
segmentation patterns in :mod:`interface.scopes`, so this module imports nothing
from it and cannot drift from it.
"""

from __future__ import annotations

import re
from typing import Mapping

#: A markdown ATX heading: 1-6 ``#``, a label, optional closing ``#``s.
_MARKDOWN_HEADING = re.compile(
    r"^[ \t]{0,3}#{1,6}[ \t]*(?P<label>[^\n]*?)[ \t]*#*[ \t]*$", re.MULTILINE
)

#: A line that is only a short label, optionally followed by ``:`` or ``.``.
#: Sentence punctuation is excluded from the label itself so a line of prose
#: ("Block one text.") is not mistaken for a heading carrying a label.
_LABEL_LINE = re.compile(
    r"^[ \t]*(?P<label>[A-Za-z][A-Za-z0-9'’ \-/&]*?)[ \t]*[.:]?[ \t]*$", re.MULTILINE
)

#: Markdown emphasis a label may wear, e.g. ``**FACTS**``.
_DECORATION = "*_` \t"

#: A label longer than this is a sentence that happens to be alone on its line.
MAX_LABEL_CHARS = 48

_WHITESPACE = re.compile(r"\s+")


def normalise_label(raw: str) -> str:
    """Return the comparable form of a heading label: lower case, single-spaced.

    Trailing emphasis, a trailing colon or period and repeated whitespace are
    removed, because every one of them is decoration rather than meaning.
    """
    label = raw.strip(_DECORATION)
    label = label.rstrip(":.").strip(_DECORATION)
    return _WHITESPACE.sub(" ", label).casefold()


def heading_lines(text: str) -> list[tuple[int, str]]:
    """Every heading-shaped line in ``text``, as ``(offset, normalised label)``.

    Offsets are the first character of the line, so a caller that segments on
    them keeps the heading with the part it introduces. Markdown headings win
    over plain labels at the same offset. Order follows the document.
    """
    found: dict[int, str] = {}

    for match in _MARKDOWN_HEADING.finditer(text):
        label = normalise_label(match.group("label"))
        if label:
            found.setdefault(match.start(), label)

    for match in _LABEL_LINE.finditer(text):
        offset = match.start()
        if offset in found:
            continue
        label = normalise_label(match.group("label"))
        if label:
            found.setdefault(offset, label)

    return [(offset, found[offset]) for offset in sorted(found)]


def heading_starts(
    text: str, aliases: Mapping[str, str]
) -> list[tuple[str, int]]:
    """Scope starts that the document's own headings declare.

    ``aliases`` maps a normalised label to a scope name. A label that names no
    scope is ignored rather than guessed at, so a document with an
    ``INTRODUCTION`` heading does not gain an invented part. Each scope name is
    emitted once, at its first heading: a second ``FACTS`` heading continues the
    parts it already belongs to, and a duplicate name would otherwise make the
    record ambiguous.
    """
    starts: list[tuple[str, int]] = []
    seen: set[str] = set()

    for offset, label in heading_lines(text):
        if len(label) > MAX_LABEL_CHARS:
            continue
        name = aliases.get(label)
        if name is None or name in seen:
            continue
        seen.add(name)
        starts.append((name, offset))

    return starts
