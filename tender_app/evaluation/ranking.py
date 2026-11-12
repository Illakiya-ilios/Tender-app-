"""Stage 3 (8): best-match ranking and shortlist (pure, deterministic — no LLM).

``build_shortlist`` consumes the per-bid :class:`BidEvaluation` results and
produces a :class:`Shortlist` the officer reviews. It is a pure function of its
input so it is fully explainable and property-testable.

Eligibility (Req 8.1)
    A bid is *eligible* iff it is:

    - ``completeness.complete`` is ``True``, AND
    - every :class:`CoverageFinding` in ``coverage`` has status
      :attr:`CoverageStatus.SATISFIED`, AND
    - ``capacity.capacity_qualified`` is ``True``.

    "Every coverage finding satisfied" is defined as
    ``all(f.status == SATISFIED for f in bid.coverage)``. With an empty coverage
    list this is vacuously ``True``: a bid with genuinely zero requirement items
    is not blocked on coverage. (In the real pipeline every bid carries one
    finding per requirement item, so emptiness only arises for a tender with no
    requirement items.)

Ranking (Req 8.2, 8.3, 8.6)
    Eligible bids whose price is available are ranked ``1..k`` by non-decreasing
    price, with a stable tie-break on ``bid_id`` for determinism. The rank-1 bid
    is the ``best_match_bid_id`` (Req 8.3). Eligible bids whose price is *not*
    available receive ``rank = None`` (unranked-on-price) but still appear as
    entries (Req 8.6).

No eligible bid (Req 8.5)
    When no bid is eligible, ``none_eligible`` is ``True``, ``best_match_bid_id``
    is ``None``, and every entry carries at least one non-empty
    ``blocking_reason`` explaining why that bid is not eligible.

Every input bid produces exactly one :class:`ShortlistEntry` (eligible or not)
so the UI can show the full field.
"""
from __future__ import annotations

from tender_app.evaluation.models import (
    BidEvaluation,
    CoverageStatus,
    Shortlist,
    ShortlistEntry,
)


def _all_satisfied(bid: BidEvaluation) -> bool:
    """True iff every coverage finding is Satisfied (vacuously true if empty)."""
    return all(f.status == CoverageStatus.SATISFIED for f in bid.coverage)


def _is_eligible(bid: BidEvaluation) -> bool:
    """Eligible = complete AND all coverage Satisfied AND capacity-qualified."""
    return (
        bid.completeness.complete
        and _all_satisfied(bid)
        and bid.capacity.capacity_qualified
    )


def _strengths(bid: BidEvaluation) -> list[str]:
    """Positive highlights: satisfied requirement items and met capacity items."""
    out: list[str] = []
    satisfied = [f.requirement_key for f in bid.coverage
                 if f.status == CoverageStatus.SATISFIED]
    if satisfied:
        out.append(
            f"Satisfies {len(satisfied)} requirement item(s): "
            + ", ".join(satisfied)
        )
    met_caps = [i.name for i in bid.capacity.items if i.met]
    if met_caps:
        out.append("Capacity met: " + ", ".join(met_caps))
    if bid.capacity.capacity_qualified:
        out.append("Capacity-qualified")
    return out


def _gaps(bid: BidEvaluation) -> list[str]:
    """Shortfalls: partly- and not-satisfied requirement items."""
    out: list[str] = []
    for f in bid.coverage:
        if f.status == CoverageStatus.PARTLY:
            detail = f" ({f.reason})" if f.reason else ""
            out.append(f"Partly satisfied: {f.requirement_key}{detail}")
        elif f.status == CoverageStatus.NOT:
            detail = f" ({f.reason})" if f.reason else ""
            out.append(f"Not satisfied: {f.requirement_key}{detail}")
    for i in bid.capacity.items:
        if not i.met:
            detail = f" ({i.reason})" if i.reason else ""
            out.append(f"Capacity gap: {i.name}{detail}")
    return out


def _risks(bid: BidEvaluation) -> list[str]:
    """Risks: unavailable price and any unreadable required documents."""
    out: list[str] = []
    if not bid.price.available:
        note = bid.price.note or "price not extractable; cannot rank on price"
        out.append(f"Price unavailable: {note}")
    if bid.completeness.unreadable:
        out.append(
            "Unreadable document(s): " + ", ".join(bid.completeness.unreadable)
        )
    return out


