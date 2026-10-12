"""Pins for the PDF text connector and the submission dispatcher.

The defect these exist to prevent: a PDF was read with
``raw.decode("utf-8", errors="replace")``. That does not fail — it succeeds
wrongly, filling the pipeline's input with U+FFFD where the document's words
should be, so the control record attests to content nobody read. A test that
only checked "processing returned a result" would have passed throughout.
"""
from __future__ import annotations

import zlib
from pathlib import Path

import pytest

from interface import pdf_text, submission


def _build_pdf(*lines: str) -> bytes:
    """Assemble a minimal single-page PDF whose content stream is Flate-compressed.

    Written by hand rather than pulled from a fixture so the test states what a
    PDF actually is: a binary container with a deflated text stream.
    """
    content = "BT /F1 12 Tf 36 720 Td\n"
    for i, line in enumerate(lines):
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        content += f"({escaped}) Tj 0 -14 Td\n"
    content += "ET"
    stream = zlib.compress(content.encode("latin-1"))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" /Filter /FlateDecode >>\nstream\n"
        + stream
        + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.7\n")
    for number, body in enumerate(objects, start=1):
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    out += b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
    return bytes(out)


# --- pdf_text ---------------------------------------------------------------


class TestLooksLikePdf:
    def test_pdf_header_is_recognised(self):
        assert pdf_text.looks_like_pdf(b"%PDF-1.7\n...") is True

    def test_pdf_header_after_leading_whitespace_is_recognised(self):
        assert pdf_text.looks_like_pdf(b"\n  %PDF-1.4") is True

    def test_mime_message_is_not_a_pdf(self):
        assert pdf_text.looks_like_pdf(b"Message-ID: <a@b>\n\nhello") is False

    def test_empty_payload_is_not_a_pdf(self):
        assert pdf_text.looks_like_pdf(b"") is False


class TestExtractText:
    def test_text_layer_is_recovered(self):
        text = pdf_text.extract_text(
            _build_pdf("Maher sued Newport over $20,000.", "The court reversed.")
        )
        assert "Maher" in text
        assert "Newport" in text
        assert "reversed" in text

    def test_recovered_text_has_no_replacement_characters(self):
        text = pdf_text.extract_text(_build_pdf("consideration"))
        assert "\ufffd" not in text

    def test_non_pdf_payload_raises(self):
        with pytest.raises(pdf_text.NotAPdf):
            pdf_text.extract_text(b"this is plain text, not a PDF")

    def test_pdf_without_a_text_layer_raises_rather_than_returning_empty(self):
        empty = b"%PDF-1.7\n1 0 obj\n<< >>\nendobj\ntrailer\n<< >>\n%%EOF\n"
        with pytest.raises(pdf_text.NoTextFound):
            pdf_text.extract_text(empty)

    def test_escaped_parentheses_survive(self):
        text = pdf_text.extract_text(_build_pdf("Angel (plaintiffs) v. Murray"))
        assert "(plaintiffs)" in text

    def test_decoding_a_pdf_as_utf8_loses_the_text(self):
        """The regression, stated as a test: this is what the old path did."""
        raw = _build_pdf("Maher", "Murray", "Newport", "consideration")
        mangled = raw.decode("utf-8", errors="replace")
        for token in ("Maher", "Murray", "Newport", "consideration"):
            assert token not in mangled
        # And the correct reader still finds them.
        good = pdf_text.extract_text(raw)
        for token in ("Maher", "Murray", "Newport", "consideration"):
            assert token in good


class TestWordGap:
    def test_large_kerning_adjustment_becomes_a_space(self):
        content = b"BT /F1 12 Tf 36 720 Td [(Maher) -400 (Newport)] TJ ET"
        stream = zlib.compress(content)
        pdf = (
            b"%PDF-1.7\n1 0 obj\n<< /Length "
            + str(len(stream)).encode()
            + b" /Filter /FlateDecode >>\nstream\n"
            + stream
            + b"\nendstream\nendobj\ntrailer\n<< >>\n%%EOF\n"
        )
        assert "Maher Newport" in pdf_text.extract_text(pdf)


