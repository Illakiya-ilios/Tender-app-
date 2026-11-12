"""Render a TenderBrief into a tender PDF using fpdf2 (pure Python, no native deps)."""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

from ..models import TenderBrief
from .. import config
from ..eligibility import (
    ELIGIBILITY_INTRO, ELIGIBILITY_ROWS, ELIGIBILITY_NOTES, ANNEXURES,
)

NAVY = (31, 56, 100)


class TenderPDF(FPDF):
    def header(self) -> None:
        pass

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def _section_title(pdf: TenderPDF, text: str) -> None:
    # Register the section with fpdf2's outline so it appears in the TOC with
    # the correct page number (resolved in fpdf2's second rendering pass).
    pdf.start_section(text, level=0)
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*NAVY)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(2)
    pdf.set_text_color(26, 26, 26)


def _render_toc(pdf: TenderPDF, outline: list) -> None:
    """Render the Table of Contents page with dotted leaders to page numbers.

    Fixed-width columns keep every row within the page: a left label column,
    a dotted-leader column, and a right-aligned page-number column.
    """
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(*NAVY)
    pdf.set_x(pdf.l_margin)
    pdf.cell(pdf.w - pdf.l_margin - pdf.r_margin, 10, "Table of Contents",
             align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_text_color(26, 26, 26)
    pdf.set_font("Helvetica", "", 11)

    usable = pdf.w - pdf.l_margin - pdf.r_margin
    page_w = 14                      # fixed column for the page number
    label_w = usable * 0.72          # label column (72% of usable width)
    dots_w = usable - label_w - page_w
    dot_unit = pdf.get_string_width(".")

    for section in outline:
        label = _truncate_to_width(pdf, _clean(section.name), label_w - 2)
        page = str(section.page_number)
        # Fill the leader column with dots, but never exceed it (keep ~2pt padding).
        n_dots = max(int((dots_w - 2) / dot_unit), 3)
        while n_dots > 3 and pdf.get_string_width("." * n_dots) > dots_w - 2:
            n_dots -= 1
        leader = "." * n_dots

        pdf.cell(label_w, 7, label, align="L")
        pdf.cell(dots_w, 7, leader, align="C")
        pdf.cell(page_w, 7, page, align="R", new_x="LMARGIN", new_y="NEXT")


def _truncate_to_width(pdf: TenderPDF, text: str, max_w: float) -> str:
    """Trim text with an ellipsis so it fits within max_w points."""
    if pdf.get_string_width(text) <= max_w:
        return text
    ell = "..."
    while text and pdf.get_string_width(text + ell) > max_w:
        text = text[:-1]
    return text.rstrip() + ell


def _body(pdf: TenderPDF, text: str, section_title: str = "") -> None:
    """Render LLM text, converting lightweight markdown to PDF formatting.

    - **bold** -> real bold (fpdf2 markdown=True)
    - leading #, ---, and a redundant heading echoing the section title are dropped
    """
    pdf.set_font("Helvetica", "", 10.5)
    for raw_line in (text or "-").split("\n"):
        line = raw_line.rstrip()

        # Drop horizontal rules.
        if line.strip() in ("---", "***", "___"):
            continue
        # Strip markdown heading hashes.
        if line.lstrip().startswith("#"):
            line = line.lstrip("#").strip()
        # Drop a redundant heading that just repeats the section title
        # (e.g. "**SCOPE OF WORK**" under the "Scope of Work" section).
        bare = line.replace("*", "").strip().lower()
        if section_title and bare and bare == section_title.strip().lower():
            continue

        if not line.strip():
            pdf.ln(2)
            continue

        pdf.multi_cell(0, 5.5, _clean(line), markdown=True,
                       new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _data_row(pdf: TenderPDF, key: str, value: str) -> None:
    """Two-column data-sheet row with aligned borders of equal height."""
    kw = 65
    vw = pdf.w - pdf.l_margin - pdf.r_margin - kw
    line_h = 6
    x0, y0 = pdf.l_margin, pdf.get_y()

    # Determine row height from whichever cell wraps to more lines.
    pdf.set_font("Helvetica", "B", 10)
    key_lines = pdf.multi_cell(kw, line_h, _clean(key), align="L",
                               dry_run=True, output="LINES")
    pdf.set_font("Helvetica", "", 10)
    val_lines = pdf.multi_cell(vw, line_h, _clean(value or "-"), align="L",
                               dry_run=True, output="LINES")
    row_h = line_h * max(len(key_lines), len(val_lines), 1)

    # Draw empty bordered boxes of equal height, then write text on top.
    pdf.rect(x0, y0, kw, row_h)
    pdf.rect(x0 + kw, y0, vw, row_h)

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_xy(x0, y0)
    pdf.multi_cell(kw, line_h, _clean(key), align="L", new_x="RIGHT", new_y="TOP")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_xy(x0 + kw, y0)
    pdf.multi_cell(vw, line_h, _clean(value or "-"), align="L")

    pdf.set_xy(x0, y0 + row_h)


def _combine(pairs: list) -> str:
    """Build a multi-line 'Label: value' block for grouped sub-fields.

    Empty sub-values are skipped. Returns '-' if nothing is filled.
    """
    lines = [f"{label}: {value}" for label, value in pairs if value and value.strip()]
    return "\n".join(lines) if lines else "-"


def _fmt_qty(q: float) -> str:
    """Render 1.0 as '1', 2.5 as '2.5'."""
    try:
        return str(int(q)) if float(q).is_integer() else str(q)
    except (TypeError, ValueError):
        return str(q)


def _clean(text: str) -> str:
    """fpdf2 core fonts are latin-1; replace common unicode punctuation."""
    repl = {"\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'",
            "\u201c": '"', "\u201d": '"', "\u20b9": "Rs.", "\u2022": "-"}
    for a, b in repl.items():
        text = text.replace(a, b)
    return text.encode("latin-1", "replace").decode("latin-1")


def generate_pdf(brief: TenderBrief, filename: str = "tender.pdf") -> Path:
    pdf = TenderPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    # Title block
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(*NAVY)
    pdf.multi_cell(0, 8, _clean(brief.tender_inviting_authority or "Tender Inviting Authority"),
                   align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(70, 70, 70)
    if brief.authority_address:
        pdf.multi_cell(0, 5, _clean(brief.authority_address), align="C",
                       new_x="LMARGIN", new_y="NEXT")
    if brief.authority_contact:
        pdf.multi_cell(0, 5, _clean(brief.authority_contact), align="C",
                       new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(26, 26, 26)
    pdf.multi_cell(0, 7, _clean(brief.name_of_work or "Tender Document"), align="C",
                   new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, _clean(f"Tender Ref. No.: {brief.tender_reference_no}"), align="C",
                   new_x="LMARGIN", new_y="NEXT")

    # Reserve a page for the Table of Contents. fpdf2 fills it in a second pass
    # once all section page numbers are known.
    pdf.add_page()
    pdf.insert_toc_placeholder(_render_toc, pages=1)

    # Document body starts on a fresh page.
    pdf.add_page()

    # Data sheet
    _section_title(pdf, "I. Notice Inviting Tender & Tender Data Sheet")
    rows = [
        ("Tender Inviting Authority", brief.tender_inviting_authority),
        ("Name of Work", brief.name_of_work),
        ("Tender Reference No.", brief.tender_reference_no),
        ("Type of Bid", brief.bid_type),
        ("Earnest Money Deposit (EMD)", brief.emd_amount),
        ("Estimated Value", brief.estimated_value),
        ("Contract Period", brief.contract_period),
        ("Pre-Bid Meeting", _combine([
            ("Date & Time", brief.pre_bid_datetime),
            ("Venue", brief.pre_bid_venue),
        ])),
        ("Last Date & Time of Submission", brief.submission_due_datetime),
        ("Date & Time of Bid Opening", brief.bid_opening_datetime),
        ("Bid Validity", f"{brief.bid_validity_days} days"),
        ("Contact Details", _combine([
            ("Name", brief.contact_name),
            ("Phone", brief.contact_phone),
            ("Email", brief.contact_email),
        ])),
        ("e-Tender Portal", brief.portal_url),
        ("Governing Law", brief.governing_law),
    ]
    for k, v in rows:
        _data_row(pdf, k, v)

    _section_title(pdf, "II. Introduction and Preamble")
    _body(pdf, brief.introduction, section_title="introduction and preamble")

    _section_title(pdf, "III. Scope of Work")
    _body(pdf, brief.scope_of_work, section_title="scope of work")

    _section_title(pdf, "IV. Bidder Eligibility Criteria")
    _eligibility_section(pdf)

    # Technical Requirements as a SUMMARY TABLE derived from the architecture
    # (same source as the BOQ, so they can never conflict).
    _section_title(pdf, "V. Technical Requirements (Summary)")
    _tech_summary_table(pdf, brief)

    _section_title(pdf, "VI. Instructions to Bidders")
    _body(pdf, brief.instructions_to_bidders, section_title="instructions to bidders")

    _section_title(pdf, "VII. Payment Terms")
    _body(pdf, brief.payment_terms, section_title="payment terms")

    _section_title(pdf, "VIII. Delivery, Implementation and Commissioning Schedule")
    _body(pdf, brief.delivery_timeline)

    _section_title(pdf, "IX. Service Level Agreement (SLA) and Penalties")
    _body(pdf, brief.sla_terms)

    _section_title(pdf, "X. General Terms and Conditions")
    _body(pdf, brief.terms_and_conditions, section_title="general terms and conditions")

    _section_title(pdf, "XI. Price Schedule (BOQ) - Summary")
    _boq_summary_table(pdf, brief)

    _annexures_section(pdf)

    out_path = config.OUTPUT_DIR / filename
    pdf.output(str(out_path))
    return out_path


def _annexures_section(pdf: TenderPDF) -> None:
    """Render the standard Annexures (bidder submission formats), each on a new
    page, registered in the Table of Contents."""
    pdf.add_page()
    _section_title(pdf, "XII. Annexures")
    pdf.set_font("Helvetica", "", 10.5)
    pdf.multi_cell(0, 5.5, _clean(
        "The following standard formats shall be used by bidders where applicable. "
        "Undertakings and declarations shall be submitted on the bidder's "
        "letterhead and signed by the Authorised Signatory."),
        new_x="LMARGIN", new_y="NEXT")

    for i, (title, body) in enumerate(ANNEXURES):
        pdf.add_page()
        # Register each annexure as a sub-section so it appears in the TOC.
        pdf.start_section(title, level=1)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*NAVY)
        pdf.multi_cell(0, 7, _clean(title), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(*NAVY)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(2)
        pdf.set_text_color(26, 26, 26)
        _body(pdf, body)


def _eligibility_section(pdf: TenderPDF) -> None:
    """Render the fixed Bidder Eligibility Criteria table + notes."""
    _body(pdf, ELIGIBILITY_INTRO)

    # Header row.
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(*NAVY)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(12, 7, "S.No", border=1, align="C", fill=True)
    pdf.cell(96, 7, "Pre-Qualification Criteria", border=1, align="C", fill=True)
    pdf.cell(0, 7, "Documentary Proof to be Submitted", border=1, align="C",
             fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(26, 26, 26)
    pdf.set_font("Helvetica", "", 8.5)

    for i, (criterion, proof) in enumerate(ELIGIBILITY_ROWS, start=1):
        _grid_row(pdf, [
            (12, str(i), "C"),
            (96, criterion, "L"),
            (0, proof, "L"),
        ], line_h=4.4)

    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 10)
    pdf.multi_cell(0, 5.5, "Note:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9.5)
    for idx, note in enumerate(ELIGIBILITY_NOTES):
        label = f"{chr(ord('a') + idx)}) "
        pdf.multi_cell(0, 5, _clean(label + note), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _tech_summary_table(pdf: TenderPDF, brief: TenderBrief) -> None:
    if not brief.architecture:
        _body(pdf, "Technical requirements to be specified.")
        return
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(*NAVY)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(10, 7, "S.No", border=1, align="C", fill=True)
    pdf.cell(38, 7, "Category", border=1, align="C", fill=True)
    pdf.cell(97, 7, "Specification", border=1, align="C", fill=True)
    pdf.cell(18, 7, "Qty", border=1, align="C", fill=True)
    pdf.cell(0, 7, "Units", border=1, align="C", fill=True,
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(26, 26, 26)
    pdf.set_font("Helvetica", "", 9)
    for i, a in enumerate(brief.architecture, start=1):
        _grid_row(pdf, [
            (10, str(i), "C"), (38, a.category, "L"),
            (97, a.description, "L"), (18, _fmt_qty(a.quantity), "C"),
            (0, a.units, "C"),
        ])
    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(0, 5, "The detailed, priceable breakup is provided in the separate "
                   "BOQ (Price Schedule), which is derived from this same component list.",
                   new_x="LMARGIN", new_y="NEXT")


def _boq_summary_table(pdf: TenderPDF, brief: TenderBrief) -> None:
    boq = brief.boq_items()
    if not boq:
        _body(pdf, "Price schedule to be specified.")
        return
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(*NAVY)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(12, 7, "Sl.", border=1, align="C", fill=True)
    pdf.cell(123, 7, "Item Description", border=1, align="C", fill=True)
    pdf.cell(20, 7, "Qty", border=1, align="C", fill=True)
    pdf.cell(0, 7, "Units", border=1, align="C", fill=True,
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(26, 26, 26)
    pdf.set_font("Helvetica", "", 9)
    for it in boq:
        _grid_row(pdf, [
            (12, str(it.sl_no), "C"), (123, it.item_description, "L"),
            (20, _fmt_qty(it.quantity), "C"), (0, it.units, "C"),
        ])
    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(0, 5, "Bidders shall quote rates in the separate BOQ Excel price "
                   "schedule. This summary is for reference only.",
                   new_x="LMARGIN", new_y="NEXT")


def _grid_row(pdf: TenderPDF, cells: list, line_h: float = 5) -> None:
    """Render one table row where cells may wrap, keeping borders aligned.

    cells: list of (width, text, align). width 0 means 'to right margin'.
    """
    # Resolve widths and compute the tallest wrapped cell.
    resolved = []
    max_lines = 1
    for w, text, align in cells:
        width = w if w else (pdf.w - pdf.r_margin - pdf.l_margin
                             - sum(c[0] for c in cells[:-1]))
        lines = pdf.multi_cell(width, line_h, _clean(str(text)), align=align,
                               dry_run=True, output="LINES")
        max_lines = max(max_lines, len(lines))
        resolved.append((width, str(text), align))
    row_h = line_h * max_lines

    x0, y0 = pdf.l_margin, pdf.get_y()
    # Page break if the row won't fit.
    if y0 + row_h > pdf.h - pdf.b_margin:
        pdf.add_page()
        x0, y0 = pdf.l_margin, pdf.get_y()

    x = x0
    for width, text, align in resolved:
        pdf.rect(x, y0, width, row_h)
        pdf.set_xy(x, y0)
        pdf.multi_cell(width, line_h, _clean(text), align=align,
                       new_x="RIGHT", new_y="TOP")
        x += width
    pdf.set_xy(x0, y0 + row_h)