def _blocking_reasons(bid: BidEvaluation) -> list[str]:
    """Why this bid is not eligible. Non-empty whenever the bid is ineligible."""
    reasons: list[str] = []
    if not bid.completeness.complete:
        parts: list[str] = []
        if bid.completeness.missing:
            parts.append("missing: " + ", ".join(bid.completeness.missing))
        if bid.completeness.unreadable:
            parts.append("unreadable: " + ", ".join(bid.completeness.unreadable))
        detail = f" ({'; '.join(parts)})" if parts else ""
        reasons.append(f"Bid is not complete{detail}")

    unsatisfied = [
        f.requirement_key for f in bid.coverage
        if f.status != CoverageStatus.SATISFIED
    ]
    if unsatisfied:
        reasons.append(
            "Requirement(s) not satisfied: " + ", ".join(unsatisfied)
        )

    if not bid.capacity.capacity_qualified:
        unmet = [i.name for i in bid.capacity.items if not i.met]
        detail = f" (unmet: {', '.join(unmet)})" if unmet else ""
        reasons.append(f"Not capacity-qualified{detail}")

    return reasons


def _reasons(bid: BidEvaluation, rank: int | None) -> list[str]:
    """Per-ranked-bid reasons mentioning price, coverage and capacity (Req 8.4)."""
    reasons: list[str] = []
    if rank is not None:
        reasons.append(f"Ranked #{rank} by price (ascending)")
    if bid.price.available and bid.price.amount is not None:
        reasons.append(
            f"Price: {bid.price.amount:g} {bid.price.currency}"
        )
    else:
        reasons.append("Price: unavailable (unranked on price)")

    n_items = len(bid.coverage)
    n_satisfied = sum(
        1 for f in bid.coverage if f.status == CoverageStatus.SATISFIED
    )
    reasons.append(
        f"Coverage: {n_satisfied}/{n_items} requirement item(s) satisfied"
    )
    reasons.append(
        "Capacity: qualified"
        if bid.capacity.capacity_qualified
        else "Capacity: not qualified"
    )
    return reasons


def build_shortlist(bids: list[BidEvaluation]) -> Shortlist:
    """Build the best-match :class:`Shortlist` from per-bid evaluations.

    Pure and deterministic. See the module docstring for the eligibility rule
    (Req 8.1), ranking order (Req 8.2/8.3/8.6), and the no-eligible-bid handling
    (Req 8.5).
    """
    eligibility = {id(b): _is_eligible(b) for b in bids}

    # Eligible bids with an available price, ranked by (price, bid_id) for a
    # stable, deterministic total order (Req 8.2).
    rankable = [
        b for b in bids
        if eligibility[id(b)] and b.price.available and b.price.amount is not None
    ]
    rankable.sort(key=lambda b: (b.price.amount, b.bid.bid_id))

    rank_by_id: dict[int, int] = {}
    for position, b in enumerate(rankable, start=1):
        rank_by_id[id(b)] = position

    # Rank-1 bid is the best match (Req 8.3); None if nothing is rankable.
    best_match_bid_id = rankable[0].bid.bid_id if rankable else None
    none_eligible = not any(eligibility.values())

    entries: list[ShortlistEntry] = []
    for b in bids:
        eligible = eligibility[id(b)]
        rank = rank_by_id.get(id(b))  # None if not rankable-on-price

        if eligible:
            blocking: list[str] = []
            reasons = _reasons(b, rank)
        else:
            blocking = _blocking_reasons(b)
            reasons = []

        entries.append(
            ShortlistEntry(
                bid_id=b.bid.bid_id,
                bidder_name=b.bid.bidder_name,
                rank=rank,
                eligible=eligible,
                price=b.price.amount if b.price.available else None,
                weighted_score=b.weighted_score,
                strengths=_strengths(b),
                gaps=_gaps(b),
                risks=_risks(b),
                reasons=reasons,
                blocking_reasons=blocking,
            )
        )

    return Shortlist(
        entries=entries,
        best_match_bid_id=best_match_bid_id,
        none_eligible=none_eligible,
    )
