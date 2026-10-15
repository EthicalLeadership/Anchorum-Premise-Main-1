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
