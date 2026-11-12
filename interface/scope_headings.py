"""Find the heading lines of a document, with their offsets.

This is the first stage of :func:`interface.scopes.split_scopes`: a document
that carries its own headings is segmented by them, ahead of the cue table and
ahead of blank-line blocking, because a heading is the author stating where a
part begins rather than the product inferring it.

The module decides only what a heading line *is* - a markdown ATX heading, or a
line carrying nothing but a short label, optionally decorated or followed by a
colon or a period - and hands back every candidate with its offset. Whether a
label names a scope is the caller's decision: the vocabulary belongs with the
other segmentation patterns in :mod:`interface.scopes`, so this module imports
nothing from it and cannot drift from it.

Scanning is per line rather than one regex over the whole document. A line that
is too long to be a heading is rejected on its length before any pattern runs,
so a document that extracts to a single 150,000-character line - the brief this
product was built to read is one - costs nothing here.
"""

from __future__ import annotations

import re
from typing import Mapping

#: A markdown ATX heading's body: 1-6 ``#``, a label, optional closing ``#``s.
_MARKDOWN_HEADING = re.compile(r"#{1,6}[ \t]*(?P<label>.*?)[ \t]*#*")

#: A line that is only a short label, optionally followed by ``:`` or ``.``.
#: Sentence punctuation is excluded from the label itself, so a line of prose
#: is not mistaken for a heading carrying a label.
_LABEL_LINE = re.compile(
    r"(?P<label>[*_`]{0,3}[A-Za-z][A-Za-z0-9'\u2019 \-/&]*?[*_`]{0,3})[ \t]*[.:]?"
)

#: Markdown emphasis a label may wear, e.g. ``**FACTS**``.
_DECORATION = "*_` \t"

#: A label longer than this is a sentence that happens to be alone on its line.
MAX_LABEL_CHARS = 48

#: Room for the ``###`` prefix, surrounding emphasis and a trailing colon.
MAX_HEADING_LINE_CHARS = MAX_LABEL_CHARS + 8

_WHITESPACE = re.compile(r"\s+")


def normalise_label(raw: str) -> str:
    """Return the comparable form of a heading label: lower case, single-spaced.

    Surrounding emphasis, a trailing colon or period and repeated whitespace are
    removed, because every one of them is decoration rather than meaning.
    """
    label = raw.strip(_DECORATION)
    label = label.rstrip(":.").strip(_DECORATION)
    return _WHITESPACE.sub(" ", label).casefold()


def _label_of(line: str) -> str:
    """The normalised label when `line` is shaped like a heading, else ""."""
    stripped = line.strip()
    if not stripped or len(stripped) > MAX_HEADING_LINE_CHARS:
        return ""

    match = _MARKDOWN_HEADING.fullmatch(stripped) or _LABEL_LINE.fullmatch(stripped)
    if match is None:
        return ""

    label = normalise_label(match.group("label"))
    return label if len(label) <= MAX_LABEL_CHARS else ""


def heading_lines(text: str) -> list[tuple[int, str]]:
    """Every heading-shaped line in ``text``, as ``(offset, normalised label)``.

    Offsets are the first character of the line, so a caller that segments on
    them keeps the heading with the part it introduces. Order follows the
    document.
    """
    found: list[tuple[int, str]] = []
    offset = 0

    for line in text.split("\n"):
        label = _label_of(line)
        if label:
            found.append((offset, label))
        offset += len(line) + 1

    return found


def heading_starts(text: str, aliases: Mapping[str, str]) -> list[tuple[str, int]]:
    """Scope starts that the document's own headings declare.

    ``aliases`` maps a normalised label to a scope name. A label that names no
    scope is ignored rather than guessed at, so a document with an
    ``INTRODUCTION`` heading does not gain an invented part. Each scope name is
    emitted once, at its first heading: a second ``FACTS`` heading continues the
    part the first one opened, and a duplicate name would make the record
    ambiguous.
    """
    starts: list[tuple[str, int]] = []
    seen: set[str] = set()

    for offset, label in heading_lines(text):
        name = aliases.get(label)
        if name is None or name in seen:
            continue
        seen.add(name)
        starts.append((name, offset))

    return starts
