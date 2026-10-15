"""Extract the text layer from a PDF without a third-party dependency.

Why this module exists
----------------------
The GRIC contract (``GRIC_v1.0_INTERFACE_SPEC.md`` §3.1) declares that a
``CaseSpec`` evidence manifest may carry artifacts of type
``pdf | docx | eml | image | video | json | txt``. Only ``eml`` had an
implementation, and every other type fell through to

    body = raw.decode("utf-8", errors="replace")

which for a PDF is not a degraded read, it is a wrong one: a PDF is a binary
container whose text lives in Flate-compressed content streams, so decoding it
as UTF-8 yields replacement characters and the document's actual words are
never seen. The pipeline then signs a control record about content it never
read.

Scope and honesty about limits
------------------------------
This is a **text-layer** extractor, not a PDF renderer. It handles the common
case: uncompressed or Flate-compressed content streams, literal and hex
strings, and the ``Tj`` / ``TJ`` / ``'`` / ``"`` text-showing operators.

It cannot recover text that is not there. A scanned page is an image; this
module refuses it (``NoTextFound``) rather than returning "". Refusing is the
point: an empty extraction must never be mistaken for a document with no
content. Callers that need OCR or exotic encodings (custom ``ToUnicode``
CMaps over embedded subset fonts, encrypted PDFs) should install ``pypdf`` and
use it see ``extract_text`` for the preferred-order contract.
"""
from __future__ import annotations

import re
import zlib
from pathlib import Path

PDF_MAGIC = b"%PDF-"
MAGIC_SCAN_BYTES = 1024

# A PDF string is followed by an operator; a kerning adjustment of -120/1000 em
# or more is a word gap in every producer seen so far.
WORD_GAP_THRESHOLD = -120
MIN_USEFUL_CHARS = 1


class PdfTextError(RuntimeError):
    """Base class for extraction failures."""


class NotAPdf(PdfTextError):
    """The bytes do not begin with the PDF magic number."""


class NoTextFound(PdfTextError):
    """The PDF carries no recoverable text layer (e.g. a scan)."""


# One pass over a content stream, in file order. Alternatives are ordered so
# that multi-character tokens win over their first character.
_TOKEN_RE = re.compile(
    rb"(?P<str>\((?:\\.|[^\\()])*\))"
    rb"|(?P<hex><[0-9A-Fa-f\s]*>)"
    rb"|(?P<arr>\[)"
    rb"|(?P<arrend>\])"
    rb"|(?P<num>-?\d+\.?\d*)"
    rb"|(?P<name>/[^\s/\[\]()<>]+)"
    rb"|(?P<op>[A-Za-z*'\"]+)",
    re.DOTALL,
)

_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)

_ESCAPES = {
    ord("n"): 0x0A,
    ord("r"): 0x0D,
    ord("t"): 0x09,
    ord("b"): 0x08,
    ord("f"): 0x0C,
    ord("("): 0x28,
    ord(")"): 0x29,
    ord("\\"): 0x5C,
}

_RUN_BREAK_OPS = frozenset({b"Td", b"TD", b"Tm", b"T*", b"ET"})


def looks_like_pdf(data: bytes) -> bool:
    """True when the payload opens with a PDF header within the first KiB."""
    return data[:MAGIC_SCAN_BYTES].lstrip().startswith(PDF_MAGIC)


def _decode_literal(raw: bytes) -> str:
    """Decode a PDF literal string ``(...)`` including backslash escapes."""
    body = raw[1:-1]
    out = bytearray()
    i = 0
    length = len(body)
    while i < length:
        byte = body[i]
        if byte == 0x5C and i + 1 < length:
            nxt = body[i + 1]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
                i += 2
                continue
            if 0x30 <= nxt <= 0x37:  # octal escape, up to three digits
                j = i + 1
                digits = bytearray()
                while j < length and len(digits) < 3 and 0x30 <= body[j] <= 0x37:
                    digits.append(body[j])
                    j += 1
                out.append(int(digits, 8) & 0xFF)
                i = j
                continue
            if nxt in (0x0A, 0x0D):  # line continuation
                i += 2
                continue
            out.append(nxt)
            i += 2
            continue
        out.append(byte)
        i += 1
    return out.decode("latin-1")


