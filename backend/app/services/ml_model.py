"""XGBoost ML model.

Feature engineering (32-feature vector) and prediction using trained
XGBoost models for ou15, ou25, and ou35 markets.
"""

import logging
import os
from datetime import date
from pathlib import Path

import numpy as np
from scipy.stats import poisson
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.fixture import Fixture
from app.models.head_to_head import HeadToHead
from app.models.injury import Injury
from app.models.standing import Standing
from app.models.team_last20 import TeamLast20

logger = logging.getLogger(__name__)

MODEL_DIR = Path(os.environ.get(
    "MODEL_DIR",
    str(Path(__file__).resolve().parent.parent.parent.parent / "ml" / "models"),
))

# Position weights for injury impact
_POSITION_WEIGHTS = {
    "Goalkeeper": 0.15,
    "Defender": 0.10,
    "Midfielder": 0.08,
    "Attacker": 0.12,
}

FEATURE_NAMES = [
    "home_goals_avg",          # 1
    "away_goals_avg",          # 2
    "home_conceded_avg",       # 3
    "away_conceded_avg",       # 4
    "home_xg_avg",             # 5
    "away_xg_avg",             # 6
    "home_xga_avg",            # 7
    "away_xga_avg",            # 8
    "home_sot_avg",            # 9
    "away_sot_avg",            # 10
    "home_possession_avg",     # 11
    "away_possession_avg",     # 12
    "home_form_pts",           # 13
    "away_form_pts",           # 14
    "home_clean_sheet_rate",   # 15
    "away_clean_sheet_rate",   # 16
    "home_btts_rate",          # 17
    "away_btts_rate",          # 18
    "home_o25_rate",           # 19
    "away_o25_rate",           # 20
    "position_diff",           # 21
    "points_gap",              # 22
    "h2h_home_wins",           # 23
    "h2h_draws",               # 24
    "h2h_away_wins",           # 25
    "h2h_avg_goals",           # 26
    "home_injury_impact",      # 27
    "away_injury_impact",      # 28
    "home_advantage",          # 29
    "poisson_home",            # 30
    "poisson_draw",            # 31
    "poisson_away",            # 32
]

# Default league averages when no data available
_DEFAULT_LEAGUE_STATS = {
    "avg_goals_per_game": 2.70,
    "avg_home_goals": 1.50,
    "avg_away_goals": 1.20,
    "home_win_rate": 0.46,
    "total_games": 0,
}


