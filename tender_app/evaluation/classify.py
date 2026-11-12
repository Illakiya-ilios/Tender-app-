"""Stage 3 (3): sub-document segmentation and semantic classification.

Real bids arrive as PDFs that may bundle many logically distinct documents (an
87-page PQ bundle, a 29-page CV bundle, etc.). This module segments each
:class:`ExtractedDocument` (one per source PDF) into :class:`SubDocument`
page ranges and assigns each to a :class:`RequiredDocumentType` by *content*,
never by folder or filename meaning (Req 3.1, 3.2, 3.3-source).

Segmentation + classification are done in a single Gemini text call built from
the already-extracted per-page text (cheaper and sufficient vs. re-OCR'ing
images). The model returns JSON describing the sub-documents. Parsing is
robust: code fences are stripped and, on any LLM/JSON error, the whole document
falls back to a single ``Unclassified`` sub-document spanning all its pages so
classification never throws (Req 3.5 retention).

Per sub-document the source filename and page range are recorded (Req 3.4), the
concatenated page text is carried, and ``readable`` reflects whether the
underlying pages were readable. Unmatched sub-documents are labelled
``Unclassified`` and retained (Req 3.5); multiple sub-documents of the same type
are all kept and associated to that type — no de-duplication by type (Req 3.6).
"""
from __future__ import annotations

import json

from tender_app import llm
from tender_app.evaluation.models import (
    ExtractedDocument,
    ExtractedPage,
    ExtractionSource,
    RequiredDocumentType,
    SubDocument,
)

# Cap per-page text in the prompt so long bundles stay within a sane token
# budget. The model only needs enough signal to segment and classify.
_MAX_PAGE_CHARS = 1500

UNCLASSIFIED = "Unclassified"


def _page_readable(page: ExtractedPage) -> bool:
    return page.source in (ExtractionSource.TEXT, ExtractionSource.OCR)


def build_classify_prompt(
    doc: ExtractedDocument, types: list[RequiredDocumentType]
) -> str:
    """Build the segmentation + classification prompt for one document.

    Lists the available required-document type keys/labels and the per-page
    (truncated) text, and asks for a strict JSON array describing the
    sub-documents.
    """
    type_lines = []
    for t in types:
        desc = f" — {t.description}" if t.description else ""
        type_lines.append(f'- "{t.key}": {t.label}{desc}')
    type_block = "\n".join(type_lines) if type_lines else "(no required types provided)"

    page_lines = []
    for page in doc.pages:
        snippet = (page.text or "").strip()
        if len(snippet) > _MAX_PAGE_CHARS:
            snippet = snippet[:_MAX_PAGE_CHARS] + " …[truncated]"
        if not snippet:
            snippet = "(no readable text)"
        page_lines.append(f"[Page {page.page}]\n{snippet}")
    page_block = "\n\n".join(page_lines) if page_lines else "(document has no pages)"

    return (
        "You are classifying the contents of a single PDF file submitted as part "
        "of a tender bid. The file may bundle several logically distinct "
        "sub-documents. Segment the file into its constituent sub-documents by "
        "CONTENT only (ignore any filename), and classify each sub-document into "
        "one of the required document types below.\n\n"
        "Required document types (use the quoted key):\n"
        f"{type_block}\n\n"
        'If a sub-document matches none of the types, classify it as '
        f'"{UNCLASSIFIED}".\n\n'
        "Return ONLY a JSON array (no prose, no code fences). Each element is an "
        "object with these fields:\n"
        '  "page_start": integer (1-based, inclusive)\n'
        '  "page_end": integer (1-based, inclusive, >= page_start)\n'
        f'  "classified_as": one of the type keys above or "{UNCLASSIFIED}"\n'
        '  "rationale": short string (optional)\n\n'
        "The page ranges must cover the document without overlapping. Page "
        f"numbers range from 1 to {len(doc.pages)}.\n\n"
        f"FILE: {doc.filename}\n"
        f"{page_block}\n"
    )


