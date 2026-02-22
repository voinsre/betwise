"""Poisson distribution prediction model — Phase 3.

Calculates match outcome probabilities across 7 markets using a
bivariate Poisson model with recency-weighted team form data.
"""

import logging

import numpy as np
from scipy.stats import poisson
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.fixture import Fixture
from app.models.standing import Standing
from app.models.team_last20 import TeamLast20

logger = logging.getLogger(__name__)

# Defaults when no league data is available
_DEFAULT_LEAGUE_STATS = {
    "avg_goals_per_game": 2.70,
    "avg_home_goals": 1.50,
    "avg_away_goals": 1.20,
    "home_win_rate": 0.46,
    "total_games": 0,
}


class PoissonPredictor:
    """Poisson-based match outcome predictor."""

    def __init__(self, session_factory: async_sessionmaker):
        self.session_factory = session_factory

    # ── Main entry ────────────────────────────────────────────

    async def predict(self, fixture_id: int) -> dict:
        """
        Main entry point. Returns lambdas, probability matrix,
        and probabilities for all 7 markets.
        """
        async with self.session_factory() as session:
            fixture = await session.get(Fixture, fixture_id)
            if not fixture:
                raise ValueError(f"Fixture {fixture_id} not found")

            # Load team last-20 data (venue-filtered and overall)
            home_venue = await self._get_team_games(session, fixture.home_team_id, venue="H")
            home_all = await self._get_team_games(session, fixture.home_team_id)
            away_venue = await self._get_team_games(session, fixture.away_team_id, venue="A")
            away_all = await self._get_team_games(session, fixture.away_team_id)

            # League averages for normalisation
            league_stats = await self.get_league_averages(
                session, fixture.league_id, fixture.season
            )

        # ── Calculate attack / defense strengths ──────────────
        home_attack = self._calc_attack_strength(home_venue, home_all, league_stats)
        home_defense = self._calc_defense_weakness(home_venue, home_all, league_stats)
        away_attack = self._calc_attack_strength(away_venue, away_all, league_stats)
        away_defense = self._calc_defense_weakness(away_venue, away_all, league_stats)

        # ── Home advantage ────────────────────────────────────
        home_advantage = self._calc_home_advantage(league_stats)

        # ── Expected goals (lambdas) ──────────────────────────
        avg_per_team = league_stats["avg_goals_per_game"] / 2
        lambda_home = home_attack * away_defense * avg_per_team * home_advantage
        lambda_away = away_attack * home_defense * avg_per_team

        # Clamp to reasonable range
        lambda_home = float(np.clip(lambda_home, 0.2, 4.5))
        lambda_away = float(np.clip(lambda_away, 0.2, 4.5))

        # ── 7×7 probability matrix ────────────────────────────
        matrix = self._build_matrix(lambda_home, lambda_away)

        # ── Derive all markets ────────────────────────────────
        return {
            "fixture_id": fixture_id,
            "home_team_id": fixture.home_team_id,
            "away_team_id": fixture.away_team_id,
            "league_id": fixture.league_id,
            "season": fixture.season,
            "lambda_home": round(lambda_home, 4),
            "lambda_away": round(lambda_away, 4),
            "home_attack": round(home_attack, 4),
            "home_defense": round(home_defense, 4),
            "away_attack": round(away_attack, 4),
            "away_defense": round(away_defense, 4),
            "home_advantage": round(home_advantage, 4),
            "league_avg_goals": league_stats["avg_goals_per_game"],
            "matrix": matrix,
            "markets": {
                "1x2": self._calc_1x2(matrix),
                "ou25": self._calc_over_under(matrix, 2.5),
                "btts": self._calc_btts(matrix),
                "dc": self._calc_double_chance(matrix),
                "htft": self._calc_htft(lambda_home, lambda_away),
                "combo": self._calc_best_combos(matrix, lambda_home, lambda_away),
            },
        }

    # ── Data loading ──────────────────────────────────────────

    async def _get_team_games(
        self, session: AsyncSession, team_id: int, venue: str | None = None
    ) -> list[TeamLast20]:
        """Load team_last20 rows, optionally filtered by venue (H/A)."""
        q = select(TeamLast20).where(TeamLast20.team_id == team_id)
        if venue:
            q = q.where(TeamLast20.venue == venue)
        q = q.order_by(TeamLast20.date.desc())
        result = await session.execute(q)
        return list(result.scalars().all())

    async def get_league_averages(
        self, session: AsyncSession, league_id: int, season: int
    ) -> dict:
        """
        Compute league averages from standings (preferred) or completed fixtures.

        Returns dict with: avg_goals_per_game, avg_home_goals, avg_away_goals,
        home_win_rate, total_games.
        """
        # ── Try standings first (full season aggregates) ──────
        result = await session.execute(
            select(Standing).where(
                Standing.league_id == league_id,
                Standing.season == season,
            )
        )
        standings = result.scalars().all()

        if standings:
            total_home_played = sum(s.home_played for s in standings)
            if total_home_played > 0:
                total_home_gf = sum(s.home_gf for s in standings)
                total_away_gf = sum(s.away_gf for s in standings)
                total_home_won = sum(s.home_won for s in standings)

                avg_home = total_home_gf / total_home_played
                avg_away = total_away_gf / total_home_played

                return {
                    "avg_goals_per_game": round(avg_home + avg_away, 4),
                    "avg_home_goals": round(avg_home, 4),
                    "avg_away_goals": round(avg_away, 4),
                    "home_win_rate": round(total_home_won / total_home_played, 4),
                    "total_games": total_home_played,
                }

        # ── Fallback: compute from completed fixtures ─────────
        result = await session.execute(
            select(
                func.count(Fixture.id),
                func.sum(Fixture.score_home_ft),
                func.sum(Fixture.score_away_ft),
            ).where(
                Fixture.league_id == league_id,
                Fixture.season == season,
                Fixture.status == "FT",
                Fixture.score_home_ft.isnot(None),
                Fixture.score_away_ft.isnot(None),
            )
        )
        row = result.one()
        total_games = row[0] or 0

        if total_games >= 10:
            total_home = row[1] or 0
            total_away = row[2] or 0
            avg_home = total_home / total_games
            avg_away = total_away / total_games

            hw_result = await session.execute(
                select(func.count(Fixture.id)).where(
                    Fixture.league_id == league_id,
                    Fixture.season == season,
                    Fixture.status == "FT",
                    Fixture.score_home_ft > Fixture.score_away_ft,
                )
            )
            home_wins = hw_result.scalar() or 0

            return {
                "avg_goals_per_game": round(avg_home + avg_away, 4),
                "avg_home_goals": round(avg_home, 4),
                "avg_away_goals": round(avg_away, 4),
                "home_win_rate": round(home_wins / total_games, 4),
                "total_games": total_games,
            }

        logger.warning(
            "No sufficient data for league %d season %d, using defaults",
            league_id,
            season,
        )
        return dict(_DEFAULT_LEAGUE_STATS)

    # ── Strength calculations ─────────────────────────────────

    def _weighted_avg_goals(
        self, games: list[TeamLast20], goals_field: str, xg_field: str
    ) -> float | None:
        """
        Compute recency-weighted average with xG blend.
        60% actual goals + 40% xG where available, else 100% actual goals.
        """
        if not games:
            return None

        total_weight = 0.0
        total_value = 0.0

        for g in games:
            actual = getattr(g, goals_field) or 0
            xg = getattr(g, xg_field)

            if xg is not None:
                effective = 0.6 * actual + 0.4 * xg
            else:
                effective = float(actual)

            w = g.form_weight
            total_weight += w
            total_value += effective * w

        if total_weight == 0:
            return None
        return total_value / total_weight

    def _calc_attack_strength(
        self,
        venue_games: list[TeamLast20],
        all_games: list[TeamLast20],
        league_stats: dict,
        venue_weight: float = 0.7,
    ) -> float:
        """
        Weighted attack strength ratio.
        70% venue-specific + 30% overall.
        > 1.0 means team scores more than league average.
        """
        venue_avg = self._weighted_avg_goals(venue_games, "goals_for", "xg_for")
        overall_avg = self._weighted_avg_goals(all_games, "goals_for", "xg_for")

        if venue_avg is not None and overall_avg is not None:
            blended = venue_weight * venue_avg + (1 - venue_weight) * overall_avg
        elif overall_avg is not None:
            blended = overall_avg
        elif venue_avg is not None:
            blended = venue_avg
        else:
            return 1.0  # no data → assume average

        league_avg_per_team = league_stats["avg_goals_per_game"] / 2
        if league_avg_per_team <= 0:
            return 1.0

        return blended / league_avg_per_team

    def _calc_defense_weakness(
        self,
        venue_games: list[TeamLast20],
        all_games: list[TeamLast20],
        league_stats: dict,
        venue_weight: float = 0.7,
    ) -> float:
        """
        Weighted defense weakness ratio.
        70% venue-specific + 30% overall.
        > 1.0 means team concedes more than league average (weaker defense).
        """
        venue_avg = self._weighted_avg_goals(venue_games, "goals_against", "xg_against")
        overall_avg = self._weighted_avg_goals(all_games, "goals_against", "xg_against")

        if venue_avg is not None and overall_avg is not None:
            blended = venue_weight * venue_avg + (1 - venue_weight) * overall_avg
        elif overall_avg is not None:
            blended = overall_avg
        elif venue_avg is not None:
            blended = venue_avg
        else:
            return 1.0

        league_avg_per_team = league_stats["avg_goals_per_game"] / 2
        if league_avg_per_team <= 0:
            return 1.0

        return blended / league_avg_per_team

    def _calc_home_advantage(self, league_stats: dict) -> float:
        """
        League-specific home advantage multiplier from goals ratio.
        Typically 1.15–1.35 for major European leagues.
        Clamped to [1.05, 1.45].
        """
        avg_home = league_stats["avg_home_goals"]
        avg_away = league_stats["avg_away_goals"]

        if avg_away > 0:
            ha = avg_home / avg_away
        else:
            ha = 1.25  # default

        return float(np.clip(ha, 1.05, 1.45))

    # ── Probability matrix ────────────────────────────────────

    @staticmethod
    def _build_matrix(lambda_home: float, lambda_away: float, max_goals: int = 7) -> np.ndarray:
        """Build bivariate Poisson probability matrix.  matrix[i][j] = P(home=i, away=j)."""
        matrix = np.zeros((max_goals, max_goals))
        for i in range(max_goals):
            for j in range(max_goals):
                matrix[i][j] = poisson.pmf(i, lambda_home) * poisson.pmf(j, lambda_away)
        return matrix

    # ── Market derivations from matrix ────────────────────────

    @staticmethod
    def _calc_1x2(matrix: np.ndarray) -> dict[str, float]:
        """Home / Draw / Away probabilities."""
        n = matrix.shape[0]
        home_win = sum(matrix[i][j] for i in range(n) for j in range(n) if i > j)
        draw = sum(matrix[i][i] for i in range(n))
        away_win = sum(matrix[i][j] for i in range(n) for j in range(n) if i < j)
        return {
            "Home": round(float(home_win), 6),
            "Draw": round(float(draw), 6),
            "Away": round(float(away_win), 6),
        }

    @staticmethod
    def _calc_over_under(matrix: np.ndarray, line: float = 2.5) -> dict[str, float]:
        """Over/Under goal line probabilities."""
        n = matrix.shape[0]
        under = sum(
            matrix[i][j] for i in range(n) for j in range(n) if (i + j) <= int(line)
        )
        over = 1.0 - under
        return {
            "Over 2.5": round(float(over), 6),
            "Under 2.5": round(float(under), 6),
        }

    @staticmethod
    def _calc_btts(matrix: np.ndarray) -> dict[str, float]:
        """Both Teams To Score probabilities."""
        n = matrix.shape[0]
        home_zero = sum(matrix[0][j] for j in range(n))
        away_zero = sum(matrix[i][0] for i in range(n))
        both_zero = matrix[0][0]
        btts_no = home_zero + away_zero - both_zero
        btts_yes = 1.0 - btts_no
        return {
            "Yes": round(float(btts_yes), 6),
            "No": round(float(btts_no), 6),
        }

    @staticmethod
    def _calc_double_chance(matrix: np.ndarray) -> dict[str, float]:
        """Double chance probabilities (1X, 12, X2)."""
        p = PoissonPredictor._calc_1x2(matrix)
        return {
            "1X": round(p["Home"] + p["Draw"], 6),
            "12": round(p["Home"] + p["Away"], 6),
            "X2": round(p["Draw"] + p["Away"], 6),
        }

    @staticmethod
    def _calc_htft(lambda_home: float, lambda_away: float) -> dict[str, float]:
        """
        Half-time / Full-time probabilities via dual Poisson.
        Research: ~43% of goals scored in first half, ~57% second half.
        """
        lh_ht = lambda_home * 0.43
        la_ht = lambda_away * 0.43
        lh_2h = lambda_home * 0.57
        la_2h = lambda_away * 0.57

        results = {}
        for ht_label, ht_cond in [("1", "home"), ("X", "draw"), ("2", "away")]:
            for ft_label, ft_cond in [("1", "home"), ("X", "draw"), ("2", "away")]:
                prob = PoissonPredictor._calc_htft_joint(
                    lh_ht, la_ht, lh_2h, la_2h, ht_cond, ft_cond
                )
                results[f"{ht_label}/{ft_label}"] = round(prob, 6)
        return results

    @staticmethod
    def _calc_htft_joint(
        lh_ht: float, la_ht: float, lh_2h: float, la_2h: float,
        ht_result: str, ft_result: str,
    ) -> float:
        """P(HT result AND FT result) via independent Poisson per half."""
        max_g = 5  # 0–4 goals per team per half
        total = 0.0
        for h1 in range(max_g):
            for a1 in range(max_g):
                # Check half-time condition
                if ht_result == "home" and h1 <= a1:
                    continue
                if ht_result == "draw" and h1 != a1:
                    continue
                if ht_result == "away" and h1 >= a1:
                    continue

                p_ht = poisson.pmf(h1, lh_ht) * poisson.pmf(a1, la_ht)

                for h2 in range(max_g):
                    for a2 in range(max_g):
                        ft_home = h1 + h2
                        ft_away = a1 + a2
                        # Check full-time condition
                        if ft_result == "home" and ft_home <= ft_away:
                            continue
                        if ft_result == "draw" and ft_home != ft_away:
                            continue
                        if ft_result == "away" and ft_home >= ft_away:
                            continue

                        p_2h = poisson.pmf(h2, lh_2h) * poisson.pmf(a2, la_2h)
                        total += p_ht * p_2h
        return total

    @staticmethod
    def _calc_best_combos(
        matrix: np.ndarray, lambda_home: float, lambda_away: float
    ) -> dict[str, float]:
        """
        Calculate combo bet probabilities (result+goals, result+BTTS, etc.).
        Returns top 5 by probability.
        """
        n = matrix.shape[0]
        combos: dict[str, float] = {}

        # ── Result + Over 2.5 ─────────────────────────────────
        for result, label in [("home", "Home"), ("draw", "Draw"), ("away", "Away")]:
            prob = sum(
                matrix[i][j]
                for i in range(n) for j in range(n)
                if (i + j) > 2
                and (
                    (result == "home" and i > j)
                    or (result == "draw" and i == j)
                    or (result == "away" and i < j)
                )
            )
            combos[f"{label} & Over 2.5"] = prob

        # ── Result + BTTS ─────────────────────────────────────
        for result, label in [("home", "Home"), ("draw", "Draw"), ("away", "Away")]:
            prob = sum(
                matrix[i][j]
                for i in range(n) for j in range(n)
                if i > 0 and j > 0
                and (
                    (result == "home" and i > j)
                    or (result == "draw" and i == j)
                    or (result == "away" and i < j)
                )
            )
            combos[f"{label} & BTTS"] = prob

        # ── Result + 3+ total goals ───────────────────────────
        for result, label in [("home", "Home"), ("draw", "Draw"), ("away", "Away")]:
            prob = sum(
                matrix[i][j]
                for i in range(n) for j in range(n)
                if (i + j) >= 3
                and (
                    (result == "home" and i > j)
                    or (result == "draw" and i == j)
                    or (result == "away" and i < j)
                )
            )
            combos[f"{label} & 3+ Goals"] = prob

        # ── BTTS + Over 2.5 ──────────────────────────────────
        combos["BTTS & Over 2.5"] = sum(
            matrix[i][j]
            for i in range(n) for j in range(n)
            if i > 0 and j > 0 and (i + j) > 2
        )

        # ── Double Chance + Over 1.5 ─────────────────────────
        dc_checks: dict[str, callable] = {
            "1X": lambda i, j: i >= j,
            "X2": lambda i, j: i <= j,
            "12": lambda i, j: i != j,
        }
        for dc, check in dc_checks.items():
            prob = sum(
                matrix[i][j]
                for i in range(n) for j in range(n)
                if check(i, j) and (i + j) > 1
            )
            combos[f"{dc} & Over 1.5"] = prob

        # Sort by probability descending, return top 5
        sorted_combos = dict(
            sorted(combos.items(), key=lambda x: x[1], reverse=True)[:5]
        )
        return {k: round(float(v), 6) for k, v in sorted_combos.items()}
