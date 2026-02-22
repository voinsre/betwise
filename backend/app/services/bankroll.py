"""Kelly criterion bankroll manager — Phase 6.

Fractional Kelly for single bets and accumulators with
correlation-discounted combined probability.
"""

import logging

logger = logging.getLogger(__name__)


class BankrollManager:
    """Fractional Kelly Criterion for stake sizing."""

    def __init__(self, kelly_multiplier: float = 0.25, max_stake_pct: float = 0.05):
        self.kelly_multiplier = kelly_multiplier
        self.max_stake_pct = max_stake_pct

    def calc_kelly_stake(
        self, probability: float, odd: float, bankroll: float
    ) -> float:
        """
        Fractional Kelly stake.

        kelly = (p * (o-1) - (1-p)) / (o-1)
        stake = bankroll * kelly * multiplier
        Capped at max_stake_pct of bankroll.
        """
        if odd <= 1.0 or probability <= 0 or probability >= 1:
            return 0.0

        kelly = (probability * (odd - 1) - (1 - probability)) / (odd - 1)
        kelly = max(kelly, 0.0)
        stake = bankroll * kelly * self.kelly_multiplier
        max_stake = bankroll * self.max_stake_pct
        return round(min(stake, max_stake), 2)

    def calc_accumulator_stake(
        self, legs: list[dict], bankroll: float
    ) -> float:
        """
        Kelly stake for multi-leg accumulators.

        Each leg dict must have 'blended_probability' and 'best_odd'.
        Combined probability = product of individual probs * 0.95^(n-1)
        correlation discount (legs are not fully independent).
        """
        if not legs:
            return 0.0

        combined_prob = 1.0
        combined_odds = 1.0
        for leg in legs:
            combined_prob *= leg["blended_probability"]
            combined_odds *= leg["best_odd"]

        # Correlation discount: 0.95 per extra leg
        n = len(legs)
        if n > 1:
            combined_prob *= 0.95 ** (n - 1)

        return self.calc_kelly_stake(combined_prob, combined_odds, bankroll)
