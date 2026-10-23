"""extract_text_with_pages: per-page spans, stable against normalization.

The feature this prepares for: search hits carry a page number so a
reader can jump to the right page of a 40-page exhibit. That requires
character spans that survive normalization; if a length-changing
substitution (whitespace collapse, U+FFFD replacement) shifted a page's
start, a search hit reported as "page 3" would point at page 2's text.

The function is additive: no existing caller of extract_text is affected
by this module. The tests exercise the function in isolation.
"""
from __future__ import annotations

import pytest

from interface import pdf_text


def _build_three_page_pdf() -> bytes:
    """Three pages with a distinctive heading on each.

    Built at test time rather than checked in, same pattern as
    test_pdf_text.py::test_pages_are_separated_so_words_do_not_weld.
    """
    from fpdf import FPDF

    doc = FPDF()
    doc.set_font("Helvetica", size=12)

    doc.add_page()
    doc.cell(0, 10, "Medical Note", new_x="LMARGIN", new_y="NEXT")
    doc.cell(0, 10, "Patient: A. Tremblay", new_x="LMARGIN", new_y="NEXT")

    doc.add_page()
    doc.cell(0, 10, "Insurer Response", new_x="LMARGIN", new_y="NEXT")
    doc.cell(0, 10, "Re: claim 4471-A", new_x="LMARGIN", new_y="NEXT")

    doc.add_page()
    doc.cell(0, 10, "Employer Notice", new_x="LMARGIN", new_y="NEXT")
    doc.cell(0, 10, "Re: temporary assignment", new_x="LMARGIN", new_y="NEXT")

    return bytes(doc.output())


def test_three_page_pdf_reports_three_pages():
    text, spans = pdf_text.extract_text_with_pages(_build_three_page_pdf())
    assert spans is not None
    assert [p for p, _, _ in spans] == [1, 2, 3]


def test_spans_are_ordered_and_cover_the_text():
    text, spans = pdf_text.extract_text_with_pages(_build_three_page_pdf())
    assert spans is not None
    prev_end = 0
    for page_num, start, end in spans:
        assert start >= prev_end, f"page {page_num} overlaps previous"
        assert end >= start, f"page {page_num} has negative length"
        prev_end = end
    # Last span ends at len(text): nothing outside the reported spans.
    assert spans[-1][2] == len(text)


def test_spans_plus_joiners_reconstruct_the_text():
    """The spans and the inter-page '\\n' must together equal `text`.

    Stronger than "slices carry page content" — this catches any off-by-
    one in the offset arithmetic.
    """
    text, spans = pdf_text.extract_text_with_pages(_build_three_page_pdf())
    assert spans is not None
    reconstructed = "\n".join(text[s:e] for _, s, e in spans)
    assert reconstructed == text


def test_page_slices_carry_the_page_content():
    text, spans = pdf_text.extract_text_with_pages(_build_three_page_pdf())
    assert spans is not None
    p1 = text[spans[0][1]:spans[0][2]]
    p2 = text[spans[1][1]:spans[1][2]]
    p3 = text[spans[2][1]:spans[2][2]]
    assert "Medical Note" in p1
    assert "Insurer Response" in p2
    assert "Employer Notice" in p3
    # No cross-contamination: each heading is on exactly one page.
    assert "Insurer" not in p1
    assert "Medical" not in p2
    assert "Employer" not in p2


def test_single_page_pdf_returns_one_span():
    from fpdf import FPDF

    doc = FPDF()
    doc.set_font("Helvetica", size=12)
    doc.add_page()
    doc.cell(0, 10, "One page only", new_x="LMARGIN", new_y="NEXT")
    data = bytes(doc.output())

    text, spans = pdf_text.extract_text_with_pages(data)
    assert spans is not None
    assert len(spans) == 1
    assert spans[0][0] == 1
    assert "One page only" in text


def test_non_pdf_raises_not_a_pdf():
    with pytest.raises(pdf_text.NotAPdf):
        pdf_text.extract_text_with_pages(b"not a pdf")


def test_no_text_layer_raises_no_text_found():
    """Blank PDF: pdfium returns empty text per page, joined is empty,
    falls through to extract_text which raises NoTextFound."""
    from fpdf import FPDF

    doc = FPDF()
    doc.add_page()
    data = bytes(doc.output())

    with pytest.raises(pdf_text.NoTextFound):
        pdf_text.extract_text_with_pages(data)
