"""Stage 3 orchestrator: wire stages 1-8 into an :class:`EvaluationRun`.

The pipeline runs in two officer-gated phases so the routes can call them
separately around the human-in-the-loop release step:

Phase 1 — :func:`run_evaluation` (document check)
    intake -> extract -> classify -> completeness, per bid. Derives the
    ``required_types`` and ``requirement_items`` from the Source_Tender, builds
    one :class:`Bid` per input (capturing the classified sub-documents on each
    :class:`BidDocument`), runs the completeness gate, and seeds one preliminary
    :class:`BidEvaluation` per bid holding the completeness result with EMPTY
    coverage / capacity / price placeholders. A bid with no evaluable PDF is
    marked ``evaluable = False`` and still surfaces as an incomplete evaluation
    (Req 1.4).

Phase 2 — :func:`release_and_score` (the officer release gate, Req 4.5)
    For each COMPLETE bid, runs coverage + capacity + pricing, then
    ``ranking.build_shortlist`` over all evaluations. Incomplete bids are NOT
    scored (Req 4.4) but remain in the evaluations list with their completeness
    and blocking information so they still appear in the shortlist.

Passing sub-documents between phases
    Phase 2 reconstructs each bid's sub-documents from
    ``Bid.documents[].sub_documents`` rather than keeping a transient side
    object. :class:`SubDocument` already carries ``text`` and ``classified_as``,
    so everything phase 2 needs is inside the serialisable model — no
    re-extraction, no re-classification, and the :class:`EvaluationRun` remains
    the single source of truth that can be persisted/reloaded between phases.

Graceful degradation (Error Handling section)
    Per-bid work in both phases is wrapped so one bad bid records a stage error
    on that bid and the run continues. The LLM-driven stage functions already
    degrade internally (OCR failure -> unreadable; coverage/capacity default to
    Not Satisfied / not-qualified with the error as the reason), so a single API
    hiccup never aborts the whole run.
"""
from __future__ import annotations

import datetime as _dt
import uuid
from pathlib import Path

from tender_app import config
from tender_app.evaluation import (
    capacity as capacity_stage,
    classify as classify_stage,
    completeness as completeness_stage,
    coverage as coverage_stage,
    extract as extract_stage,
    intake as intake_stage,
    pricing as pricing_stage,
    ranking as ranking_stage,
    requirements_source,
)
from tender_app.evaluation.models import (
    Bid,
    BidDocument,
    BidEvaluation,
    BidPrice,
    CapacityResult,
    CompletenessResult,
    EvaluationRun,
    RequiredDocumentType,
    SubDocument,
)
from tender_app.models import TenderBrief


def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _empty_capacity(bid_id: str) -> CapacityResult:
    """A not-yet-scored capacity placeholder (phase 1)."""
    return CapacityResult(bid_id=bid_id, capacity_qualified=False, items=[])


def _empty_price(bid_id: str) -> BidPrice:
    """A not-yet-scored price placeholder (phase 1)."""
    return BidPrice(
        bid_id=bid_id,
        available=False,
        amount=None,
        note="Not yet scored (bid not released for scoring).",
    )


def _incomplete_completeness(
    bid_id: str, types: list[RequiredDocumentType], note: str
) -> CompletenessResult:
    """Completeness result for a bid with no evaluable documents (Req 1.4).

    Every required type is reported missing so the bid is clearly incomplete and
    surfaces in the matrix rather than crashing the run.
    """
    return CompletenessResult(
        bid_id=bid_id,
        complete=False,
        cells=[],
        missing=[t.key for t in types],
        unreadable=[],
    )


def _bid_documents_from_subdocs(
    sub_docs: list[SubDocument],
) -> list[BidDocument]:
    """Group classified sub-documents back under their source PDF filename.

    Preserves first-seen filename order so the captured documents are stable and
    phase 2 can reconstruct the full sub-document set from the model alone.
    """
    by_file: dict[str, BidDocument] = {}
    order: list[str] = []
    for sub in sub_docs:
        doc = by_file.get(sub.filename)
        if doc is None:
            doc = BidDocument(filename=sub.filename, sub_documents=[])
            by_file[sub.filename] = doc
            order.append(sub.filename)
        doc.sub_documents.append(sub)
    return [by_file[name] for name in order]


def _subdocs_from_bid(bid: Bid) -> list[SubDocument]:
    """Reconstruct a bid's sub-documents from its captured BidDocuments.

    This is the inverse of :func:`_bid_documents_from_subdocs`; it lets phase 2
    score a bid using the sub-document text + classification already stored on
    the model, with no re-extraction.
    """
    subs: list[SubDocument] = []
    for doc in bid.documents:
        subs.extend(doc.sub_documents)
    return subs


