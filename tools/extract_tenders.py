"""Extract text from tender PDFs and BOQ Excel files for analysis."""
import sys
from pathlib import Path

import pdfplumber
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def dump_pdf(path: Path, max_chars: int = 6000) -> None:
    print(f"\n{'='*80}\nPDF: {path.relative_to(ROOT)}\n{'='*80}")
    try:
        with pdfplumber.open(path) as pdf:
            print(f"[pages: {len(pdf.pages)}]")
            collected = []
            for i, page in enumerate(pdf.pages):
                txt = page.extract_text() or ""
                collected.append(f"--- page {i+1} ---\n{txt}")
                if sum(len(c) for c in collected) > max_chars:
                    collected.append("...[truncated]...")
                    break
            print("\n".join(collected))
    except Exception as e:
        print(f"[error: {e}]")


def dump_excel(path: Path) -> None:
    print(f"\n{'='*80}\nEXCEL: {path.relative_to(ROOT)}\n{'='*80}")
    for engine in ("xlrd", "openpyxl", None):
        try:
            sheets = pd.read_excel(path, sheet_name=None, header=None, engine=engine)
            for name, df in sheets.items():
                print(f"--- sheet: {name} ({df.shape[0]}x{df.shape[1]}) ---")
                print(df.to_string(max_rows=40, max_cols=12))
            return
        except Exception as e:
            last = e
    print(f"[error reading excel: {last}]")


if __name__ == "__main__":
    targets = sys.argv[1:]
    for t in targets:
        p = ROOT / t
        if p.suffix.lower() == ".pdf":
            dump_pdf(p)
        elif p.suffix.lower() in (".xls", ".xlsx"):
            dump_excel(p)