def _decode_hex(raw: bytes) -> str:
    """Decode a PDF hex string ``<...>``; UTF-16BE when it looks like text."""
    digits = re.sub(rb"\s+", b"", raw[1:-1])
    if len(digits) % 2:
        digits += b"0"
    try:
        payload = bytes.fromhex(digits.decode("ascii"))
    except ValueError:
        return ""
    try:
        return payload.decode("utf-16-be")
    except UnicodeDecodeError:
        return payload.decode("latin-1")


def _stream_text(data: bytes) -> list[str]:
    """Walk one decoded content stream, returning its text runs in order."""
    runs: list[str] = []
    current = ""
    pending: list[tuple[str, object]] = []
    array_items: list[tuple[str, object]] = []
    in_array = False

    for match in _TOKEN_RE.finditer(data):
        kind = match.lastgroup
        token = match.group(0)

        if kind == "str":
            (array_items if in_array else pending).append(
                ("s", _decode_literal(token))
            )
        elif kind == "hex":
            (array_items if in_array else pending).append(
                ("s", _decode_hex(token))
            )
        elif kind == "arr":
            in_array = True
            array_items = []
        elif kind == "arrend":
            in_array = False
            pending.append(("a", array_items))
            array_items = []
        elif kind == "num":
            if in_array:
                try:
                    array_items.append(("n", float(token)))
                except ValueError:
                    pass
            else:
                pending.append(("n", token))
        elif kind == "name":
            pending.append(("name", token))
        elif kind == "op":
            current = _apply_operator(token, pending, current, runs)
            pending = []

    if current:
        runs.append(current)
    return runs


def _apply_operator(
    op: bytes,
    pending: list[tuple[str, object]],
    current: str,
    runs: list[str],
) -> str:
    """Apply one text operator, returning the new in-progress run."""
    if op == b"Tj":
        for kind, value in pending:
            if kind == "s":
                current += str(value)
    elif op == b"TJ":
        for kind, value in pending:
            if kind == "a" and isinstance(value, list):
                for item_kind, item_value in value:
                    if item_kind == "s":
                        current += str(item_value)
                    elif item_kind == "n" and float(item_value) <= WORD_GAP_THRESHOLD:
                        current += " "
    elif op in (b"'", b'"'):
        if current:
            runs.append(current)
            current = ""
        for kind, value in pending:
            if kind == "s":
                current += str(value)
    elif op in _RUN_BREAK_OPS:
        if current:
            runs.append(current)
            current = ""
    return current


def _decode_stream(chunk: bytes) -> bytes | None:
    """Return the stream's decoded bytes, or None when it is not Flate."""
    try:
        return zlib.decompress(chunk)
    except zlib.error:
        return None


def extract_text(data: bytes) -> str:
    """Return the text layer of a PDF, or raise.

    Raises:
        NotAPdf: the payload has no PDF header.
        NoTextFound: the PDF has no recoverable text layer. Callers must treat
            this as a failure, not as an empty document.
    """
    if not looks_like_pdf(data):
        raise NotAPdf("payload does not begin with a PDF header")

    runs: list[str] = []
    for match in _STREAM_RE.finditer(data):
        decoded = _decode_stream(match.group(1))
        if decoded is not None:
            runs.extend(_stream_text(decoded))

    text = " ".join(run.strip() for run in runs if run.strip())
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) < MIN_USEFUL_CHARS:
        raise NoTextFound(
            "no text layer recovered; the document may be a scan or use an "
            "unsupported font encoding. Install 'pypdf' for broader coverage."
        )
    return text


def extract_text_from_file(path: str | Path) -> str:
    """Read ``path`` and return its text layer. See ``extract_text``."""
    return extract_text(Path(path).read_bytes())
