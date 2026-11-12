"""Stage 3 (5): requirement coverage assessment (LLM-driven + invariant post-processor).

For each :class:`RequirementItem` the LLM is asked, grounded in the bid's
classified :class:`SubDocument`s, to decide a :class:`CoverageStatus`
(Satisfied / Partly / Not), to cite the supporting evidence (filename + page +
quote), and to give a reason (Req 5.2, 5.3, 5.4).

Because the LLM is non-deterministic, a deterministic POST-PROCESSOR enforces
the coverage invariants regardless of what the model returns:

- EXACTLY ONE finding per requirement item — no missing, no duplicate. Findings
  are built by iterating the items and keying by ``item.key`` (Req 5.5, 5.2;
  Property 6).
- A ``Satisfied`` / ``Partly Satisfied`` finding MUST carry >=1
  :class:`EvidenceCitation` with a non-empty filename and a positive page. If
  the model returns such a status without a valid citation, we attach a
  best-effort citation from a confidently matched sub-document, or DOWNGRADE the
  status to ``Not Satisfied`` with an explanatory reason (Property 4).
- A ``Not Satisfied`` finding MUST carry a non-empty reason; a default reason is
  supplied when missing (Property 5).

On any LLM/JSON error for an item the finding degrades to ``Not Satisfied`` with
a reason noting the assessment error (graceful degradation). This module never
throws.
"""
from __future__ import annotations

from tender_app import llm
from tender_app.evaluation._jsonutil import parse_json
from tender_app.evaluation.models import (
    CoverageFinding,
    CoverageStatus,
    EvidenceCitation,
    RequirementItem,
    SubDocument,
)

# Cap per sub-document text in the prompt so large bundles stay within budget.
_MAX_SUBDOC_CHARS = 1200

_STATUS_BY_VALUE = {s.value: s for s in CoverageStatus}
# Also accept common short forms the model may emit.
_STATUS_ALIASES = {
    "satisfied": CoverageStatus.SATISFIED,
    "partly": CoverageStatus.PARTLY,
    "partly satisfied": CoverageStatus.PARTLY,
    "partially satisfied": CoverageStatus.PARTLY,
    "not": CoverageStatus.NOT,
    "not satisfied": CoverageStatus.NOT,
}


def _coerce_status(value: object) -> CoverageStatus:
    """Map an LLM-provided status string to a :class:`CoverageStatus`.

    Defaults to ``Not Satisfied`` when the value is unrecognised (the safe
    default — an unknown status should never claim satisfaction).
    """
    if isinstance(value, str):
        v = value.strip()
        if v in _STATUS_BY_VALUE:
            return _STATUS_BY_VALUE[v]
        return _STATUS_ALIASES.get(v.lower(), CoverageStatus.NOT)
    return CoverageStatus.NOT


def _snippet(sub: SubDocument) -> str:
    text = (sub.text or "").strip()
    if len(text) > _MAX_SUBDOC_CHARS:
        text = text[:_MAX_SUBDOC_CHARS] + " …[truncated]"
    if not text:
        text = "(no readable text)"
    return text


def build_coverage_prompt(
    item: RequirementItem, sub_docs: list[SubDocument]
) -> str:
    """Build the per-requirement coverage prompt grounded in sub-documents."""
    doc_lines = []
    for sub in sub_docs:
        doc_lines.append(
            f'--- filename: "{sub.filename}" | pages {sub.page_start}-{sub.page_end}'
            f' | type: {sub.classified_as} ---\n{_snippet(sub)}'
        )
    doc_block = "\n\n".join(doc_lines) if doc_lines else "(no sub-documents available)"

    return (
        "You are evaluating whether a tender bid satisfies ONE specific "
        "requirement, grounded strictly in the bid sub-documents provided "
        "below. Judge only from the supplied text; do not assume evidence that "
        "is not present.\n\n"
        f"REQUIREMENT ({item.req_class.value}): {item.text}\n\n"
        "BID SUB-DOCUMENTS:\n"
        f"{doc_block}\n\n"
        "Return ONLY a JSON object (no prose, no code fences) with fields:\n"
        '  "status": one of "Satisfied", "Partly Satisfied", "Not Satisfied"\n'
        '  "citations": array of objects, each {"filename": string, '
        '"page": integer, "quote": string} drawn from the sub-documents above. '
        "For Satisfied or Partly Satisfied you MUST include at least one "
        "citation whose filename matches a sub-document above and whose page is "
        "within that sub-document's page range.\n"
        '  "reason": string explaining the decision (required, especially when '
        "Not Satisfied).\n"
    )


