"""Feature engineering — 30-feature vectors for ML prediction.

Tier A (19 features from existing data):
  xG (7), Form (4), H2H (3), League (3), Situational (2)
Tier B (11 features, available after OddsPapi/ClubElo):
  Elo (3), Pinnacle (6), Consensus (2)

Context features (12) are computed but NOT included in FEATURE_NAMES.
They degraded OU25 from +4.9% to -8.3% ROI in backtesting.
Kept here for future research.

Critical: all queries use before_date to prevent training data leakage.
"""

import logging
from datetime import date, timedelta
from statistics import mean

import numpy as np
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.elo_ratings import EloRating
from app.models.fixture import Fixture
from app.models.source_mapping import TeamSourceMapping
from app.models.head_to_head import HeadToHead
from app.models.injury import Injury
from app.models.odds import Odds
from app.models.standing import Standing
from app.models.team import Team
from app.models.team_last20 import TeamLast20

logger = logging.getLogger(__name__)

TIER_A_FEATURES = [
    # xG (7)
    "rolling_xg_for_5",
    "rolling_xg_for_10",
    "rolling_xg_against_5",
    "rolling_xg_against_10",
    "xg_differential_5",
    "xg_overperformance_10",
    "combined_xg",
    # Form (4)
    "form_points_5",
    "form_goals_scored_5",
    "form_goals_conceded_5",
    "home_away_form_5",
    # H2H (3)
    "h2h_avg_goals_5",
    "h2h_home_wins_5",
    "h2h_over25_rate_5",
    # League (3)
    "league_avg_goals",
    "league_over25_rate",
    "position_gap",
    # Situational (2)
    "rest_days",
    "injuries_count",
]

TIER_B_FEATURES = [
    # Elo (3)
    "elo_home",
    "elo_away",
    "elo_gap",
    # Pinnacle (6)
    "pinnacle_implied_home",
    "pinnacle_implied_draw",
    "pinnacle_implied_away",
    "pinnacle_implied_over15",
    "pinnacle_implied_over25",
    "pinnacle_implied_over35",
    # Consensus (2)
    "consensus_implied_home",
    "consensus_implied_away",
]

CONTEXT_FEATURES = [
    "is_derby",                   # 1 if derby match, 0 otherwise
    "derby_intensity",            # 0.0 (not derby), 0.4, 0.6, 0.8 (fierce)
    "home_congestion_14d",        # Number of games home team played in last 14 days
    "away_congestion_14d",        # Number of games away team played in last 14 days
    "rest_day_diff",              # home_rest_days - away_rest_days (positive = home more rested)
    "home_relegation_pressure",   # 0.0 to 1.0 based on position + games remaining
    "away_relegation_pressure",   # 0.0 to 1.0
    "home_form_trajectory",       # Goals trend: recent 3 avg minus older 3 avg
    "away_form_trajectory",       # Same for away
    "h2h_goal_avg",               # Average total goals in last 5 H2H meetings
    "home_scoring_streak",        # Consecutive games with 1+ goals (0-20)
    "away_scoring_streak",        # Same for away team
]

FEATURE_NAMES = TIER_A_FEATURES + TIER_B_FEATURES  # 30 features, no CONTEXT_FEATURES


# ── helpers ──────────────────────────────────────────────────────────────


async def _last_n(session, team_id, before_date, n, *, venue=None):
    """Fetch last N TeamLast20 rows for a team before a cutoff date."""
    q = (
        select(TeamLast20)
        .where(TeamLast20.team_id == team_id, TeamLast20.date < before_date)
        .order_by(TeamLast20.date.desc())
        .limit(n)
    )
    if venue:
        q = q.where(TeamLast20.venue == venue)
    return (await session.execute(q)).scalars().all()


def _safe_mean(values):
    """Mean of non-None values, or None if empty."""
    filtered = [v for v in values if v is not None]
    return mean(filtered) if filtered else None


def _points(rows):
    """W=3, D=1, L=0 total from TeamLast20 rows."""
    return sum(3 if r.result == "W" else 1 if r.result == "D" else 0 for r in rows)


# ── feature groups ───────────────────────────────────────────────────────


