"""Probe incoming bid PDFs: page count + whether a text layer exists."""
import sys
from pathlib import Path
import pdfplumber

for arg in sys.argv[1:]:
    p = Path(arg)
    try:
        with pdfplumber.open(p) as pdf:
            n = len(pdf.pages)
            sample = ""
            for pg in pdf.pages[:3]:
                sample += (pg.extract_text() or "")
            has_text = len(sample.strip()) > 20
            preview = " ".join(sample.split())[:160]
            print(f"{'TEXT' if has_text else 'SCAN'} | {n:>3}p | {p.name}")
            if has_text:
                print(f"        preview: {preview}")
    except Exception as e:
        print(f"ERR  | {p.name} -> {e}")
