"""Property-based tests for ``tender_app.evaluation.ranking.build_shortlist``.

These exercise the pure, deterministic ranker with synthetic multi-bidder
collections built via :func:`tests.fixtures.make_bid_evaluation` (both real
sample bids are a single bidder, so ranking needs synthetic inputs).
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from tender_app.evaluation import ranking
from tender_app.evaluation.models import CoverageStatus
from tests.fixtures import make_bid_evaluation


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Prices are drawn from a bounded set of floats (with ties possible) or None
# (unavailable price). Small integer-like set keeps ties frequent so tie-break
# determinism gets exercised.
_price = st.one_of(
    st.none(),
    st.sampled_from([100.0, 200.0, 200.0, 300.0, 500.0, 1000.0]),
    st.floats(min_value=1.0, max_value=5000.0, allow_nan=False, allow_infinity=False),
)

_coverage_keys = st.lists(
    st.sampled_from(["elig_1", "tech_1", "cap_1", "qual_1"]),
    min_size=0,
    max_size=4,
    unique=True,
)


@st.composite
def _bid_spec(draw, *, force_ineligible: bool = False, force_eligible: bool = False):
    """Draw the parameters for one synthetic bid evaluation."""
    complete = draw(st.booleans())
    all_satisfied = draw(st.booleans())
    capacity = draw(st.booleans())
    price = draw(_price)
    keys = draw(_coverage_keys)
    if force_eligible:
        complete = True
        all_satisfied = True
        capacity = True
    return {
        "complete": complete,
        "all_satisfied": all_satisfied,
        "capacity": capacity,
        "price": price,
        "coverage_keys": tuple(keys),
    }


@st.composite
def _collection(draw, min_size=1, max_size=6):
    """A collection of synthetic BidEvaluations with unique bid ids."""
    specs = draw(st.lists(_bid_spec(), min_size=min_size, max_size=max_size))
    bids = []
    for i, spec in enumerate(specs):
        bids.append(make_bid_evaluation(bid_id=f"bid{i}", **spec))
    return bids


def _expected_eligible(bid) -> bool:
    return (
        bid.completeness.complete
        and all(f.status == CoverageStatus.SATISFIED for f in bid.coverage)
        and bid.capacity.capacity_qualified
    )


# ---------------------------------------------------------------------------
# Property 3
# ---------------------------------------------------------------------------
# Feature: bid-evaluation, Property 3: For any collection of bid evaluations, no bid whose completeness.complete is False appears as eligible or as the best_match_bid_id in the shortlist produced by ranking.build_shortlist.
@settings(max_examples=100)
@given(bids=_collection())
def test_incomplete_bids_excluded_from_selection(bids):
    # Validates: Requirements 4.4, 8.1
    shortlist = ranking.build_shortlist(bids)
    entry_by_id = {e.bid_id: e for e in shortlist.entries}

    incomplete_ids = {b.bid.bid_id for b in bids if not b.completeness.complete}
    for bid_id in incomplete_ids:
        assert entry_by_id[bid_id].eligible is False
        assert shortlist.best_match_bid_id != bid_id


# ---------------------------------------------------------------------------
# Property 7
# ---------------------------------------------------------------------------
# Feature: bid-evaluation, Property 7: For any collection of bid evaluations, a bid is marked eligible in the shortlist if and only if it is complete, every requirement item has status Satisfied, and it is capacity-qualified.
@settings(max_examples=100)
@given(bids=_collection())
def test_eligibility_iff_complete_satisfied_capacity(bids):
    # Validates: Requirements 8.1
    shortlist = ranking.build_shortlist(bids)
    entry_by_id = {e.bid_id: e for e in shortlist.entries}

    # One entry per input bid.
    assert len(shortlist.entries) == len(bids)

    for b in bids:
        expected = _expected_eligible(b)
        assert entry_by_id[b.bid.bid_id].eligible is expected


# ---------------------------------------------------------------------------
# Property 8
# ---------------------------------------------------------------------------
# Feature: bid-evaluation, Property 8: For any collection of eligible bids with available prices, ranking.build_shortlist assigns ranks that are a permutation 1..k ordered by non-decreasing price, the entry at rank 1 is the best_match_bid_id, and no bid with an unavailable price is assigned a numeric rank.
@settings(max_examples=100)
@given(bids=_collection())
def test_ranking_is_ascending_total_order_by_price(bids):
    # Validates: Requirements 8.2, 8.3, 8.6
    shortlist = ranking.build_shortlist(bids)
    entry_by_id = {e.bid_id: e for e in shortlist.entries}
    bid_by_id = {b.bid.bid_id: b for b in bids}

    # The set of bids that SHOULD carry a numeric rank: eligible AND priced.
    rankable_ids = [
        b.bid.bid_id
        for b in bids
        if _expected_eligible(b) and b.price.available and b.price.amount is not None
    ]

    ranked_entries = [e for e in shortlist.entries if e.rank is not None]
    k = len(rankable_ids)

    # (a) numeric ranks form exactly the permutation 1..k.
    assert sorted(e.rank for e in ranked_entries) == list(range(1, k + 1))
    assert {e.bid_id for e in ranked_entries} == set(rankable_ids)

    # (b) ranks ordered by non-decreasing price (tie-break by bid_id).
    ordered = sorted(
        ranked_entries,
        key=lambda e: (bid_by_id[e.bid_id].price.amount, e.bid_id),
    )
    for position, e in enumerate(ordered, start=1):
        assert e.rank == position

    # (c) rank 1 is the best match (when any rankable bids exist).
    if k > 0:
        rank1 = next(e for e in ranked_entries if e.rank == 1)
        assert shortlist.best_match_bid_id == rank1.bid_id
    else:
        assert shortlist.best_match_bid_id is None

    # (d) no unavailable-price bid gets a numeric rank.
    for e in shortlist.entries:
        if not bid_by_id[e.bid_id].price.available:
            assert e.rank is None


# ---------------------------------------------------------------------------
# Property 9
# ---------------------------------------------------------------------------
# Feature: bid-evaluation, Property 9: For any collection of eligible priced bids, the best_match_bid_id has a price less than or equal to the price of every other eligible priced bid.
@settings(max_examples=100)
@given(bids=_collection())
def test_best_match_is_minimum_price_eligible_bid(bids):
    # Validates: Requirements 8.3
    shortlist = ranking.build_shortlist(bids)
    bid_by_id = {b.bid.bid_id: b for b in bids}

    eligible_priced = [
        b
        for b in bids
        if _expected_eligible(b) and b.price.available and b.price.amount is not None
    ]

    if not eligible_priced:
        assert shortlist.best_match_bid_id is None
        return

    best_id = shortlist.best_match_bid_id
    assert best_id is not None
    best_price = bid_by_id[best_id].price.amount
    for b in eligible_priced:
        assert best_price <= b.price.amount


# ---------------------------------------------------------------------------
# Property 10
# ---------------------------------------------------------------------------
@st.composite
def _no_eligible_collection(draw):
    """Collection where every bid is guaranteed ineligible.

    Each bid has at least one of complete/all_satisfied/capacity forced False.
    """
    n = draw(st.integers(min_value=1, max_value=6))
    bids = []
    for i in range(n):
        # Choose which eligibility pillar(s) to break; guarantee >=1 broken.
        complete = draw(st.booleans())
        all_satisfied = draw(st.booleans())
        capacity = draw(st.booleans())
        if complete and all_satisfied and capacity:
            # Force at least one pillar to fail.
            which = draw(st.sampled_from(["c", "s", "cap"]))
            if which == "c":
                complete = False
            elif which == "s":
                all_satisfied = False
            else:
                capacity = False
        bids.append(
            make_bid_evaluation(
                bid_id=f"bid{i}",
                price=draw(_price),
                complete=complete,
                all_satisfied=all_satisfied,
                capacity=capacity,
                coverage_keys=("elig_1", "tech_1"),
            )
        )
    return bids


# Feature: bid-evaluation, Property 10: For any collection of bid evaluations in which no bid is eligible, the shortlist has none_eligible = True, best_match_bid_id is None, and every bid has at least one non-empty blocking reason.
@settings(max_examples=100)
@given(bids=_no_eligible_collection())
def test_no_eligible_bid_means_no_best_match(bids):
    # Validates: Requirements 8.5
    # Precondition: no bid is eligible.
    assert not any(_expected_eligible(b) for b in bids)

    shortlist = ranking.build_shortlist(bids)

    assert shortlist.none_eligible is True
    assert shortlist.best_match_bid_id is None
    assert len(shortlist.entries) == len(bids)
    for e in shortlist.entries:
        assert len(e.blocking_reasons) >= 1
        assert all(r.strip() for r in e.blocking_reasons)