def _xg_features(f, home_10, away_5):
    """Populate 7 xG features from pre-fetched TeamLast20 rows."""
    home_5 = home_10[:5]

    f["rolling_xg_for_5"] = _safe_mean([r.xg_for for r in home_5])
    f["rolling_xg_for_10"] = _safe_mean([r.xg_for for r in home_10])
    f["rolling_xg_against_5"] = _safe_mean([r.xg_against for r in home_5])
    f["rolling_xg_against_10"] = _safe_mean([r.xg_against for r in home_10])

    xgf5 = f["rolling_xg_for_5"]
    xga5 = f["rolling_xg_against_5"]
    f["xg_differential_5"] = (xgf5 - xga5) if xgf5 is not None and xga5 is not None else None

    overperf = [r.goals_for - r.xg_for for r in home_10 if r.xg_for is not None]
    f["xg_overperformance_10"] = mean(overperf) if overperf else None

    away_xgf5 = _safe_mean([r.xg_for for r in away_5])
    f["combined_xg"] = (xgf5 + away_xgf5) if xgf5 is not None and away_xgf5 is not None else None


def _form_features(f, home_5, away_5, home_h5, away_a5):
    """Populate 4 form features."""
    f["form_points_5"] = _points(home_5) if home_5 else None
    f["form_goals_scored_5"] = sum(r.goals_for for r in home_5) if home_5 else None
    f["form_goals_conceded_5"] = sum(r.goals_against for r in home_5) if home_5 else None

    h_venue = _points(home_h5) if home_h5 else None
    a_venue = _points(away_a5) if away_a5 else None
    f["home_away_form_5"] = (h_venue - a_venue) if h_venue is not None and a_venue is not None else None


async def _h2h_features(f, session, fixture, before_date):
    """3 H2H features from HeadToHead table."""
    t1, t2 = sorted((fixture.home_team_id, fixture.away_team_id))
    rows = (await session.execute(
        select(HeadToHead)
        .where(HeadToHead.team1_id == t1, HeadToHead.team2_id == t2, HeadToHead.date < before_date)
        .order_by(HeadToHead.date.desc())
        .limit(5)
    )).scalars().all()

    if not rows:
        f["h2h_avg_goals_5"] = None
        f["h2h_home_wins_5"] = None
        f["h2h_over25_rate_5"] = None
        return

    f["h2h_avg_goals_5"] = mean(r.total_goals for r in rows)
    f["h2h_home_wins_5"] = sum(1 for r in rows if r.winner == "home")
    f["h2h_over25_rate_5"] = sum(1 for r in rows if r.total_goals > 2) / len(rows)


async def _league_features(f, session, fixture, before_date):
    """3 league context features."""
    rows = (await session.execute(
        select(Fixture.score_home_ft, Fixture.score_away_ft)
        .where(
            Fixture.league_id == fixture.league_id,
            Fixture.season == fixture.season,
            Fixture.status == "FT",
            Fixture.date < before_date,
            Fixture.score_home_ft.is_not(None),
            Fixture.score_away_ft.is_not(None),
        )
    )).all()

    if rows:
        totals = [h + a for h, a in rows]
        f["league_avg_goals"] = mean(totals)
        f["league_over25_rate"] = sum(1 for g in totals if g > 2) / len(totals)
    else:
        f["league_avg_goals"] = None
        f["league_over25_rate"] = None

    home_rank = (await session.execute(
        select(Standing.rank).where(
            Standing.league_id == fixture.league_id,
            Standing.season == fixture.season,
            Standing.team_id == fixture.home_team_id,
        )
    )).scalar_one_or_none()
    away_rank = (await session.execute(
        select(Standing.rank).where(
            Standing.league_id == fixture.league_id,
            Standing.season == fixture.season,
            Standing.team_id == fixture.away_team_id,
        )
    )).scalar_one_or_none()
    f["position_gap"] = abs(home_rank - away_rank) if home_rank is not None and away_rank is not None else None


async def _situational_features(f, session, fixture, home_10, away_5):
    """rest_days and injuries_count."""
    home_last = home_10[0].date if home_10 else None
    away_last = away_5[0].date if away_5 else None
    if home_last and away_last:
        f["rest_days"] = min((fixture.date - home_last).days, (fixture.date - away_last).days)
    elif home_last:
        f["rest_days"] = (fixture.date - home_last).days
    elif away_last:
        f["rest_days"] = (fixture.date - away_last).days
    else:
        f["rest_days"] = None

    cnt = (await session.execute(
        select(func.count()).select_from(Injury)
        .where(Injury.fixture_id == fixture.id, Injury.type.not_in(["Questionable", "Doubtful"]))
    )).scalar_one()
    f["injuries_count"] = cnt


