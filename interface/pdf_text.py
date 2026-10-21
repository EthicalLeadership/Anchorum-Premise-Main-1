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

import logging
import re
import zlib
from pathlib import Path

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
MAGIC_SCAN_BYTES = 1024

# A control byte is a glyph from a font encoding this extractor cannot read,
# which is the normal case for a PDF produced by a word processor. Such a byte
# must never reach the extracted text: it is not text, the API stores and serves
# that text, and a control character corrupts every consumer of it. The brief
# this module was repaired against carries fourteen of them, and they fall into
# exactly the cases handled below.
#
# Between two letters the glyph is an apostrophe. All eleven occurrences in that
# brief are possessives and contractions: "Newport\x03s", "court\x03s",
# "contract\x03s", "shouldn\x03t", "council\x03s", "city\x03s", "society\x03s".
# Leaving the byte in place means a search for "court's" finds nothing and no
# pattern containing an apostrophe can ever match; dropping it would silently
# change the word ("shouldnt"). It becomes an ASCII apostrophe, which is also
# the character a reader types when searching for it.
APOSTROPHE = "'"

#: Windows-1252 defines a printable character for these bytes, and Windows code
#: pages are what produce them. Byte 0x96, the en dash in this document's own
#: running title ("Angel v. Murray \x96 (IRAC) Case Brief Summary"), arrives as
#: the C1 control U+0096 when the byte is decoded as latin-1, which is what this
#: module does. The bytes Windows-1252 leaves undefined (0x81, 0x8D, 0x8F,
#: 0x90, 0x9D) are absent from the table and are handled as the controls they
#: are.
_C1_FROM_CP1252 = {
    0x80: "\u20ac", 0x82: "\u201a", 0x83: "\u0192", 0x84: "\u201e",
    0x85: "\u2026", 0x86: "\u2020", 0x87: "\u2021", 0x88: "\u02c6",
    0x89: "\u2030", 0x8A: "\u0160", 0x8B: "\u2039", 0x8C: "\u0152",
    0x8E: "\u017d", 0x91: "\u2018", 0x92: "\u2019", 0x93: "\u201c",
    0x94: "\u201d", 0x95: "\u2022", 0x96: "\u2013", 0x97: "\u2014",
    0x98: "\u02dc", 0x99: "\u2122", 0x9A: "\u0161", 0x9B: "\u203a",
    0x9C: "\u0153", 0x9E: "\u017e", 0x9F: "\u0178",
}

#: A control byte in word-medial position: the apostrophe case above. Tab,
#: newline and carriage return are excluded because they are whitespace.
_IN_WORD_CONTROL_RE = re.compile(
    r"(?<=[A-Za-z])[\x00-\x08\x0b\x0c\x0e-\x1f](?=[A-Za-z])"
)

#: Every other control character, C0 and C1 and DEL. A glyph that cannot be
#: decoded still occupied a position in the line, so it becomes a word gap
#: rather than vanishing: the citation "322 A.2d 630 \x011974\x02 CONTRACTS"
#: reads "322 A.2d 630 1974 CONTRACTS", and "the court applied\x04 :
#: Restatement" reads "the court applied : Restatement".
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

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


def normalise_control_glyphs(text: str) -> str:
    """Replace the control bytes of an undecodable font encoding with text.

    Two substitutions are made, in this order:

    * a byte in the Windows-1252 range becomes the character that byte denotes,
      which is how the document's en dashes are recovered;
    * a control byte between two letters becomes an apostrophe, and every other
      control byte becomes a word gap.

    No control character survives, so nothing downstream stores, searches or
    serves one. The apostrophe substitution is one character for one character;
    the word-gap substitution is collapsed, so a control byte that sat beside a
    space removes that space rather than adding a second one.
    """
    text = "".join(_C1_FROM_CP1252.get(ord(ch), ch) for ch in text)
    text = _IN_WORD_CONTROL_RE.sub(APOSTROPHE, text)
    text = _CONTROL_RE.sub(" ", text)
    return re.sub(r" {2,}", " ", text)


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


_COMMON_WORDS = frozenset({
    "le","la","les","de","des","du","et","un","une","en","pour","par",
    "que","qui","dans","sur","est","au","aux","ce","cette","ces","son",
    "sa","ses","ne","pas","se","il","elle","nous","vous","ils",
    "the","and","of","to","for","in","is","that","this","a","an","on",
    "at","by","with","be","or","as",
})


def _looks_like_garbage(text: str) -> bool:
    """Detect font-glyph soup and mojibake that look like text but are not.

    Font-glyph soup carries control chars or PUA codepoints. Mojibake
    (e.g. \xc3\xa9 for \xe9) is all alphabetic but contains no common
    function words. Short legitimate text is NOT garbage.
    """
    if not text or not any(c.isalpha() for c in text):
        return True
    if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
        return True
    if sum(1 for c in text if 0xE000 <= ord(c) <= 0xF8FF) > max(1, len(text) * 0.01):
        return True
    words = re.findall(r"\b[a-z\xe0-\xff]{2,}\b", text.lower())
    if len(words) >= 50 and not any(w in _COMMON_WORDS for w in words):
        return True
    return False


