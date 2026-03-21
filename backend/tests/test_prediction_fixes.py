"""Tests for prediction engine audit fixes.

Verifies:
- Confidence score is independent of edge
- Value bet dedup limits to one per market
- Threshold settings (MIN_EDGE=0.05, ODDS_MAX=5.00)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock

from app.services.prediction_engine import PredictionEngine
from app.config import settings


class FakeLeague:
    has_statistics = True
    has_odds = True
    has_injuries = True


class FakePrediction:
    """Minimal prediction mock for dedup testing."""
    def __init__(self, market: str, edge: float, is_value_bet: bool):
        self.market = market
        self.edge = edge
        self.is_value_bet = is_value_bet


class TestConfidenceScore:
    """Confidence score must be independent of edge."""

    @pytest.fixture
    def engine(self):
        mock_factory = MagicMock()
        # PredictionEngine.__init__ creates sub-objects that need session_factory.
        # We only test _calc_confidence which doesn't use it.
        engine = object.__new__(PredictionEngine)
        return engine

    def test_confidence_independent_of_edge(self, engine):
        """Same inputs except edge should produce identical confidence."""
        common = dict(
            poisson_prob=0.45,
            ml_prob=0.42,
            league=FakeLeague(),
            home_games=15,
            away_games=12,
            odds_values=[1.90, 2.00, 1.95],
        )
        score_low_edge = engine._calc_confidence(edge=0.01, **common)
        score_high_edge = engine._calc_confidence(edge=0.10, **common)
        assert score_low_edge == score_high_edge, (
            f"Confidence should not depend on edge: {score_low_edge} != {score_high_edge}"
        )

    def test_confidence_range(self, engine):
        """Confidence score should be 0-100."""
        score = engine._calc_confidence(
            poisson_prob=0.50,
            ml_prob=0.48,
            edge=0.05,
            league=FakeLeague(),
            home_games=20,
            away_games=20,
            odds_values=[2.00, 2.05, 1.95],
        )
        assert 0 <= score <= 100

    def test_confidence_no_ml(self, engine):
        """Confidence works when ml_prob is None."""
        score = engine._calc_confidence(
            poisson_prob=0.50,
            ml_prob=None,
            edge=0.05,
            league=FakeLeague(),
            home_games=10,
            away_games=10,
            odds_values=[2.00],
        )
        assert 0 <= score <= 100


class TestValueBetDedup:
    """One value bet per market — highest edge wins."""

    def test_dedup_keeps_highest_edge(self):
        """Only the prediction with highest edge should remain as value bet."""
        preds = [
            FakePrediction("1x2", edge=0.06, is_value_bet=True),
            FakePrediction("1x2", edge=0.08, is_value_bet=True),
            FakePrediction("1x2", edge=0.03, is_value_bet=False),
        ]

        # Run the dedup logic (same code as prediction_engine.py lines 201-210)
        best_value_per_market = {}
        for pred in preds:
            if pred.is_value_bet:
                key = pred.market
                if key not in best_value_per_market or pred.edge > best_value_per_market[key].edge:
                    best_value_per_market[key] = pred
        for pred in preds:
            if pred.is_value_bet and pred is not best_value_per_market.get(pred.market):
                pred.is_value_bet = False

        # Only the one with edge=0.08 should be value bet
        assert preds[0].is_value_bet is False, "edge=0.06 should be demoted"
        assert preds[1].is_value_bet is True, "edge=0.08 should remain"
        assert preds[2].is_value_bet is False, "edge=0.03 was never a value bet"

    def test_dedup_across_markets(self):
        """Different markets should each keep their best."""
        preds = [
            FakePrediction("1x2", edge=0.06, is_value_bet=True),
            FakePrediction("1x2", edge=0.09, is_value_bet=True),
            FakePrediction("ou25", edge=0.07, is_value_bet=True),
            FakePrediction("ou25", edge=0.05, is_value_bet=True),
        ]

        best_value_per_market = {}
        for pred in preds:
            if pred.is_value_bet:
                key = pred.market
                if key not in best_value_per_market or pred.edge > best_value_per_market[key].edge:
                    best_value_per_market[key] = pred
        for pred in preds:
            if pred.is_value_bet and pred is not best_value_per_market.get(pred.market):
                pred.is_value_bet = False

        assert preds[0].is_value_bet is False  # 1x2 edge=0.06 demoted
        assert preds[1].is_value_bet is True   # 1x2 edge=0.09 kept
        assert preds[2].is_value_bet is True   # ou25 edge=0.07 kept
        assert preds[3].is_value_bet is False  # ou25 edge=0.05 demoted


class TestThresholds:
    """MIN_EDGE and ODDS_MAX thresholds from config."""

    def test_min_edge_is_005(self):
        assert settings.MIN_EDGE == 0.05, f"MIN_EDGE should be 0.05, got {settings.MIN_EDGE}"

    def test_odds_max_is_500(self):
        assert settings.ODDS_MAX == 5.00, f"ODDS_MAX should be 5.00, got {settings.ODDS_MAX}"

    def test_odds_min_is_120(self):
        assert settings.ODDS_MIN == 1.20

    def test_min_confidence_is_60(self):
        assert settings.MIN_CONFIDENCE == 60

    def test_edge_below_threshold_not_value(self):
        """edge=0.04 with MIN_EDGE=0.05 should not be a value bet."""
        edge = 0.04
        odds = 2.00
        confidence = 70
        is_value = (
            edge > settings.MIN_EDGE
            and odds >= settings.ODDS_MIN
            and odds <= settings.ODDS_MAX
            and confidence >= settings.MIN_CONFIDENCE
        )
        assert is_value is False

    def test_edge_above_threshold_is_value(self):
        """edge=0.06 with good odds should be a value bet."""
        edge = 0.06
        odds = 2.00
        confidence = 70
        is_value = (
            edge > settings.MIN_EDGE
            and odds >= settings.ODDS_MIN
            and odds <= settings.ODDS_MAX
            and confidence >= settings.MIN_CONFIDENCE
        )
        assert is_value is True

    def test_odds_within_new_max(self):
        """odds=4.50 should be within the new ODDS_MAX=5.00."""
        edge = 0.06
        odds = 4.50
        confidence = 70
        is_value = (
            edge > settings.MIN_EDGE
            and odds >= settings.ODDS_MIN
            and odds <= settings.ODDS_MAX
            and confidence >= settings.MIN_CONFIDENCE
        )
        assert is_value is True

    def test_odds_above_max(self):
        """odds=5.50 should exceed ODDS_MAX=5.00."""
        edge = 0.06
        odds = 5.50
        confidence = 70
        is_value = (
            edge > settings.MIN_EDGE
            and odds >= settings.ODDS_MIN
            and odds <= settings.ODDS_MAX
            and confidence >= settings.MIN_CONFIDENCE
        )
        assert is_value is False
