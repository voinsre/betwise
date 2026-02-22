"""Value bet detector — Phase 3/5.

Compares model probabilities against best bookmaker odds to identify
value bets where the model assigns higher probability than the market.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.odds import Odds

logger = logging.getLogger(__name__)


class ValueDetector:
    """Compare model probabilities against bookmaker odds to find value."""

    def __init__(
        self,
        min_edge: float | None = None,
        odds_min: float | None = None,
        odds_max: float | None = None,
    ):
        self.min_edge = min_edge if min_edge is not None else settings.MIN_EDGE
        self.odds_min = odds_min if odds_min is not None else settings.ODDS_MIN
        self.odds_max = odds_max if odds_max is not None else settings.ODDS_MAX

    async def detect(
        self, session: AsyncSession, prediction_result: dict
    ) -> list[dict]:
        """
        Compare Poisson output against best bookmaker odds for a fixture.

        Returns list of dicts sorted by edge descending, each containing:
        market, label, model_prob, best_odd, bookmaker, implied_prob,
        edge, ev, is_value.
        """
        fixture_id = prediction_result["fixture_id"]

        # Load all odds for this fixture
        result = await session.execute(
            select(Odds).where(Odds.fixture_id == fixture_id)
        )
        odds_rows = result.scalars().all()

        # Build best odds per (market, label) — highest value wins
        best_odds: dict[tuple[str, str], Odds] = {}
        for o in odds_rows:
            key = (o.market, o.label)
            if key not in best_odds or o.value > best_odds[key].value:
                best_odds[key] = o

        value_bets = []
        markets = prediction_result["markets"]

        for market, selections in markets.items():
            for label, model_prob in selections.items():
                key = (market, label)
                if key not in best_odds:
                    continue

                o = best_odds[key]
                implied_prob = 1.0 / o.value
                edge = model_prob - implied_prob
                ev = (model_prob * (o.value - 1)) - (1 - model_prob)

                is_value = (
                    edge > self.min_edge
                    and o.value >= self.odds_min
                    and o.value <= self.odds_max
                )

                value_bets.append({
                    "market": market,
                    "label": label,
                    "model_prob": round(model_prob, 4),
                    "best_odd": o.value,
                    "bookmaker": o.bookmaker_name,
                    "implied_prob": round(implied_prob, 4),
                    "edge": round(edge, 4),
                    "ev": round(ev, 4),
                    "is_value": is_value,
                })

        value_bets.sort(key=lambda x: x["edge"], reverse=True)
        return value_bets
