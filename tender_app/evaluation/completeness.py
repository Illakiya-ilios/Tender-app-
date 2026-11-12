"""Stage 3 (4): the completeness gate (pure, deterministic — no LLM).

For each :class:`RequiredDocumentType`, decides presence from the classified
:class:`SubDocument`s of a bid:

- at least one sub-document classified as that type AND readable
  -> :attr:`DocPresence.PRESENT` (Req 4.1)
- none classified as that type at all -> :attr:`DocPresence.MISSING`,
  key added to ``missing`` (Req 4.2)
- present only via unreadable sub-documents -> :attr:`DocPresence.PRESENT_UNREADABLE`,
  key added to ``unreadable`` (Req 4.3)

The bid is ``complete`` only when no type is missing and none is
present-but-unreadable; any missing/unreadable type is the scoring gate and
forces ``complete = False`` (Req 4.4, 4.5). Each cell carries evidence
citations (filename + page_start) from a matching sub-document (Req 4.6).

This function is pure and deterministic so it can be property-tested.
"""
from __future__ import annotations

from tender_app.evaluation.models import (
    CompletenessResult,
    DocCheckCell,
    DocPresence,
    EvidenceCitation,
    RequiredDocumentType,
    SubDocument,
)


def _citation(sub: SubDocument) -> EvidenceCitation:
    """Build an evidence citation pointing at a sub-document's first page."""
    return EvidenceCitation(filename=sub.filename, page=sub.page_start)


def check_completeness(
    sub_docs: list[SubDocument],
    types: list[RequiredDocumentType],
    bid_id: str = "",
    bidder_name: str = "",
) -> CompletenessResult:
    """Evaluate the completeness gate for one bid.

    Returns a :class:`CompletenessResult` with one :class:`DocCheckCell` per
    required type (carrying its presence and any citations), the lists of
    ``missing`` / ``unreadable`` type keys, and ``complete`` set to ``True`` iff
    every required type has at least one present-and-readable sub-document.
    """
    cells: list[DocCheckCell] = []
    missing: list[str] = []
    unreadable: list[str] = []

    for req_type in types:
        matches = [s for s in sub_docs if s.classified_as == req_type.key]
        readable_matches = [s for s in matches if s.readable]

        if readable_matches:
            presence = DocPresence.PRESENT
            citations = [_citation(s) for s in readable_matches]
        elif matches:
            # Present only via unreadable sub-documents (Req 4.3).
            presence = DocPresence.PRESENT_UNREADABLE
            citations = [_citation(s) for s in matches]
            unreadable.append(req_type.key)
        else:
            # Nothing classified as this type at all (Req 4.2).
            presence = DocPresence.MISSING
            citations = []
            missing.append(req_type.key)

        cells.append(
            DocCheckCell(
                document_key=req_type.key,
                presence=presence,
                citations=citations,
            )
        )

    # Complete iff no type is missing and none is present-but-unreadable
    # (Req 4.4 / 4.5). This is the scoring gate.
    complete = not missing and not unreadable

    return CompletenessResult(
        bid_id=bid_id,
        complete=complete,
        cells=cells,
        missing=missing,
        unreadable=unreadable,
    )