class MLPredictor:
    """XGBoost-based match outcome predictor."""

    def __init__(self, session_factory: async_sessionmaker):
        self.session_factory = session_factory
        self._models: dict = {}
        # Cache for league averages (league_id, season) -> dict
        self._league_avg_cache: dict[tuple[int, int], dict] = {}
        # Cache for standings (league_id, season) -> list[Standing]
        self._standings_cache: dict[tuple[int, int], list] = {}

    def load_models(self):
        """Load trained XGBoost models from disk."""
        import xgboost as xgb

        for market in ["ou15", "ou25", "ou35"]:
            path = MODEL_DIR / f"{market}_model.json"
            if path.exists():
                model = xgb.XGBClassifier()
                model.load_model(str(path))
                self._models[market] = model
                logger.info("Loaded model %s", path.name)
            else:
                logger.warning("Model file not found: %s", path)

    def is_ready(self) -> bool:
        return len(self._models) > 0

    def clear_cache(self):
        """Clear league averages and standings cache."""
        self._league_avg_cache.clear()
        self._standings_cache.clear()

    # ── Feature vector construction (DEPRECATED — use feature_engineering.compute_feature_vector) ──

    async def build_feature_vector(
        self,
        session: AsyncSession,
        fixture: Fixture,
        before_date: date | None = None,
    ) -> np.ndarray:
        """
        Build the 32-feature vector for a single fixture.

        If before_date is provided, only use team_last20 games played
        BEFORE that date (critical for training to prevent data leakage).
        Computes Poisson 1x2 probabilities inline (no extra session).
        """
        cutoff = before_date or fixture.date

        # Load team last-20 games (only games before cutoff)
        home_games = await self._get_team_games(session, fixture.home_team_id, cutoff)
        away_games = await self._get_team_games(session, fixture.away_team_id, cutoff)

        # H2H records (before cutoff)
        h2h = await self._get_h2h(
            session, fixture.home_team_id, fixture.away_team_id, cutoff
        )

        # Standings (cached)
        standings = await self._get_standings_cached(
            session, fixture.league_id, fixture.season
        )

        # Injuries (for this fixture)
        home_injuries = await self._get_injuries(
            session, fixture.id, fixture.home_team_id
        )
        away_injuries = await self._get_injuries(
            session, fixture.id, fixture.away_team_id
        )

        # Poisson 1x2 computed inline (no separate session)
        league_stats = await self._get_league_avg_cached(
            session, fixture.league_id, fixture.season
        )
        p_home, p_draw, p_away, home_adv = self._compute_poisson_1x2(
            home_games, away_games, league_stats
        )

        features = [
            # 1-2: Goals scored avg (weighted by recency)
            self._weighted_avg(home_games, "goals_for"),
            self._weighted_avg(away_games, "goals_for"),
            # 3-4: Goals conceded avg
            self._weighted_avg(home_games, "goals_against"),
            self._weighted_avg(away_games, "goals_against"),
            # 5-6: xG avg (fallback to goals_for)
            self._weighted_avg(home_games, "xg_for", fallback="goals_for"),
            self._weighted_avg(away_games, "xg_for", fallback="goals_for"),
            # 7-8: xGA avg (fallback to goals_against)
            self._weighted_avg(home_games, "xg_against", fallback="goals_against"),
            self._weighted_avg(away_games, "xg_against", fallback="goals_against"),
            # 9-10: Shots on target avg
            self._weighted_avg(home_games, "shots_on_target"),
            self._weighted_avg(away_games, "shots_on_target"),
            # 11-12: Possession avg
            self._weighted_avg(home_games, "possession"),
            self._weighted_avg(away_games, "possession"),
            # 13-14: Form points (last 5 games, W=3, D=1, L=0)
            self._calc_form_points(home_games[:5]),
            self._calc_form_points(away_games[:5]),
            # 15-16: Clean sheet rate
            self._calc_rate(home_games, lambda g: g.goals_against == 0),
            self._calc_rate(away_games, lambda g: g.goals_against == 0),
            # 17-18: BTTS rate
            self._calc_rate(home_games, lambda g: g.goals_for > 0 and g.goals_against > 0),
            self._calc_rate(away_games, lambda g: g.goals_for > 0 and g.goals_against > 0),
            # 19-20: Over 2.5 rate
            self._calc_rate(home_games, lambda g: g.goals_for + g.goals_against > 2),
            self._calc_rate(away_games, lambda g: g.goals_for + g.goals_against > 2),
            # 21-22: League position diff, points gap
            self._get_position_diff(standings, fixture.home_team_id, fixture.away_team_id),
            self._get_points_gap(standings, fixture.home_team_id, fixture.away_team_id),
            # 23-25: H2H record (last 10)
            self._h2h_wins(h2h, fixture.home_team_id),
            self._h2h_draws(h2h),
            self._h2h_wins(h2h, fixture.away_team_id),
            # 26: H2H avg total goals
            self._h2h_avg_goals(h2h),
            # 27-28: Injury impact
            self.calc_injury_impact(home_injuries),
            self.calc_injury_impact(away_injuries),
            # 29: Home advantage factor
            home_adv,
            # 30-32: Poisson model outputs
            p_home,
            p_draw,
            p_away,
        ]

        return np.array(features, dtype=np.float32)

    # ── Inline Poisson computation ─────────────────────────────

    def _compute_poisson_1x2(
        self,
        home_games: list[TeamLast20],
        away_games: list[TeamLast20],
        league_stats: dict,
    ) -> tuple[float, float, float, float]:
        """
        Compute Poisson 1x2 probabilities inline using pre-loaded data.
        Returns (p_home, p_draw, p_away, home_advantage).
        """
        avg_per_team = league_stats["avg_goals_per_game"] / 2
        if avg_per_team <= 0:
            avg_per_team = 1.35

        # Split home games by venue
        home_venue = [g for g in home_games if g.venue == "H"]
        away_venue = [g for g in away_games if g.venue == "A"]

        # Attack/defense strengths
        home_attack = self._calc_strength(home_venue, home_games, "goals_for", "xg_for", avg_per_team)
        home_defense = self._calc_strength(home_venue, home_games, "goals_against", "xg_against", avg_per_team)
        away_attack = self._calc_strength(away_venue, away_games, "goals_for", "xg_for", avg_per_team)
        away_defense = self._calc_strength(away_venue, away_games, "goals_against", "xg_against", avg_per_team)

        # Home advantage
        avg_home = league_stats["avg_home_goals"]
        avg_away = league_stats["avg_away_goals"]
        if avg_away > 0:
            home_adv = float(np.clip(avg_home / avg_away, 1.05, 1.45))
        else:
            home_adv = 1.25

        # Lambdas
        lambda_home = float(np.clip(home_attack * away_defense * avg_per_team * home_adv, 0.2, 4.5))
        lambda_away = float(np.clip(away_attack * home_defense * avg_per_team, 0.2, 4.5))

        # 7x7 matrix → 1x2
        max_goals = 7
        p_home = p_draw = p_away = 0.0
        for i in range(max_goals):
            pi = poisson.pmf(i, lambda_home)
            for j in range(max_goals):
                pj = poisson.pmf(j, lambda_away)
                p = pi * pj
                if i > j:
                    p_home += p
                elif i == j:
                    p_draw += p
                else:
                    p_away += p

        return p_home, p_draw, p_away, home_adv

    def _calc_strength(
        self,
        venue_games: list[TeamLast20],
        all_games: list[TeamLast20],
        goals_field: str,
        xg_field: str,
        league_avg_per_team: float,
        venue_weight: float = 0.7,
    ) -> float:
        """Calculate attack or defense strength ratio."""
        venue_avg = self._xg_weighted_avg(venue_games, goals_field, xg_field)
        overall_avg = self._xg_weighted_avg(all_games, goals_field, xg_field)

        if venue_avg is not None and overall_avg is not None:
            blended = venue_weight * venue_avg + (1 - venue_weight) * overall_avg
        elif overall_avg is not None:
            blended = overall_avg
        elif venue_avg is not None:
            blended = venue_avg
        else:
            return 1.0

        if league_avg_per_team <= 0:
            return 1.0
        return blended / league_avg_per_team

    @staticmethod
    def _xg_weighted_avg(
        games: list[TeamLast20], goals_field: str, xg_field: str
    ) -> float | None:
        """60/40 xG blend with form_weight recency."""
        if not games:
            return None
        total_weight = 0.0
        total_value = 0.0
        for g in games:
            actual = getattr(g, goals_field) or 0
            xg = getattr(g, xg_field)
            effective = (0.6 * actual + 0.4 * xg) if xg is not None else float(actual)
            w = g.form_weight
            total_weight += w
            total_value += effective * w
        if total_weight == 0:
            return None
        return total_value / total_weight

    # ── Data loading helpers ───────────────────────────────────

    async def _get_team_games(
        self, session: AsyncSession, team_id: int, before_date: date
    ) -> list[TeamLast20]:
        """Load team_last20 rows played BEFORE the given date."""
        q = (
            select(TeamLast20)
            .where(TeamLast20.team_id == team_id, TeamLast20.date < before_date)
            .order_by(TeamLast20.date.desc())
            .limit(20)
        )
        result = await session.execute(q)
        return list(result.scalars().all())

    async def _get_h2h(
        self,
        session: AsyncSession,
        home_id: int,
        away_id: int,
        before_date: date,
    ) -> list[HeadToHead]:
        """Load H2H records before cutoff, last 10."""
        t1, t2 = min(home_id, away_id), max(home_id, away_id)
        q = (
            select(HeadToHead)
            .where(
                HeadToHead.team1_id == t1,
                HeadToHead.team2_id == t2,
                HeadToHead.date < before_date,
            )
            .order_by(HeadToHead.date.desc())
            .limit(10)
        )
        result = await session.execute(q)
        return list(result.scalars().all())

    async def _get_standings_cached(
        self, session: AsyncSession, league_id: int, season: int
    ) -> list[Standing]:
        """Get standings with caching."""
        key = (league_id, season)
        if key in self._standings_cache:
            return self._standings_cache[key]
        q = select(Standing).where(
            Standing.league_id == league_id, Standing.season == season
        )
        result = await session.execute(q)
        standings = list(result.scalars().all())
        self._standings_cache[key] = standings
        return standings

    async def _get_league_avg_cached(
        self, session: AsyncSession, league_id: int, season: int
    ) -> dict:
        """Get league averages with caching."""
        key = (league_id, season)
        if key in self._league_avg_cache:
            return self._league_avg_cache[key]

        standings = await self._get_standings_cached(session, league_id, season)
        if standings:
            total_home_played = sum(s.home_played for s in standings)
            if total_home_played > 0:
                total_home_gf = sum(s.home_gf for s in standings)
                total_away_gf = sum(s.away_gf for s in standings)
                total_home_won = sum(s.home_won for s in standings)
                avg_home = total_home_gf / total_home_played
                avg_away = total_away_gf / total_home_played
                stats = {
                    "avg_goals_per_game": round(avg_home + avg_away, 4),
                    "avg_home_goals": round(avg_home, 4),
                    "avg_away_goals": round(avg_away, 4),
                    "home_win_rate": round(total_home_won / total_home_played, 4),
                    "total_games": total_home_played,
                }
                self._league_avg_cache[key] = stats
                return stats

        stats = dict(_DEFAULT_LEAGUE_STATS)
        self._league_avg_cache[key] = stats
        return stats

    async def _get_injuries(
        self, session: AsyncSession, fixture_id: int, team_id: int
    ) -> list[Injury]:
        q = select(Injury).where(
            Injury.fixture_id == fixture_id, Injury.team_id == team_id
        )
        result = await session.execute(q)
        return list(result.scalars().all())

    # ── Feature calculation helpers ────────────────────────────

    @staticmethod
    def _weighted_avg(
        games: list[TeamLast20],
        field: str,
        fallback: str | None = None,
    ) -> float:
        """Recency-weighted average of a field, with optional fallback.

        Returns NaN when all values are missing so XGBoost can learn
        optimal split directions for missing data (better than 0.0).
        """
        if not games:
            return float('nan')

        total_weight = 0.0
        total_value = 0.0
        has_value = False
        for g in games:
            val = getattr(g, field, None)
            if val is None and fallback:
                val = getattr(g, fallback, None)
            if val is None:
                continue
            has_value = True
            total_weight += g.form_weight
            total_value += float(val) * g.form_weight

        if not has_value or total_weight == 0:
            return float('nan')
        return total_value / total_weight

    @staticmethod
    def _calc_form_points(games: list[TeamLast20]) -> float:
        """Form points from last N games. W=3, D=1, L=0. Normalized to 0-1."""
        if not games:
            return 0.0
        pts = sum(3 if g.result == "W" else (1 if g.result == "D" else 0) for g in games)
        return pts / (3 * len(games))  # normalize to [0, 1]

    @staticmethod
    def _calc_rate(games: list[TeamLast20], condition) -> float:
        """Rate of games matching a condition."""
        if not games:
            return 0.0
        return sum(1 for g in games if condition(g)) / len(games)

    @staticmethod
    def _get_position_diff(
        standings: list[Standing], home_id: int, away_id: int
    ) -> float:
        """Position difference (positive = home team ranked higher)."""
        home_pos = away_pos = 10  # default middle
        for s in standings:
            if s.team_id == home_id:
                home_pos = s.rank
            elif s.team_id == away_id:
                away_pos = s.rank
        return float(away_pos - home_pos)

    @staticmethod
    def _get_points_gap(
        standings: list[Standing], home_id: int, away_id: int
    ) -> float:
        """Absolute points gap between the two teams."""
        home_pts = away_pts = 0
        for s in standings:
            if s.team_id == home_id:
                home_pts = s.points
            elif s.team_id == away_id:
                away_pts = s.points
        return float(abs(home_pts - away_pts))

    @staticmethod
    def _h2h_wins(h2h: list[HeadToHead], team_id: int) -> float:
        """Number of H2H wins for a team (as fraction of matches)."""
        if not h2h:
            return 0.0
        wins = 0
        for m in h2h:
            if m.winner == "home" and m.home_team_id == team_id:
                wins += 1
            elif m.winner == "away" and m.home_team_id != team_id:
                wins += 1
        return wins / len(h2h)

    @staticmethod
    def _h2h_draws(h2h: list[HeadToHead]) -> float:
        """Draw rate in H2H matches."""
        if not h2h:
            return 0.0
        return sum(1 for m in h2h if m.winner == "draw") / len(h2h)

    @staticmethod
    def _h2h_avg_goals(h2h: list[HeadToHead]) -> float:
        """Average total goals in H2H matches."""
        if not h2h:
            return 2.5  # default league average
        return sum(m.total_goals for m in h2h) / len(h2h)

    @staticmethod
    def calc_injury_impact(injuries: list[Injury]) -> float:
        """
        Weight missing players by position importance.
        GK=0.15, DEF=0.10, MID=0.08, FWD=0.12 per player.
        Cap at 0.50.
        """
        if not injuries:
            return 0.0
        total = len(injuries) * 0.08  # average weight per unknown-position player
        return min(total, 0.50)

    # ── Label extraction from completed fixtures ───────────────

    @staticmethod
    def get_labels(fixture: Fixture) -> dict:
        """
        Extract actual outcome labels from a completed fixture.
        Returns dict with keys: ou15, ou25, ou35
        """
        h = fixture.score_home_ft or 0
        a = fixture.score_away_ft or 0
        total = h + a
        return {
            "ou15": 1 if total > 1 else 0,
            "ou25": 1 if total > 2 else 0,
            "ou35": 1 if total > 3 else 0,
        }
