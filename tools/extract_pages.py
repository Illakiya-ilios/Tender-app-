"""Extract specific pages from a PDF (1-indexed, inclusive)."""
import sys
from pathlib import Path
import pdfplumber

ROOT = Path(__file__).resolve().parent.parent

path = ROOT / sys.argv[1]
start = int(sys.argv[2])
end = int(sys.argv[3])

with pdfplumber.open(path) as pdf:
    for i in range(start - 1, min(end, len(pdf.pages))):
        print(f"\n--- page {i+1} ---")
        print(pdf.pages[i].extract_text() or "[no text]")
