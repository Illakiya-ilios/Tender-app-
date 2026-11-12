"""Pytest root configuration.

Ensures the workspace root is on ``sys.path`` so the production package is
importable as ``tender_app`` (and therefore ``tender_app.evaluation.*``) when
tests run from the workspace root via ``.venv\\Scripts\\python.exe -m pytest``.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import pytest

from tests.fixtures import make_bid_evaluation as _make_bid_evaluation


@pytest.fixture
def make_bid_evaluation():
    """Expose the synthetic ``BidEvaluation`` builder as a pytest fixture.

    Returns the :func:`tests.fixtures.make_bid_evaluation` factory so tests can
    construct fully-compliant (or deliberately ineligible) bidders with a
    configurable ``bid_id`` and ``price`` for multi-bidder ranking.
    """
    return _make_bid_evaluation
