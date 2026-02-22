"""Ticket builder and optimizer — Phase 6.

Assembles optimal betting tickets from value bets using
combinatorial optimization and Kelly criterion staking.
"""

import logging
import uuid
from datetime import date
from itertools import combinations

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.models.ticket import Ticket
from app.services.bankroll import BankrollManager
from app.services.prediction_engine import PredictionEngine

logger = logging.getLogger(__name__)


class TicketBuilder:
    """Build optimized betting tickets from value bets."""

    def __init__(self, session_factory: async_sessionmaker, engine: PredictionEngine):
        self.session_factory = session_factory
        self.engine = engine
        self.bankroll_mgr = BankrollManager(
            kelly_multiplier=settings.KELLY_MULTIPLIER,
        )

    async def build_ticket(
        self,
        target_date: date,
        num_games: int,
        target_odds: float | None = None,
        preferred_markets: list[str] | None = None,
        min_confidence: int = 60,
        bankroll: float = 1000.0,
        upcoming_fixture_ids: set[int] | None = None,
    ) -> dict:
        """
        Assemble the optimal ticket given user constraints.

        Algorithm:
        1. Get all value bets for the date
        2. Filter by preferred_markets if specified
        3. Filter by min_confidence
        4. One bet per fixture (pick best edge per fixture)
        5. If target_odds: combinatorial optimization
        6. Else: rank by confidence * edge, pick top N
        7. Calculate combined odds, probability, Kelly stake
        """
        # Get candidates
        candidates = await self.engine.get_value_bets_for_date(target_date)

        # Filter to upcoming fixtures only (when provided by chat layer)
        if upcoming_fixture_ids is not None:
            candidates = [c for c in candidates if c["fixture_id"] in upcoming_fixture_ids]

        if preferred_markets:
            candidates = [c for c in candidates if c["market"] in preferred_markets]

        candidates = [c for c in candidates if c["confidence_score"] >= min_confidence]

        # One bet per fixture (pick best edge per fixture)
        best_per_fixture: dict[int, dict] = {}
        for c in candidates:
            fid = c["fixture_id"]
            if fid not in best_per_fixture or c["edge"] > best_per_fixture[fid]["edge"]:
                best_per_fixture[fid] = c

        candidates = list(best_per_fixture.values())

        if len(candidates) < num_games:
            return {
                "error": f"Only {len(candidates)} qualifying bets found, need {num_games}",
                "available": len(candidates),
            }

        if target_odds:
            selected = self._optimize_for_target_odds(candidates, num_games, target_odds)
        else:
            candidates.sort(
                key=lambda x: x["confidence_score"] * x["edge"], reverse=True
            )
            selected = candidates[:num_games]

        # Calculate ticket metrics
        combined_odds = 1.0
        combined_prob = 1.0
        legs = []
        for leg in selected:
            combined_odds *= leg["best_odd"]
            combined_prob *= leg["blended_probability"]
            legs.append({
                "blended_probability": leg["blended_probability"],
                "best_odd": leg["best_odd"],
            })

        # Correlation discount
        if num_games > 1:
            combined_prob *= 0.95 ** (num_games - 1)

        kelly_stake = self.bankroll_mgr.calc_accumulator_stake(legs, bankroll)

        # Build game list for storage
        games = []
        for s in selected:
            games.append({
                "fixture_id": s["fixture_id"],
                "home_team": s["home_team"],
                "away_team": s["away_team"],
                "market": s["market"],
                "selection": s["selection"],
                "odd": s["best_odd"],
                "bookmaker": s["best_bookmaker"],
                "probability": s["blended_probability"],
                "edge": s["edge"],
                "confidence": s["confidence_score"],
            })

        # Save ticket to DB
        ticket = Ticket(
            games=games,
            num_games=num_games,
            combined_odds=round(combined_odds, 2),
            combined_probability=round(combined_prob, 4),
            kelly_stake=kelly_stake,
            target_odds=target_odds,
            status="pending",
        )

        async with self.session_factory() as session:
            session.add(ticket)
            await session.commit()
            await session.refresh(ticket)
            ticket_id = str(ticket.id)

        return {
            "ticket_id": ticket_id,
            "games": games,
            "num_games": num_games,
            "combined_odds": round(combined_odds, 2),
            "combined_probability": round(combined_prob, 4),
            "combined_probability_pct": round(combined_prob * 100, 1),
            "kelly_stake": kelly_stake,
            "kelly_stake_pct": round(kelly_stake / bankroll * 100, 1) if bankroll > 0 else 0,
            "target_odds": target_odds,
        }

    async def swap_game(
        self,
        ticket_id: str,
        fixture_id_to_remove: int,
        target_date: date,
        preference: str = "safer",
        upcoming_fixture_ids: set[int] | None = None,
    ) -> dict:
        """Swap a game in an existing ticket."""
        async with self.session_factory() as session:
            ticket = await session.get(Ticket, uuid.UUID(ticket_id))
            if not ticket:
                return {"error": "Ticket not found"}

            games = list(ticket.games)
            removed = None
            remaining = []
            for g in games:
                if g["fixture_id"] == fixture_id_to_remove:
                    removed = g
                else:
                    remaining.append(g)

            if not removed:
                return {"error": f"Fixture {fixture_id_to_remove} not in ticket"}

            # Get replacement candidates
            value_bets = await self.engine.get_value_bets_for_date(target_date)

            # Filter to upcoming fixtures only (when provided by chat layer)
            if upcoming_fixture_ids is not None:
                value_bets = [v for v in value_bets if v["fixture_id"] in upcoming_fixture_ids]

            existing_fixtures = {g["fixture_id"] for g in remaining}
            replacements = [
                v for v in value_bets
                if v["fixture_id"] not in existing_fixtures
                and v["confidence_score"] >= settings.MIN_CONFIDENCE
            ]

            if not replacements:
                return {"error": "No replacement bets available"}

            if preference == "safer":
                replacements.sort(key=lambda x: x["blended_probability"], reverse=True)
            else:  # "riskier" or default
                replacements.sort(key=lambda x: x["best_odd"], reverse=True)

            replacement = replacements[0]
            new_game = {
                "fixture_id": replacement["fixture_id"],
                "home_team": replacement["home_team"],
                "away_team": replacement["away_team"],
                "market": replacement["market"],
                "selection": replacement["selection"],
                "odd": replacement["best_odd"],
                "bookmaker": replacement["best_bookmaker"],
                "probability": replacement["blended_probability"],
                "edge": replacement["edge"],
                "confidence": replacement["confidence_score"],
            }
            remaining.append(new_game)

            # Recalculate ticket metrics
            combined_odds = 1.0
            combined_prob = 1.0
            legs = []
            for g in remaining:
                combined_odds *= g["odd"]
                combined_prob *= g["probability"]
                legs.append({
                    "blended_probability": g["probability"],
                    "best_odd": g["odd"],
                })

            if len(remaining) > 1:
                combined_prob *= 0.95 ** (len(remaining) - 1)

            ticket.games = remaining
            ticket.combined_odds = round(combined_odds, 2)
            ticket.combined_probability = round(combined_prob, 4)
            ticket.kelly_stake = self.bankroll_mgr.calc_accumulator_stake(legs, 1000.0)

            await session.commit()

            return {
                "ticket_id": ticket_id,
                "games": remaining,
                "num_games": len(remaining),
                "combined_odds": round(combined_odds, 2),
                "combined_probability": round(combined_prob, 4),
                "swapped_out": removed,
                "swapped_in": new_game,
            }

    def _optimize_for_target_odds(
        self, candidates: list[dict], n: int, target: float
    ) -> list[dict]:
        """
        Find the n-combination whose product of odds is closest to target,
        breaking ties by highest combined probability.
        """
        if len(candidates) <= 50:
            best_combo = None
            best_score = float("inf")
            for combo in combinations(candidates, n):
                odds_product = 1.0
                prob_product = 1.0
                for leg in combo:
                    odds_product *= leg["best_odd"]
                    prob_product *= leg["blended_probability"]

                distance = abs(odds_product - target)
                score = distance - prob_product * 0.1
                if score < best_score:
                    best_score = score
                    best_combo = combo
            return list(best_combo) if best_combo else candidates[:n]
        else:
            # Greedy for larger pools
            candidates_sorted = sorted(candidates, key=lambda x: x["best_odd"])
            selected = []
            remaining_target = target
            for c in candidates_sorted:
                if len(selected) >= n:
                    break
                remaining_slots = n - len(selected)
                if remaining_slots > 0:
                    avg_needed = remaining_target ** (1 / remaining_slots)
                    if c["best_odd"] <= avg_needed * 1.2:
                        selected.append(c)
                        remaining_target /= c["best_odd"]

            # Fill remaining if needed
            if len(selected) < n:
                remaining = [c for c in candidates_sorted if c not in selected]
                selected.extend(remaining[: n - len(selected)])

            return selected[:n]
