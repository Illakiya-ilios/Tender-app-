"""Write the BOQ price schedule as an .xlsx in the government BOQ layout."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

from ..models import TenderBrief
from .. import config

_thin = Side(style="thin")
_border = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
_header_fill = PatternFill("solid", fgColor="1F3864")
_header_font = Font(bold=True, color="FFFFFF")
_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
_wrap = Alignment(vertical="center", wrap_text=True)


def generate_boq(brief: TenderBrief, filename: str = "boq.xlsx") -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "BoQ1"

    # Title block, mirroring the BOQ_Ver4.0 header rows.
    ws["A1"] = "PRICE SCHEDULE (BOQ)"
    ws["A1"].font = Font(bold=True, size=14)
    ws.merge_cells("A1:G1")
    ws["A1"].alignment = _center

    ws["A2"] = f"Tender Inviting Authority: {brief.tender_inviting_authority}"
    ws["A3"] = f"Name of Work: {brief.name_of_work}"
    ws["A4"] = f"Contract No: {brief.tender_reference_no}"
    for r in (2, 3, 4):
        ws.merge_cells(f"A{r}:G{r}")
        ws[f"A{r}"].alignment = _wrap

    # Column headers.
    headers = ["Sl. No.", "Item Description", "Item Code / Make",
               "Quantity", "Units", "Estimated Rate in Rs.", "Mandatory"]
    header_row = 6
    for col, title in enumerate(headers, start=1):
        c = ws.cell(row=header_row, column=col, value=title)
        c.fill = _header_fill
        c.font = _header_font
        c.alignment = _center
        c.border = _border

    # Line items (derived from the architecture - same source as the PDF).
    row = header_row + 1
    for item in brief.boq_items():
        values = [
            item.sl_no, item.item_description, item.item_code,
            item.quantity, item.units,
            item.estimated_rate if item.estimated_rate is not None else "",
            "Yes" if item.mandatory else "",
        ]
        for col, val in enumerate(values, start=1):
            c = ws.cell(row=row, column=col, value=val)
            c.border = _border
            c.alignment = _wrap if col == 2 else _center
        row += 1

    widths = [8, 50, 18, 10, 10, 18, 10]
    for col, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = w

    out_path = config.OUTPUT_DIR / filename
    wb.save(str(out_path))
    return out_path
