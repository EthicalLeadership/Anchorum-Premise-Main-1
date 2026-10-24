"""PDF report for a case export.

Pure function: takes primitives, returns bytes. No DB, no FastAPI, no
request. That makes it testable in isolation and keeps the route free of
layout code.

The output is a human-readable companion to the ZIP, not a replacement
for it. The ZIP carries the machine-checkable manifest and hashes; this
PDF carries the same information in a form a lawyer can hand to a client.
"""
from __future__ import annotations


def _pdf_safe(text: str) -> str:
    """fpdf2's built-in fonts are Latin-1 only.

    Non-representable characters become "?" rather than breaking the whole
    document. A filename with an emoji loses the emoji in the PDF; the
    original filename is still in the ZIP manifest unchanged.
    """
    return text.encode("latin-1", errors="replace").decode("latin-1")


def build_pdf(
    *,
    case_key: str,
    title: str,
    exported_at: str,
    approved_by: str,
    stamp_version: str,
    documents: list[dict],
    gates: list[dict],
    disclaimer: str,
) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", size=16)
    pdf.cell(0, 10, _pdf_safe(f"Case {case_key}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 8, _pdf_safe(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 6, _pdf_safe(f"Exported: {exported_at}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(
        0, 6,
        _pdf_safe(f"Barreau: approved by {approved_by} (v{stamp_version})"),
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(6)

    pdf.set_font("Helvetica", size=14)
    pdf.cell(0, 8, "Evidence", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    if not documents:
        pdf.cell(0, 5, "(none)", new_x="LMARGIN", new_y="NEXT")
    for doc in documents:
        pdf.multi_cell(
            0, 5,
            _pdf_safe(
                f"- {doc.get('document_key', '?')}  "
                f"{doc.get('filename', '?')}  "
                f"({doc.get('byte_size', 0)} bytes, "
                f"type: {doc.get('document_type', 'unknown')})"
            ),
            new_x="LMARGIN", new_y="NEXT",
        )
    pdf.ln(6)

    pdf.set_font("Helvetica", size=14)
    pdf.cell(0, 8, "Pre-flight gates", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    for gate in gates:
        advisory = " (advisory)" if not gate.get("blocking", True) else ""
        detail = f" - {gate['detail']}" if gate.get("detail") else ""
        pdf.multi_cell(
            0, 5,
            _pdf_safe(f"- {gate.get('id', '?')}: {gate.get('result', '?')}{advisory}{detail}"),
            new_x="LMARGIN", new_y="NEXT",
        )
    pdf.ln(6)

    pdf.set_font("Helvetica", size=8)
    pdf.multi_cell(0, 4, _pdf_safe(disclaimer), new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())
