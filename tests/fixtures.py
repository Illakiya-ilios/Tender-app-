"""Synthetic fixtures for exercising multi-bidder ranking.

Both real sample bids (``extracted_1/``, ``extracted_2/``) belong to the same
single bidder, so ranking (which needs several distinct bidders at different
prices) is exercised with synthetic, fully-configurable
:class:`BidEvaluation` objects built by :func:`make_bid_evaluation`.
"""
from __future__ import annotations

from typing import Optional, Sequence

from tender_app.evaluation.models import (
    Bid,
    BidEvaluation,
    BidPrice,
    CapacityItemResult,
    CapacityResult,
    CompletenessResult,
    CoverageFinding,
    CoverageStatus,
    EvidenceCitation,
)

DEFAULT_COVERAGE_KEYS = ("elig_1", "tech_1", "cap_1")


def make_bid_evaluation(
    bid_id: str,
    price: Optional[float] = None,
    *,
    bidder_name: str = "",
    complete: bool = True,
    all_satisfied: bool = True,
    capacity: bool = True,
    coverage_keys: Sequence[str] = DEFAULT_COVERAGE_KEYS,
    coverage_status: Optional[CoverageStatus] = None,
    currency: str = "INR",
    weighted_score: float = 0.0,
) -> BidEvaluation:
    """Build a configurable :class:`BidEvaluation` for ranking tests.

    Args:
        bid_id: unique bid identifier.
        price: quoted price; ``None`` means the price is unavailable
            (``BidPrice.available = False``), i.e. unranked-on-price.
        complete: value of ``completeness.complete``.
        all_satisfied: when ``True`` every coverage finding is ``Satisfied``;
            when ``False`` findings use ``coverage_status`` (default
            ``Not Satisfied``) so the bid is coverage-ineligible.
        capacity: value of ``capacity.capacity_qualified``.
        coverage_keys: requirement keys to emit one finding each for.
        coverage_status: explicit status for the non-satisfied case; defaults
            to ``CoverageStatus.NOT`` when ``all_satisfied`` is ``False``.
        currency: price currency.
        weighted_score: weighted score carried onto the entry.

    A fully-compliant, priced bidder is the default (``complete=True``,
    ``all_satisfied=True``, ``capacity=True``) given a numeric ``price``.
    """
    bidder = bidder_name or f"Bidder {bid_id}"

    # Coverage findings — satisfied carry a citation; non-satisfied carry a reason.
    status = (
        CoverageStatus.SATISFIED
        if all_satisfied
        else (coverage_status or CoverageStatus.NOT)
    )
    findings: list[CoverageFinding] = []
    for key in coverage_keys:
        if status == CoverageStatus.SATISFIED:
            findings.append(
                CoverageFinding(
                    requirement_key=key,
                    status=CoverageStatus.SATISFIED,
                    citations=[
                        EvidenceCitation(filename=f"{key}.pdf", page=1, quote="ok")
                    ],
                )
            )
        else:
            findings.append(
                CoverageFinding(
                    requirement_key=key,
                    status=status,
                    reason=f"{key} not demonstrated",
                )
            )

    completeness = CompletenessResult(
        bid_id=bid_id,
        complete=complete,
        missing=[] if complete else ["some_required_doc"],
    )

    capacity_result = CapacityResult(
        bid_id=bid_id,
        capacity_qualified=capacity,
        items=[
            CapacityItemResult(
                name="turnover",
                met=capacity,
                reason="" if capacity else "turnover below threshold",
            )
        ],
    )

    if price is None:
        bid_price = BidPrice(
            bid_id=bid_id,
            available=False,
            amount=None,
            currency=currency,
            note="price not extractable; officer must supply",
        )
    else:
        bid_price = BidPrice(
            bid_id=bid_id,
            available=True,
            amount=float(price),
            currency=currency,
            citation=EvidenceCitation(filename="price_schedule.pdf", page=1),
        )

    return BidEvaluation(
        bid=Bid(bid_id=bid_id, bidder_name=bidder),
        completeness=completeness,
        coverage=findings,
        capacity=capacity_result,
        price=bid_price,
        weighted_score=weighted_score,
    )
