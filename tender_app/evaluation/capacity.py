"""Stage 3 (6): capacity assessment (LLM-driven + deterministic roll-up).

Assesses a bidder's organizational capacity to deliver across four items
(Req 6.1):

- ``turnover`` — annual turnover against the tender's turnover criterion. The
  evidence source MUST be the CA/Statutory Auditor turnover certificate
  sub-document (``classified_as == "ca_turnover"``) with an attached
  :class:`EvidenceCitation` (Req 6.2).
- ``experience`` — relevant prior experience.
- ``delivered_projects`` — comparable projects actually delivered.
- ``certifications`` — required quality/security certifications.

Each item is assessed by a focused Gemini call grounded in the relevant
sub-documents, parsed leniently, and turned into a :class:`CapacityItemResult`.
``capacity_qualified`` is ``True`` only when all four items are met (Req 6.3);
every unmet item records a non-empty reason (Req 6.4). On any LLM/JSON error an
item degrades to unmet with the error as its reason. This module never throws.
"""
from __future__ import annotations

from tender_app import llm
from tender_app.evaluation._jsonutil import parse_json
from tender_app.evaluation.models import (
    CapacityItemResult,
    CapacityResult,
    EvidenceCitation,
    SubDocument,
)
from tender_app.models import TenderBrief

# Cap per sub-document text in the prompt.
_MAX_SUBDOC_CHARS = 1200

# The sub-document type key that evidences turnover (Req 6.2).
CA_TURNOVER_KEY = "ca_turnover"

# The four capacity items, with the tender fields that frame each criterion.
_CAPACITY_ITEMS = ("turnover", "experience", "delivered_projects", "certifications")

_ITEM_FOCUS = {
    "turnover": (
        "the bidder's annual turnover / financial strength meets the tender's "
        "turnover and estimated-value expectations"
    ),
    "experience": (
        "the bidder has relevant prior experience of similar scope and domain"
    ),
    "delivered_projects": (
        "the bidder has delivered comparable projects (work orders / completion "
        "certificates / client references)"
    ),
    "certifications": (
        "the bidder holds the required quality and security certifications "
        "(e.g. ISO 9001, ISO 27001, ISO 20000) relevant to the tender"
    ),
}


def _snippet(sub: SubDocument) -> str:
    text = (sub.text or "").strip()
    if len(text) > _MAX_SUBDOC_CHARS:
        text = text[:_MAX_SUBDOC_CHARS] + " …[truncated]"
    if not text:
        text = "(no readable text)"
    return text


def _tender_context(tender: TenderBrief) -> str:
    parts = []
    if tender.estimated_value:
        parts.append(f"Estimated value: {tender.estimated_value}")
    if tender.contract_period:
        parts.append(f"Contract period: {tender.contract_period}")
    if tender.delivery_timeline:
        parts.append(f"Delivery timeline: {tender.delivery_timeline}")
    if tender.sla_terms:
        parts.append(f"SLA terms: {tender.sla_terms}")
    return "\n".join(parts) if parts else "(no additional tender context)"


def build_capacity_prompt(
    name: str, focus: str, tender: TenderBrief, sub_docs: list[SubDocument]
) -> str:
    """Build the prompt assessing one capacity item against sub-documents."""
    doc_lines = []
    for sub in sub_docs:
        doc_lines.append(
            f'--- filename: "{sub.filename}" | pages {sub.page_start}-{sub.page_end}'
            f' | type: {sub.classified_as} ---\n{_snippet(sub)}'
        )
    doc_block = "\n\n".join(doc_lines) if doc_lines else "(no sub-documents available)"

    return (
        "You are assessing ONE aspect of a tender bidder's capacity to deliver "
        "the project, grounded strictly in the bid sub-documents provided. "
        "Judge only from the supplied text.\n\n"
        f"CAPACITY ASPECT: Determine whether {focus}.\n\n"
        "TENDER CONTEXT:\n"
        f"{_tender_context(tender)}\n\n"
        "BID SUB-DOCUMENTS:\n"
        f"{doc_block}\n\n"
        "Return ONLY a JSON object (no prose, no code fences) with fields:\n"
        '  "met": boolean (true only if the evidence clearly supports this aspect)\n'
        '  "reason": string explaining the decision (required when met is false)\n'
        '  "citations": array of {"filename": string, "page": integer, '
        '"quote": string} drawn from the sub-documents above.\n'
    )


def _parse_citations(
    raw: object, sub_docs: list[SubDocument]
) -> list[EvidenceCitation]:
    if not isinstance(raw, list):
        return []
    known = {s.filename for s in sub_docs}
    out: list[EvidenceCitation] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        filename = c.get("filename")
        if not isinstance(filename, str) or filename not in known:
            continue
        try:
            page = int(c.get("page"))
        except (TypeError, ValueError):
            continue
        if page <= 0:
            continue
        quote = c.get("quote")
        out.append(
            EvidenceCitation(
                filename=filename,
                page=page,
                quote=quote.strip() if isinstance(quote, str) else "",
            )
        )
    return out


def _subdocs_for_item(name: str, sub_docs: list[SubDocument]) -> list[SubDocument]:
    """Pick the sub-documents to ground a given capacity item.

    Turnover is grounded specifically in the CA turnover certificate (Req 6.2);
    the other items use all sub-documents.
    """
    if name == "turnover":
        ca = [s for s in sub_docs if s.classified_as == CA_TURNOVER_KEY]
        if ca:
            return ca
    return sub_docs


def _assess_item(
    name: str, tender: TenderBrief, sub_docs: list[SubDocument]
) -> CapacityItemResult:
    """Assess one capacity item, enforcing the unmet-has-reason invariant."""
    relevant = _subdocs_for_item(name, sub_docs)
    focus = _ITEM_FOCUS[name]
    try:
        raw = llm.generate(
            build_capacity_prompt(name, focus, tender, relevant), temperature=0.1
        )
        payload = parse_json(raw)
        if not isinstance(payload, dict):
            raise ValueError("capacity payload was not a JSON object")
    except Exception as exc:  # graceful degradation — unmet with error reason
        return CapacityItemResult(
            name=name,
            met=False,
            reason=f"Could not assess this capacity item due to an error: {exc}",
            citations=[],
        )

    met = bool(payload.get("met"))
    reason = payload.get("reason")
    reason = reason.strip() if isinstance(reason, str) else ""
    citations = _parse_citations(payload.get("citations"), relevant)

    # Req 6.4: every unmet item must record a non-empty reason.
    if not met and not reason:
        reason = "The bid documents do not demonstrate this capacity requirement."

    return CapacityItemResult(
        name=name,
        met=met,
        reason=reason,
        citations=citations,
    )


def assess_capacity(
    sub_docs: list[SubDocument], tender: TenderBrief, bid_id: str = ""
) -> CapacityResult:
    """Assess the four capacity items for a bid and roll up the qualification.

    Builds one :class:`CapacityItemResult` per item (turnover, experience,
    delivered projects, certifications; Req 6.1). Turnover is grounded in the
    ``ca_turnover`` sub-document when present (Req 6.2). ``capacity_qualified``
    is ``True`` only when all four items are met (Req 6.3); each unmet item
    carries a reason (Req 6.4). Never raises.
    """
    items = [_assess_item(name, tender, sub_docs) for name in _CAPACITY_ITEMS]
    qualified = all(item.met for item in items)
    return CapacityResult(
        bid_id=bid_id,
        capacity_qualified=qualified,
        items=items,
    )