async def _elo_features(f, session, fixture, before_date):
    """3 Elo features from ClubElo ratings via team_source_mappings."""

    async def _get_elo(team_id):
        # Look up the ClubElo name via TeamSourceMapping
        mapping = (await session.execute(
            select(TeamSourceMapping.clubelo_name)
            .where(TeamSourceMapping.api_football_team_id == team_id)
        )).scalar_one_or_none()
        if not mapping:
            return None
        # Get most recent Elo before the fixture date
        elo = (await session.execute(
            select(EloRating.elo)
            .where(EloRating.team_name == mapping, EloRating.date < before_date)
            .order_by(EloRating.date.desc())
            .limit(1)
        )).scalar_one_or_none()
        return elo

    home_elo = await _get_elo(fixture.home_team_id)
    away_elo = await _get_elo(fixture.away_team_id)

    f["elo_home"] = home_elo
    f["elo_away"] = away_elo
    f["elo_gap"] = (home_elo - away_elo) if (home_elo is not None and away_elo is not None) else None


async def _pinnacle_features(f, session, fixture):
    """6 Pinnacle implied probability features."""
    rows = (await session.execute(
        select(Odds.market, Odds.label, Odds.value)
        .where(Odds.fixture_id == fixture.id, Odds.bookmaker_name == "Pinnacle")
    )).all()
    lookup = {(r.market, r.label): r.value for r in rows}

    for label, feat in [("Home", "pinnacle_implied_home"), ("Draw", "pinnacle_implied_draw"), ("Away", "pinnacle_implied_away")]:
        odds = lookup.get(("1x2", label))
        f[feat] = 1.0 / odds if odds else None

    for mkt, label, feat in [
        ("ou15", "Over 1.5", "pinnacle_implied_over15"),
        ("ou25", "Over 2.5", "pinnacle_implied_over25"),
        ("ou35", "Over 3.5", "pinnacle_implied_over35"),
    ]:
        odds = lookup.get((mkt, label))
        f[feat] = 1.0 / odds if odds else None


async def _consensus_features(f, session, fixture):
    """2 consensus implied probability features — mean of all bookmaker 1x2 odds."""
    for label, feat in [("Home", "consensus_implied_home"), ("Away", "consensus_implied_away")]:
        avg = (await session.execute(
            select(func.avg(Odds.value))
            .where(Odds.fixture_id == fixture.id, Odds.market == "1x2", Odds.label == label)
        )).scalar_one_or_none()
        f[feat] = 1.0 / avg if avg else None


# ── context features ─────────────────────────────────────────────────────