def _valid_citation(cit: EvidenceCitation) -> bool:
    return bool(cit.filename and cit.filename.strip()) and cit.page > 0


def _parse_citations(
    raw: object, sub_docs: list[SubDocument]
) -> list[EvidenceCitation]:
    """Parse LLM citation objects into valid :class:`EvidenceCitation`s.

    Only citations whose filename matches an available sub-document and whose
    page is positive are kept, so evidence stays grounded.
    """
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
        cit = EvidenceCitation(
            filename=filename,
            page=page,
            quote=quote.strip() if isinstance(quote, str) else "",
        )
        if _valid_citation(cit):
            out.append(cit)
    return out


def _best_effort_citation(
    item: RequirementItem, sub_docs: list[SubDocument]
) -> EvidenceCitation | None:
    """Confidently match a sub-document to the requirement for a fallback citation.

    Prefers a readable sub-document whose ``classified_as`` key matches the
    requirement's ``source_ref`` (a strong, deterministic signal). Returns
    ``None`` when no confident match exists — the caller then downgrades.
    """
    ref = (item.source_ref or "").strip()
    if not ref:
        return None
    for sub in sub_docs:
        if sub.readable and sub.classified_as == ref:
            return EvidenceCitation(
                filename=sub.filename,
                page=sub.page_start if sub.page_start > 0 else 1,
                quote="",
            )
    return None


def _assess_item(
    item: RequirementItem, sub_docs: list[SubDocument]
) -> CoverageFinding:
    """Assess one requirement item and enforce the coverage invariants."""
    try:
        raw = llm.generate(build_coverage_prompt(item, sub_docs), temperature=0.1)
        payload = parse_json(raw)
        if not isinstance(payload, dict):
            raise ValueError("coverage payload was not a JSON object")
    except Exception as exc:  # graceful degradation — never throw (Req 5.2/5.4)
        return CoverageFinding(
            requirement_key=item.key,
            status=CoverageStatus.NOT,
            citations=[],
            reason=f"Could not assess this requirement due to an error: {exc}",
        )

    status = _coerce_status(payload.get("status"))
    citations = _parse_citations(payload.get("citations"), sub_docs)
    reason = payload.get("reason")
    reason = reason.strip() if isinstance(reason, str) else ""

    # Invariant: Satisfied/Partly must carry >=1 valid citation (Property 4).
    if status in (CoverageStatus.SATISFIED, CoverageStatus.PARTLY) and not citations:
        fallback = _best_effort_citation(item, sub_docs)
        if fallback is not None:
            citations = [fallback]
        else:
            # Downgrade — a claim of satisfaction without evidence is not
            # defensible, so record it as Not Satisfied with an explanation.
            status = CoverageStatus.NOT
            reason = (
                "Downgraded to Not Satisfied: no supporting evidence citation "
                "could be grounded in the bid documents."
            )

    # Invariant: Not Satisfied must carry a non-empty reason (Property 5).
    if status == CoverageStatus.NOT and not reason:
        reason = "The bid documents do not provide evidence satisfying this requirement."

    return CoverageFinding(
        requirement_key=item.key,
        status=status,
        citations=citations,
        reason=reason,
    )


def assess_coverage(
    sub_docs: list[SubDocument], items: list[RequirementItem]
) -> list[CoverageFinding]:
    """Assess coverage for every requirement item against a bid's sub-documents.

    Produces EXACTLY ONE :class:`CoverageFinding` per :class:`RequirementItem`
    (Req 5.5; Property 6), each satisfying the evidence/reason invariants
    (Properties 4 and 5). Iterates the item list so the output set matches the
    requirement set exactly — never missing, never duplicated — independent of
    the LLM's output. Never raises.
    """
    return [_assess_item(item, sub_docs) for item in items]