class TestHexString:
    def test_utf16be_hex_string_is_decoded(self):
        # <004D0061> is "Ma" in UTF-16BE.
        content = b"BT <004D0061006800650072> Tj ET"
        stream = zlib.compress(content)
        pdf = (
            b"%PDF-1.7\n1 0 obj\n<< /Length "
            + str(len(stream)).encode()
            + b" /Filter /FlateDecode >>\nstream\n"
            + stream
            + b"\nendstream\nendobj\ntrailer\n<< >>\n%%EOF\n"
        )
        assert "Maher" in pdf_text.extract_text(pdf)


# --- submission -------------------------------------------------------------


class TestSubmissionDispatch:
    def test_pdf_is_parsed_not_decoded(self):
        raw = _build_pdf("Maher", "Newport")
        assert "Maher" in submission.extract_text(raw, "brief.pdf")

    def test_mislabelled_pdf_is_still_parsed(self):
        """Content wins over the name: the bytes are the authority."""
        raw = _build_pdf("Maher")
        assert "Maher" in submission.extract_text(raw, "brief.txt")

    def test_text_format_is_decoded(self):
        assert submission.extract_text(b"hello", "notes.txt") == "hello"

    def test_utf8_without_a_suffix_is_decoded(self):
        assert submission.extract_text("café".encode("utf-8"), "") == "café"

    def test_declared_binary_type_is_refused(self):
        docx = b"PK\x03\x04\x14\x00\x06\x00" + b"\x00" * 40
        with pytest.raises(submission.UnsupportedSubmission):
            submission.extract_text(docx, "brief.docx")

    def test_refusal_names_the_type(self):
        with pytest.raises(submission.UnsupportedSubmission) as excinfo:
            submission.extract_text(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, "scan.png")
        assert "images" in str(excinfo.value)

    def test_unknown_binary_is_refused(self):
        with pytest.raises(submission.UnsupportedSubmission):
            submission.extract_text(b"\x00\x01\x02\xff\xfe", "blob.bin")

    def test_empty_submission_is_refused(self):
        with pytest.raises(submission.UnsupportedSubmission):
            submission.extract_text(b"", "empty.txt")

    def test_headerless_binary_is_refused_not_replaced(self):
        """The old behaviour decoded this with errors='replace'; now it refuses."""
        binary = bytes(range(256)) * 4
        with pytest.raises(submission.UnsupportedSubmission):
            submission.extract_text(binary, "")


class TestIsEml:
    def test_eml_suffix_is_a_message(self):
        assert submission.is_eml(b"anything", "mail.eml") is True

    def test_message_id_header_makes_it_a_message(self):
        assert submission.is_eml(b"Message-ID: <x@y>\n\nbody", "noextension") is True

    def test_pdf_is_not_a_message(self):
        assert submission.is_eml(_build_pdf("hi"), "brief.pdf") is False


class TestRealBrief:
    """The connector against a real PDF, when one is available."""

    BRIEF = Path("/tmp/casebrief/angel-v-murray.pdf")

    @pytest.mark.skipif(
        not BRIEF.exists(), reason="sample PDF not present on this machine"
    )
    def test_real_brief_recovers_its_distinguishing_terms(self):
        text = submission.extract_text(self.BRIEF.read_bytes(), self.BRIEF.name)
        for token in ("Maher", "Murray", "Newport", "consideration", "89D"):
            assert token in text, f"{token!r} did not survive extraction"

    @pytest.mark.skipif(
        not BRIEF.exists(), reason="sample PDF not present on this machine"
    )
    def test_real_brief_has_no_replacement_characters(self):
        text = submission.extract_text(self.BRIEF.read_bytes(), self.BRIEF.name)
        assert text.count("\ufffd") == 0