def _process_bid_document_check(
    bid_id: str,
    bidder_name: str,
    archives: list[Path],
    run_dir: Path,
    required_types: list[RequiredDocumentType],
) -> BidEvaluation:
    """Phase-1 work for a single bid: intake -> extract -> classify -> completeness.

    Wrapped by the caller for graceful degradation. Returns a preliminary
    :class:`BidEvaluation` holding only the completeness result (coverage /
    capacity / price are empty placeholders filled in phase 2).
    """
    bid_run_dir = run_dir / bid_id

    intake_result = intake_stage.extract_bid(archives, bid_id, bid_run_dir)

    # No evaluable PDF -> mark the bid not evaluable, skip extraction, but still
    # produce an incomplete evaluation so the bid surfaces (Req 1.4).
    if not intake_result.evaluable:
        bid = Bid(
            bid_id=bid_id,
            bidder_name=bidder_name,
            documents=[],
            evaluable=False,
        )
        completeness = _incomplete_completeness(
            bid_id, required_types, "contains no evaluable documents"
        )
        return BidEvaluation(
            bid=bid,
            completeness=completeness,
            coverage=[],
            capacity=_empty_capacity(bid_id),
            price=_empty_price(bid_id),
        )

    # Extract each discovered PDF, then classify into sub-documents.
    docs = [
        extract_stage.extract_document(Path(pdf_path))
        for pdf_path in intake_result.pdf_paths
    ]
    sub_docs = classify_stage.classify_bid(docs, required_types)

    completeness = completeness_stage.check_completeness(
        sub_docs, required_types, bid_id, bidder_name
    )

    bid = Bid(
        bid_id=bid_id,
        bidder_name=bidder_name,
        documents=_bid_documents_from_subdocs(sub_docs),
        evaluable=True,
    )

    return BidEvaluation(
        bid=bid,
        completeness=completeness,
        coverage=[],
        capacity=_empty_capacity(bid_id),
        price=_empty_price(bid_id),
    )


def run_evaluation(
    tender: TenderBrief,
    bid_inputs: list[tuple[str, str, list[Path]]],
    run_dir: Path | None = None,
) -> EvaluationRun:
    """Phase 1: run the document check for every bid and build the run.

    ``bid_inputs`` is a list of ``(bid_id, bidder_name, archives)`` tuples. For
    each bid this runs intake -> extract -> classify -> completeness and stores a
    preliminary :class:`BidEvaluation` (completeness only). The returned
    :class:`EvaluationRun` carries the derived ``required_types`` /
    ``requirement_items`` and awaits an officer release before scoring.

    A per-bid failure is caught so one bad bid does not abort the run: the bid
    is recorded as not evaluable / incomplete with the error noted.
    """
    run_id = uuid.uuid4().hex
    created_at = _now_iso()

    if run_dir is None:
        run_dir = config.EVAL_DIR / f"run_{run_id}"
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    required_types = requirements_source.required_document_types(tender)
    requirement_items = requirements_source.requirement_items(tender)

    bids: list[Bid] = []
    evaluations: list[BidEvaluation] = []

    for bid_id, bidder_name, archives in bid_inputs:
        try:
            evaluation = _process_bid_document_check(
                bid_id, bidder_name, list(archives), run_dir, required_types
            )
        except Exception as exc:  # graceful degradation — never abort the run.
            bid = Bid(
                bid_id=bid_id,
                bidder_name=bidder_name,
                documents=[],
                evaluable=False,
            )
            completeness = _incomplete_completeness(
                bid_id,
                required_types,
                f"document check failed: {exc}",
            )
            evaluation = BidEvaluation(
                bid=bid,
                completeness=completeness,
                coverage=[],
                capacity=_empty_capacity(bid_id),
                price=_empty_price(bid_id),
            )

        bids.append(evaluation.bid)
        evaluations.append(evaluation)

    return EvaluationRun(
        run_id=run_id,
        created_at=created_at,
        tender=tender,
        required_types=required_types,
        requirement_items=requirement_items,
        bids=bids,
        evaluations=evaluations,
    )


def _score_bid(run: EvaluationRun, evaluation: BidEvaluation) -> None:
    """Phase-2 scoring for one COMPLETE bid, mutating ``evaluation`` in place.

    Reconstructs the bid's sub-documents from the model and runs coverage,
    capacity and pricing. Wrapped by the caller for graceful degradation.
    """
    bid = evaluation.bid
    sub_docs = _subdocs_from_bid(bid)

    evaluation.coverage = coverage_stage.assess_coverage(
        sub_docs, run.requirement_items
    )
    evaluation.capacity = capacity_stage.assess_capacity(
        sub_docs, run.tender, bid.bid_id
    )
    evaluation.price = pricing_stage.extract_price(sub_docs, bid.bid_id)


def release_and_score(run: EvaluationRun) -> EvaluationRun:
    """Phase 2 (officer release gate, Req 4.5): score complete bids and rank.

    For every COMPLETE bid (``completeness.complete`` is ``True``) runs coverage
    + capacity + pricing and fills the :class:`BidEvaluation`. Incomplete bids
    are left unscored (Req 4.4) but remain in ``run.evaluations`` with their
    completeness + blocking info. Finally builds ``run.shortlist`` from all
    evaluations via :func:`ranking.build_shortlist`. Mutates and returns ``run``.

    A per-bid scoring failure is caught so one bad bid does not abort the run;
    the LLM stages also degrade internally.
    """
    for evaluation in run.evaluations:
        if not evaluation.completeness.complete:
            # Incomplete bids are not scored (Req 4.4); they still rank as
            # ineligible via their completeness/blocking info.
            continue
        try:
            _score_bid(run, evaluation)
        except Exception as exc:  # graceful degradation — keep the run going.
            evaluation.price = BidPrice(
                bid_id=evaluation.bid.bid_id,
                available=False,
                amount=None,
                note=f"Scoring failed: {exc}",
            )

    run.shortlist = ranking_stage.build_shortlist(run.evaluations)
    return run
