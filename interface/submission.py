"""Turn an uploaded submission into plain text, by artifact type.

Both document entry points the GRIC inspector (``gric_server.py``) and the
dossier bridge (``document.py``) used to decide by extension and then, for
everything that was not ``.eml``, do:

    body = raw.decode("utf-8", errors="replace")

For a PDF that is not a lossy read, it is a wrong one: the document's words
live in a Flate-compressed content stream, so the replacement characters
replace the entire document. The pipeline then committed and signed a control
record about content it had never read.

This module is the single place that decides what an artifact is and refuses
the ones it cannot honestly read, so the two entry points cannot drift apart
again.
"""
from __future__ import annotations

from pathlib import Path

from interface import pdf_text

# Types this module can decode as text. Anything else must be parsed by a
# dedicated reader or refused; it must never be decoded as if it were text.
TEXT_SUFFIXES = frozenset(
    {
        ".txt",
        ".text",
        ".md",
        ".markdown",
        ".json",
        ".jsonl",
        ".csv",
        ".tsv",
        ".xml",
        ".html",
        ".htm",
        ".yaml",
        ".yml",
        ".log",
        ".rst",
        ".ini",
        ".cfg",
        ".toml",
    }
)

# Declared as valid CaseSpec artifact types by GRIC v1.0 §3.1 but not yet
# implemented. Named here so the refusal is specific rather than generic.
UNIMPLEMENTED_SUFFIXES = {
    ".docx": "Word documents",
    ".doc": "Word documents",
    ".odt": "OpenDocument text",
    ".rtf": "rich text",
    ".png": "images",
    ".jpg": "images",
    ".jpeg": "images",
    ".tif": "images",
    ".tiff": "images",
    ".gif": "images",
    ".mp4": "video",
    ".mov": "video",
    ".mkv": "video",
    ".avi": "video",
}


class UnsupportedSubmission(RuntimeError):
    """The submission is not in a format this connector can read."""


def _suffix(filename: str) -> str:
    return Path(filename).suffix.lower() if filename else ""


def is_eml(data: bytes, filename: str = "") -> bool:
    """True for a MIME message, by name or by RFC 5322 header sniffing."""
    if _suffix(filename) == ".eml":
        return True
    head = data[:2048]
    return head.startswith(b"From ") or b"\nMessage-ID:" in head or head.startswith(b"Message-ID:")


def extract_text(data: bytes, filename: str = "") -> str:
    """Return the readable text of a submission.

    Dispatch order is by content first, then by name, because a mislabelled
    file is a real occurrence and the bytes are the authority.

    Raises:
        pdf_text.NotAPdf / pdf_text.NoTextFound: a PDF was claimed but could
            not be read, or carried no text layer.
        UnsupportedSubmission: the artifact is a binary type this connector
            does not implement. It is refused rather than decoded as text.
    """
    suffix = _suffix(filename)

    if pdf_text.looks_like_pdf(data) or suffix == ".pdf":
        return pdf_text.extract_text(data)

    if not data:
        raise UnsupportedSubmission("submission is empty")

    # A declared binary type is refused before any decode is attempted. Order
    # matters: a ZIP container (docx, odt) contains long runs of bytes that are
    # valid UTF-8, so "it decoded" is not evidence that it is text.
    if suffix in UNIMPLEMENTED_SUFFIXES:
        raise UnsupportedSubmission(
            f"{UNIMPLEMENTED_SUFFIXES[suffix]} ({suffix}) are declared in the "
            "GRIC CaseSpec evidence manifest but have no reader in this "
            "connector; refusing rather than decoding binary as text"
        )

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass

    if suffix in TEXT_SUFFIXES:
        # A text format that is not valid UTF-8 is still text: read it the
        # lossy way, but only after the strict attempt above has shown it is
        # genuinely malformed rather than merely being binary.
        return data.decode("utf-8", errors="replace")

    raise UnsupportedSubmission(
        f"cannot read {suffix or 'headerless binary'} as text; the GRIC "
        "manifest accepts pdf, docx, eml, image, video, json and txt, and "
        "only eml, pdf and the text formats above are implemented"
    )


def extract_text_from_file(path: str | Path) -> str:
    """Read ``path`` and return its readable text. See ``extract_text``."""
    file_path = Path(path)
    return extract_text(file_path.read_bytes(), file_path.name)


def extract_text_with_pages(
    data: bytes, filename: str = ""
) -> tuple[str, list[tuple[int, int, int]] | None]:
    """Return text plus per-page spans, or ``(text, None)`` for non-PDF types.

    Mirrors ``extract_text``'s dispatch exactly; the two functions must
    agree on what text is extracted and how refusals are raised. They
    are kept as separate functions rather than ``extract_text`` being
    reimplemented in terms of this one, because the pdfium path in
    ``pdf_text.extract_text_with_pages`` normalizes per page rather than
    across the join — usually byte-identical to ``extract_text`` output,
    not guaranteed. Refactoring ``extract_text`` to call through this
    wrapper would quietly move every existing caller onto that slightly
    different text, and the consumers (scope splitting, doctrine
    matching) are written against the current form.

    Non-PDF artifacts (text, eml, and the suffix-decode fallbacks) have
    no page concept: the second element is ``None``. A caller that uses
    this function uniformly does not have to special-case its input
    types, only check whether spans came back.

    Raises:
        UnsupportedSubmission: same conditions as ``extract_text`` — the
            refusal happens inside ``extract_text``, which is called for
            every non-PDF input, so the error surface is identical.
        pdf_text.NotAPdf / pdf_text.NoTextFound: same as ``extract_text``
            for a PDF that turns out to be unreadable or empty.
    """
    suffix = _suffix(filename)

    if pdf_text.looks_like_pdf(data) or suffix == ".pdf":
        return pdf_text.extract_text_with_pages(data)

    return extract_text(data, filename), None