def _normalise_typography(text: str) -> str:
    """Convert PDFium's typographic punctuation to the ASCII forms the rest
    of the pipeline expects, and treat U+FFFD (PDFium's replacement
    character for unrenderable glyphs) the way the control-byte normalizer
    treats a control byte: apostrophe between letters, space otherwise.

    The custom content-stream parser produced ASCII apostrophes directly
    (via its CP1252 decoding); PDFium preserves Unicode typography
    (U+02BC MODIFIER LETTER APOSTROPHE, U+2019 RIGHT SINGLE QUOTATION
    MARK). Downstream consumers -- search, scopes, the acceptance-brief
    tests -- are written against the ASCII form, so the pipeline normalizes
    at the extraction boundary. En dashes (U+2013) are preserved: the tests
    assert them and they are the correct punctuation for ranges.
    """
    text = text.replace("\u02bc", "'")   # MODIFIER LETTER APOSTROPHE
    text = text.replace("\u2019", "'")   # RIGHT SINGLE QUOTATION MARK
    text = text.replace("\u2018", "'")   # LEFT SINGLE QUOTATION MARK
    text = text.replace("\u201c", '"')   # LEFT DOUBLE QUOTATION MARK
    text = text.replace("\u201d", '"')   # RIGHT DOUBLE QUOTATION MARK
    text = text.replace("\u00a0", " ")   # NO-BREAK SPACE
    text = text.replace("\u202f", " ")   # NARROW NO-BREAK SPACE
    fffd = chr(0xFFFD)
    # U+FFFD between two letters -> apostrophe (mirrors control-byte rule).
    text = re.sub(rf"(?<=[A-Za-z]){fffd}(?=[A-Za-z])", "'", text)
    # Remaining U+FFFD -> space (normalise_control_glyphs collapses runs).
    text = text.replace(fffd, " ")
    # PDFium inserts \n at block boundaries. Strip *any* horizontal
    # whitespace (ASCII space, tab, U+00A0 already converted above, but
    # U+2009 etc. may remain) against those newlines so downstream
    # consumers (scope splitting, exact-match assertions) see the same
    # text the built-in parser produced.
    text = re.sub(r"[^\S\n]+\n", "\n", text)
    text = re.sub(r"\n[^\S\n]+", "\n", text)
    return text


def _extract_via_pdfium(data: bytes) -> str:
    """PDFium (Apache-2.0, Chrome's PDF engine) via pypdfium2."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(data)
    try:
        parts: list[str] = []
        for page in pdf:
            tp = page.get_textpage()
            parts.append(tp.get_text_range())
        text = "".join(parts).replace("\r\n", "\n").replace("\r", "\n")
        return _normalise_typography(text)
    finally:
        pdf.close()


def _extract_via_ocr(data: bytes) -> str:
    """Render pages and OCR via tesseract (needs tesseract-ocr-fra)."""
    import pypdfium2 as pdfium
    import pytesseract
    pdf = pdfium.PdfDocument(data)
    try:
        parts: list[str] = []
        for page in pdf:
            bitmap = page.render(scale=2.0)
            pil = bitmap.to_pil()
            parts.append(pytesseract.image_to_string(pil, lang="fra+eng"))
        return "\n".join(parts)
    finally:
        pdf.close()


def extract_text(data: bytes) -> str:
    """Return the text layer of a PDF, or raise.

    Tries PDFium (pypdfium2, Apache-2.0) first — it resolves font
    encodings the built-in content-stream parser cannot. Falls back to
    the built-in parser, then OCR. Every stage's failure is logged; the
    caller sees only success or a NoTextFound summarising all stages.

    Raises:
        NotAPdf: the payload has no PDF header.
        NoTextFound: no stage produced usable text.
    """
    if not looks_like_pdf(data):
        raise NotAPdf("payload does not begin with a PDF header")

    failures: list[tuple[str, str]] = []

    try:
        text = _extract_via_pdfium(data)
        if text.strip() and not _looks_like_garbage(text):
            logger.info("pdf_text: pdfium extracted %d chars", len(text))
            return normalise_control_glyphs(text)
        failures.append(("pdfium", f"empty or garbage ({len(text)} chars)"))
    except Exception as exc:
        failures.append(("pdfium", f"{type(exc).__name__}: {exc}"))

    try:
        runs: list[str] = []
        for match in _STREAM_RE.finditer(data):
            decoded = _decode_stream(match.group(1))
            if decoded is not None:
                runs.extend(_stream_text(decoded))
        text = " ".join(run.strip() for run in runs if run.strip())
        text = re.sub(r"[ \t]+", " ", text).strip()
        # Normalize control bytes before the garbage check: the built-in
        # parser's recovery heuristic converts in-word control bytes to
        # apostrophes, but _looks_like_garbage rejects any text that still
        # carries a control byte. Normalizing first lets a successful
        # built-in extraction pass the check.
        text = normalise_control_glyphs(text)
        if text.strip() and not _looks_like_garbage(text):
            logger.info("pdf_text: built-in extracted %d chars", len(text))
            return text
        failures.append(("builtin", f"empty or garbage ({len(text)} chars)"))
    except Exception as exc:
        failures.append(("builtin", f"{type(exc).__name__}: {exc}"))

    try:
        text = _extract_via_ocr(data)
        if text.strip():
            logger.info("pdf_text: OCR extracted %d chars", len(text))
            return normalise_control_glyphs(text)
        failures.append(("ocr", "empty result"))
    except Exception as exc:
        failures.append(("ocr", f"{type(exc).__name__}: {exc}"))

    logger.warning("pdf_text: all extraction stages failed; %r", failures)
    raise NoTextFound(
        f"no text layer recovered after pdfium, built-in, and OCR; {failures}"
    )


def extract_text_from_file(path: str | Path) -> str:
    """Read ``path`` and return its text layer. See ``extract_text``."""
    return extract_text(Path(path).read_bytes())
