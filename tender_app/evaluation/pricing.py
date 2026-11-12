"""Stage 3 (7): bid price extraction (LLM-driven + defensive parsing).

Extracts a bid's total quoted price from its price-schedule sub-document(s) via
Gemini, grounded in the classified sub-documents (Req 7.1). The price schedule
is preferred (``classified_as == "price_schedule"``); if none is classified as
such, all sub-documents are searched. The extracted amount carries an
:class:`EvidenceCitation` (filename + page) (Req 7.2).

When no price can be extracted the result is ``available = False`` with a note
that the bid cannot be ranked on price until the officer supplies it (Req 7.3).
On any LLM/JSON error the result degrades to unavailable with an explanatory
note. This module never throws.
"""
from __future__ import annotations

import re

from tender_app import llm
from tender_app.evaluation._jsonutil import parse_json
from tender_app.evaluation.models import BidPrice, EvidenceCitation, SubDocument

# Cap per sub-document text in the prompt.
_MAX_SUBDOC_CHARS = 1500

# The sub-document type key for the priced bill of quantities / price schedule.
PRICE_SCHEDULE_KEY = "price_schedule"

_NO_PRICE_NOTE = (
    "No total price could be extracted from the bid. This bid cannot be ranked "
    "on price until the officer supplies it."
)


def _snippet(sub: SubDocument) -> str:
    text = (sub.text or "").strip()
    if len(text) > _MAX_SUBDOC_CHARS:
        text = text[:_MAX_SUBDOC_CHARS] + " …[truncated]"
    if not text:
        text = "(no readable text)"
    return text


def _price_subdocs(sub_docs: list[SubDocument]) -> list[SubDocument]:
    """Prefer price-schedule sub-documents; fall back to all of them (Req 7.1)."""
    schedule = [s for s in sub_docs if s.classified_as == PRICE_SCHEDULE_KEY]
    return schedule if schedule else sub_docs


def build_price_prompt(sub_docs: list[SubDocument]) -> str:
    """Build the price-extraction prompt grounded in the price sub-documents."""
    doc_lines = []
    for sub in sub_docs:
        doc_lines.append(
            f'--- filename: "{sub.filename}" | pages {sub.page_start}-{sub.page_end}'
            f' | type: {sub.classified_as} ---\n{_snippet(sub)}'
        )
    doc_block = "\n\n".join(doc_lines) if doc_lines else "(no sub-documents available)"

    return (
        "You are extracting the TOTAL quoted price from a tender bid's price "
        "schedule, grounded strictly in the sub-documents provided. Find the "
        "single grand-total / final quoted amount the bidder is charging.\n\n"
        "BID SUB-DOCUMENTS:\n"
        f"{doc_block}\n\n"
        "Return ONLY a JSON object (no prose, no code fences) with fields:\n"
        '  "available": boolean (true only if a total price is clearly present)\n'
        '  "amount": number (the total price as a plain number, no currency '
        "symbols or thousands separators; null if not available)\n"
        '  "currency": string (e.g. "INR"; default "INR")\n'
        '  "citation": object {"filename": string, "page": integer, '
        '"quote": string} pointing at where the total appears (null if not '
        "available). filename must match a sub-document above.\n"
    )


def _coerce_amount(value: object) -> float | None:
    """Parse a numeric amount from the LLM payload (number or numeric string)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Strip currency symbols, commas, whitespace; keep digits/decimal/sign.
        cleaned = re.sub(r"[^0-9.\-]", "", value.strip())
        if not cleaned or cleaned in ("-", ".", "-."):
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _parse_citation(
    raw: object, sub_docs: list[SubDocument]
) -> EvidenceCitation | None:
    if not isinstance(raw, dict):
        return None
    known = {s.filename for s in sub_docs}
    filename = raw.get("filename")
    if not isinstance(filename, str) or filename not in known:
        return None
    try:
        page = int(raw.get("page"))
    except (TypeError, ValueError):
        return None
    if page <= 0:
        return None
    quote = raw.get("quote")
    return EvidenceCitation(
        filename=filename,
        page=page,
        quote=quote.strip() if isinstance(quote, str) else "",
    )


def extract_price(sub_docs: list[SubDocument], bid_id: str = "") -> BidPrice:
    """Extract the total quoted price for a bid.

    On success returns ``available = True`` with a parsed ``amount`` and an
    :class:`EvidenceCitation` (Req 7.1, 7.2). When no price is extractable (or
    on any error) returns ``available = False`` with a note that the bid cannot
    be ranked on price until the officer supplies it (Req 7.3). Never raises.
    """
    relevant = _price_subdocs(sub_docs)
    try:
        raw = llm.generate(build_price_prompt(relevant), temperature=0.0)
        payload = parse_json(raw)
        if not isinstance(payload, dict):
            raise ValueError("price payload was not a JSON object")
    except Exception as exc:  # graceful degradation — unavailable with note
        return BidPrice(
            bid_id=bid_id,
            available=False,
            amount=None,
            note=f"{_NO_PRICE_NOTE} (extraction error: {exc})",
        )

    amount = _coerce_amount(payload.get("amount"))
    currency = payload.get("currency")
    currency = currency.strip() if isinstance(currency, str) and currency.strip() else "INR"

    # A price is only usable if the model flagged it available AND a numeric
    # amount was actually parsed.
    if payload.get("available") and amount is not None:
        citation = _parse_citation(payload.get("citation"), relevant)
        return BidPrice(
            bid_id=bid_id,
            available=True,
            amount=amount,
            currency=currency,
            citation=citation,
        )

    return BidPrice(
        bid_id=bid_id,
        available=False,
        amount=None,
        currency=currency,
        note=_NO_PRICE_NOTE,
    )
