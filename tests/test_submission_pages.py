"""submission.extract_text_with_pages: dispatch parity with extract_text.

The wrapper exists so a caller can ask for pages without branching on
file type: PDFs go through pdf_text's page-aware extractor, everything
else goes through extract_text and returns ``(text, None)``. These tests
pin the parity — a non-PDF input must produce exactly the text
extract_text would have produced, so a caller that switches from one to
the other does not see different content.

The PDF parity is weaker by design: pdfium's per-page normalization is
documented in pdf_text.extract_text_with_pages as "usually but not
always byte-identical" to extract_text, so this file does not assert
equality for PDFs — only that the pdfium path is actually taken (spans
not None).
"""
from __future__ import annotations

import pytest

from interface import submission


def test_non_pdf_text_returns_same_string_as_extract_text():
    data = b"Plain text file.\nSecond line.\n"
    text, spans = submission.extract_text_with_pages(data, "note.txt")
    assert text == submission.extract_text(data, "note.txt")
    assert spans is None


def test_non_pdf_no_filename_still_returns_text_and_none():
    data = b"Headerless bytes.\n"
    text, spans = submission.extract_text_with_pages(data)
    assert text == submission.extract_text(data)
    assert spans is None


def test_empty_data_raises_the_same_refusal():
    with pytest.raises(submission.UnsupportedSubmission):
        submission.extract_text_with_pages(b"", "empty.txt")


def test_unimplemented_suffix_raises_the_same_refusal():
    # .docx is declared-but-unimplemented; extract_text refuses rather than
    # decoding binary as text. The wrapper must refuse identically.
    with pytest.raises(submission.UnsupportedSubmission):
        submission.extract_text_with_pages(b"PK\x03\x04fake-docx", "letter.docx")


def test_pdf_dispatches_to_page_aware_extractor():
    """A real PDF must take the pdfium path and come back with spans.

    Uses the same test-time PDF construction as
    tests/test_pdf_text_pages.py — build a 2-page PDF and confirm spans
    are populated. Equality with extract_text is not asserted here: the
    two paths normalize differently and the difference is documented.
    """
    from fpdf import FPDF

    doc = FPDF()
    doc.set_font("Helvetica", size=12)
    doc.add_page()
    doc.cell(0, 10, "Page one heading", new_x="LMARGIN", new_y="NEXT")
    doc.add_page()
    doc.cell(0, 10, "Page two heading", new_x="LMARGIN", new_y="NEXT")
    data = bytes(doc.output())

    text, spans = submission.extract_text_with_pages(data, "doc.pdf")
    assert spans is not None
    assert [p for p, _, _ in spans] == [1, 2]
    assert "Page one heading" in text
    assert "Page two heading" in text


def test_pdf_detected_by_content_not_suffix():
    """A PDF mislabelled .txt must still take the PDF branch.

    extract_text dispatches on content first, then suffix, because a
    mislabelled file is a real occurrence and the bytes are the
    authority. The wrapper must preserve that order.
    """
    from fpdf import FPDF

    doc = FPDF()
    doc.set_font("Helvetica", size=12)
    doc.add_page()
    doc.cell(0, 10, "Content is a PDF", new_x="LMARGIN", new_y="NEXT")
    data = bytes(doc.output())

    text, spans = submission.extract_text_with_pages(data, "mislabelled.txt")
    assert spans is not None
    assert "Content is a PDF" in text


def test_non_pdf_raises_not_a_pdf_never_through_wrapper():
    """Sanity: a plain-text file is not routed through pdf_text at all.

    If the wrapper ever accidentally called pdf_text for non-PDF input,
    this would raise NotAPdf instead of returning (text, None).
    """
    text, spans = submission.extract_text_with_pages(b"not a pdf at all", "plain.txt")
    assert spans is None
    assert "not a pdf" in text