def _strip_code_fences(text: str) -> str:
    """Remove a surrounding ``` or ```json code fence if present."""
    s = (text or "").strip()
    if s.startswith("```"):
        # Drop the opening fence line (``` or ```json) and the trailing fence.
        newline = s.find("\n")
        if newline != -1:
            s = s[newline + 1 :]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[: -3]
    return s.strip()


def _whole_doc_unclassified(doc: ExtractedDocument) -> SubDocument:
    """Fallback sub-document: the entire document as one Unclassified unit."""
    page_count = len(doc.pages)
    start = doc.pages[0].page if page_count else 1
    end = doc.pages[-1].page if page_count else 1
    text = _concat_text(doc, start, end)
    readable = any(_page_readable(p) for p in doc.pages) if page_count else False
    return SubDocument(
        filename=doc.filename,
        page_start=start,
        page_end=end,
        classified_as=UNCLASSIFIED,
        readable=readable,
        text=text,
    )


def _concat_text(doc: ExtractedDocument, start: int, end: int) -> str:
    """Concatenate the text of pages in [start, end] (1-based, inclusive)."""
    parts = [p.text for p in doc.pages if start <= p.page <= end and p.text]
    return "\n".join(parts).strip()


def _range_readable(doc: ExtractedDocument, start: int, end: int) -> bool:
    """True if any page in [start, end] was readable."""
    return any(
        _page_readable(p) for p in doc.pages if start <= p.page <= end
    )


def _valid_keys(types: list[RequiredDocumentType]) -> set[str]:
    return {t.key for t in types}


def _segment_document(
    doc: ExtractedDocument, types: list[RequiredDocumentType]
) -> list[SubDocument]:
    """Segment and classify one document, with whole-doc fallback on any error."""
    if not doc.pages:
        return [_whole_doc_unclassified(doc)]

    prompt = build_classify_prompt(doc, types)
    try:
        raw = llm.generate(prompt, temperature=0.1)
        payload = json.loads(_strip_code_fences(raw))
    except Exception:
        return [_whole_doc_unclassified(doc)]

    if not isinstance(payload, list) or not payload:
        return [_whole_doc_unclassified(doc)]

    first_page = doc.pages[0].page
    last_page = doc.pages[-1].page
    valid = _valid_keys(types)

    sub_docs: list[SubDocument] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            start = int(item.get("page_start"))
            end = int(item.get("page_end"))
        except (TypeError, ValueError):
            continue

        # Clamp to the document's real page bounds and normalise order.
        start = max(first_page, min(start, last_page))
        end = max(first_page, min(end, last_page))
        if end < start:
            start, end = end, start

        classified = item.get("classified_as") or UNCLASSIFIED
        if not isinstance(classified, str) or (
            classified != UNCLASSIFIED and classified not in valid
        ):
            classified = UNCLASSIFIED

        sub_docs.append(
            SubDocument(
                filename=doc.filename,
                page_start=start,
                page_end=end,
                classified_as=classified,
                readable=_range_readable(doc, start, end),
                text=_concat_text(doc, start, end),
            )
        )

    # If nothing parsed into a usable sub-document, fall back to whole-doc.
    if not sub_docs:
        return [_whole_doc_unclassified(doc)]
    return sub_docs


def classify_bid(
    docs: list[ExtractedDocument], types: list[RequiredDocumentType]
) -> list[SubDocument]:
    """Segment and classify every document of a bid into sub-documents.

    Each :class:`ExtractedDocument` (one per source PDF) is segmented into one
    or more :class:`SubDocument` page ranges and each range is classified into a
    :class:`RequiredDocumentType` key by content, or ``Unclassified`` (Req 3.1,
    3.2). Source filename and page range are recorded per sub-document (Req
    3.4). Unmatched sub-documents are retained as ``Unclassified`` (Req 3.5) and
    all sub-documents of the same type are kept — never de-duplicated by type
    (Req 3.6). Classification never raises: on any LLM/JSON failure the affected
    document degrades to a single whole-document ``Unclassified`` sub-document.
    """
    result: list[SubDocument] = []
    for doc in docs:
        result.extend(_segment_document(doc, types))
    return result
