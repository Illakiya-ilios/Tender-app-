"""Stage 3 (2): PDF text extraction with a Gemini-vision OCR fallback.

Per page: try the ``pdfplumber`` text layer (Req 2.1). If a page yields no text
or garbled/non-readable text (see :func:`looks_unreadable`), render it to a PNG
with ``pypdfium2`` and OCR it via :func:`tender_app.llm.generate_multimodal`
(Req 2.2, 2.3). Record a per-document extraction source rollup
(``TEXT`` | ``OCR`` | ``BOTH`` | ``NONE``; Req 2.4). When neither method yields
readable text for the whole document, mark it unreadable while retaining the
filename (Req 2.5).
"""
from __future__ import annotations

from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium

from tender_app import llm
from tender_app.evaluation.models import (
    ExtractedDocument,
    ExtractedPage,
    ExtractionSource,
)

# Scale factor for rendering a PDF page to a raster image for OCR. ~2.0 gives a
# good balance of legibility and size for the vision model.
_OCR_RENDER_SCALE = 2.0

_OCR_PROMPT = (
    "You are an OCR engine. Transcribe all readable text from this scanned "
    "document page exactly as it appears, preserving line breaks. Return only "
    "the transcribed text with no commentary. If the page contains no legible "
    "text, return an empty response."
)


def looks_unreadable(text: str) -> bool:
    """Heuristic deciding whether a page's extracted text needs OCR.

    Returns ``True`` when the text is empty/whitespace-only, has a high ratio of
    non-printable or Unicode replacement (``\\ufffd``) glyphs, or has a very low
    ratio of alphabetic characters relative to its length.
    """
    if text is None:
        return True
    stripped = text.strip()
    if not stripped:
        return True

    total = len(stripped)
    bad = 0
    alpha = 0
    for ch in stripped:
        if ch == "\ufffd" or (not ch.isprintable() and not ch.isspace()):
            bad += 1
        if ch.isalpha():
            alpha += 1

    # High proportion of garbage glyphs -> unreadable.
    if bad / total > 0.1:
        return True

    # Very few letters relative to length -> likely not real extracted prose.
    # Only apply to text long enough to judge, so short labels/numbers pass.
    if total >= 8 and alpha / total < 0.2:
        return True

    return False


def _render_page_png(pdf: "pdfium.PdfDocument", index: int) -> bytes:
    """Render a single (0-based) page of an open pdfium document to PNG bytes."""
    page = pdf[index]
    try:
        pil_image = page.render(scale=_OCR_RENDER_SCALE).to_pil()
        import io

        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        page.close()


def extract_document(pdf_path) -> ExtractedDocument:
    """Extract text from ``pdf_path`` page by page, OCR'ing unreadable pages.

    Returns an :class:`ExtractedDocument` with one :class:`ExtractedPage` per
    page, a per-document ``source`` rollup, and ``readable`` set to ``False``
    when nothing readable was obtained for the whole document.
    """
    path = Path(pdf_path)
    filename = path.name
    pages: list[ExtractedPage] = []

    # Open once with pypdfium2 for OCR rendering; keep alive for page loop.
    try:
        pdfium_doc = pdfium.PdfDocument(str(path))
    except Exception:
        pdfium_doc = None

    try:
        with pdfplumber.open(str(path)) as pdf:
            for i, pl_page in enumerate(pdf.pages):
                page_no = i + 1
                try:
                    raw_text = pl_page.extract_text() or ""
                except Exception:
                    raw_text = ""

                if not looks_unreadable(raw_text):
                    pages.append(
                        ExtractedPage(
                            page=page_no,
                            text=raw_text.strip(),
                            source=ExtractionSource.TEXT,
                        )
                    )
                    continue

                # Text layer missing/garbled -> OCR fallback via vision model.
                ocr_text = ""
                if pdfium_doc is not None:
                    try:
                        png = _render_page_png(pdfium_doc, i)
                        ocr_text = llm.generate_multimodal(_OCR_PROMPT, [png])
                    except Exception:
                        ocr_text = ""

                if not looks_unreadable(ocr_text):
                    pages.append(
                        ExtractedPage(
                            page=page_no,
                            text=ocr_text.strip(),
                            source=ExtractionSource.OCR,
                        )
                    )
                else:
                    # Neither method produced readable text for this page.
                    pages.append(
                        ExtractedPage(
                            page=page_no,
                            text="",
                            source=ExtractionSource.NONE,
                        )
                    )
    finally:
        if pdfium_doc is not None:
            try:
                pdfium_doc.close()
            except Exception:
                pass

    source = _rollup_source(pages)
    readable = any(p.source in (ExtractionSource.TEXT, ExtractionSource.OCR) for p in pages)

    return ExtractedDocument(
        filename=filename,
        pages=pages,
        source=source,
        readable=readable,
    )


def _rollup_source(pages: list[ExtractedPage]) -> ExtractionSource:
    """Roll per-page sources into a document-level source (Req 2.4).

    TEXT if all readable pages came from pdfplumber, OCR if all from OCR, BOTH if
    mixed, NONE if nothing readable.
    """
    readable_sources = {
        p.source for p in pages if p.source in (ExtractionSource.TEXT, ExtractionSource.OCR)
    }
    if not readable_sources:
        return ExtractionSource.NONE
    if readable_sources == {ExtractionSource.TEXT}:
        return ExtractionSource.TEXT
    if readable_sources == {ExtractionSource.OCR}:
        return ExtractionSource.OCR
    return ExtractionSource.BOTH
