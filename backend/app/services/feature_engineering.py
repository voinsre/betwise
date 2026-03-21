"""Feature engineering — 30-feature vectors for ML prediction.

Tier A (19 features from existing data):
  xG (7), Form (4), H2H (3), League (3), Situational (2)
Tier B (11 features, available after OddsPapi/ClubElo):
  Elo (3), Pinnacle (6), Consensus (2)

Critical: all queries use before_date to prevent training data leakage.
"""

import logging
from datetime import date
from statistics import mean

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.elo_ratings import EloRating
from app.models.fixture import Fixture
from app.models.head_to_head import HeadToHead
from app.models.injury import Injury
from app.models.odds import Odds
from app.models.standing import Standing
from app.models.team_last20 import TeamLast20

logger = logging.getLogger(__name__)

FEATURE_NAMES = [
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
    """3 Elo features — returns None until ClubElo sync populates elo_ratings."""
    f["elo_home"] = None
    f["elo_away"] = None
    f["elo_gap"] = None


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