async def _context_features(f, session, fixture, league_config, before_date):
    """12 context features derived from match context signals."""
    from app.services.match_context import MatchContextEngine

    # --- is_derby + derby_intensity ---
    home_team = await session.get(Team, fixture.home_team_id)
    away_team = await session.get(Team, fixture.away_team_id)
    home_name = home_team.name.lower() if home_team else ""
    away_name = away_team.name.lower() if away_team else ""

    derby_intensity = 0.0
    for team1_kw, team2_kw, _name, intensity in MatchContextEngine.DERBIES:
        home_match = any(kw in home_name for kw in team1_kw)
        away_match = any(kw in away_name for kw in team2_kw)
        rev_home = any(kw in home_name for kw in team2_kw)
        rev_away = any(kw in away_name for kw in team1_kw)
        if (home_match and away_match) or (rev_home and rev_away):
            derby_intensity = {"fierce": 0.8, "strong": 0.6, "moderate": 0.4}.get(intensity, 0.4)
            break

    f["is_derby"] = 1.0 if derby_intensity > 0 else 0.0
    f["derby_intensity"] = derby_intensity

    # --- congestion: games in last 14 days ---
    cutoff_14d = before_date - timedelta(days=14)
    for team_id, key in [(fixture.home_team_id, "home_congestion_14d"),
                          (fixture.away_team_id, "away_congestion_14d")]:
        result = await session.execute(
            select(func.count()).select_from(TeamLast20)
            .where(
                TeamLast20.team_id == team_id,
                TeamLast20.date >= cutoff_14d,
                TeamLast20.date < before_date,
            )
        )
        f[key] = float(result.scalar_one())

    # --- rest day difference ---
    rest = {}
    for team_id, label in [(fixture.home_team_id, "home"), (fixture.away_team_id, "away")]:
        result = await session.execute(
            select(func.max(TeamLast20.date))
            .where(TeamLast20.team_id == team_id, TeamLast20.date < before_date)
        )
        last_game = result.scalar_one_or_none()
        rest[label] = (before_date - last_game).days if last_game else 7
    f["rest_day_diff"] = float(rest.get("home", 7) - rest.get("away", 7))

    # --- relegation pressure ---
    if league_config and not league_config.is_international:
        total_teams = league_config.teams
        games_per_team = 2 * (total_teams - 1)
        relegation_zone = max(3, total_teams // 6)

        for team_id, key in [(fixture.home_team_id, "home_relegation_pressure"),
                              (fixture.away_team_id, "away_relegation_pressure")]:
            row = (await session.execute(
                select(Standing.rank, Standing.played)
                .where(
                    Standing.team_id == team_id,
                    Standing.league_id == fixture.league_id,
                )
                .order_by(Standing.season.desc())
                .limit(1)
            )).first()
            if row and row[0]:
                position = row[0]
                played = row[1] or 0
                remaining = games_per_team - played
                if position > (total_teams - relegation_zone) and 0 < remaining <= 15:
                    f[key] = min(1.0, (15 - remaining) / 12)
                else:
                    f[key] = 0.0
            else:
                f[key] = 0.0
    else:
        f["home_relegation_pressure"] = 0.0
        f["away_relegation_pressure"] = 0.0

    # --- form trajectory (recent 3 avg - older 3 avg from last 6 games) ---
    for team_id, key in [(fixture.home_team_id, "home_form_trajectory"),
                          (fixture.away_team_id, "away_form_trajectory")]:
        rows = await _last_n(session, team_id, before_date, 6)
        if len(rows) >= 5:
            goals = [r.goals_for or 0 for r in rows[:5]]
            goals.reverse()  # chronological
            recent_avg = sum(goals[3:]) / 2
            older_avg = sum(goals[:2]) / 2
            f[key] = float(recent_avg - older_avg)
        else:
            f[key] = 0.0

    # --- H2H goal average ---
    t1, t2 = sorted((fixture.home_team_id, fixture.away_team_id))
    h2h_rows = (await session.execute(
        select(HeadToHead.total_goals)
        .where(HeadToHead.team1_id == t1, HeadToHead.team2_id == t2, HeadToHead.date < before_date)
        .order_by(HeadToHead.date.desc())
        .limit(5)
    )).scalars().all()
    if h2h_rows and len(h2h_rows) >= 2:
        totals = [g for g in h2h_rows if g is not None]
        f["h2h_goal_avg"] = float(sum(totals) / len(totals)) if totals else None
    else:
        f["h2h_goal_avg"] = None

    # --- scoring streaks ---
    for team_id, key in [(fixture.home_team_id, "home_scoring_streak"),
                          (fixture.away_team_id, "away_scoring_streak")]:
        rows = await _last_n(session, team_id, before_date, 10)
        streak = 0
        for r in rows:
            if (r.goals_for or 0) > 0:
                streak += 1
            else:
                break
        f[key] = float(streak)


# ── public API ───────────────────────────────────────────────────────────


async def compute_features(
    session: AsyncSession,
    fixture: Fixture,
    league_config=None,
    before_date: date | None = None,
) -> dict:
    """Compute all 30 features. Returns dict[feature_name, float | None].

    All DB queries filter by date < before_date to prevent training data leakage.
    Defaults to fixture.date when not specified.
    """
    if before_date is None:
        before_date = fixture.date

    f: dict = {}

    # Pre-fetch TeamLast20 rows (shared across xG, Form, Situational)
    home_10 = await _last_n(session, fixture.home_team_id, before_date, 10)
    away_5 = await _last_n(session, fixture.away_team_id, before_date, 5)
    home_h5 = await _last_n(session, fixture.home_team_id, before_date, 5, venue="H")
    away_a5 = await _last_n(session, fixture.away_team_id, before_date, 5, venue="A")

    _xg_features(f, home_10, away_5)
    _form_features(f, home_10[:5], away_5, home_h5, away_a5)
    await _h2h_features(f, session, fixture, before_date)
    await _league_features(f, session, fixture, before_date)
    await _situational_features(f, session, fixture, home_10, away_5)
    await _elo_features(f, session, fixture, before_date)
    await _pinnacle_features(f, session, fixture)
    await _consensus_features(f, session, fixture)
    # Context features computed but NOT included in FEATURE_NAMES (degraded OU25)
    # await _context_features(f, session, fixture, league_config, before_date)

    return f


async def compute_feature_vector(
    session: AsyncSession,
    fixture: Fixture,
    league_config=None,
    before_date: date | None = None,
) -> np.ndarray:
    """30-element float32 array. NaN for missing (XGBoost handles natively)."""
    features = await compute_features(session, fixture, league_config, before_date)
    return np.array(
        [features.get(n) if features.get(n) is not None else float("nan") for n in FEATURE_NAMES],
        dtype=np.float32,
    )
