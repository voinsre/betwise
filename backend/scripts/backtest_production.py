"""
Production Backtest — uses the REAL PoissonPredictor logic and MLPredictor
with before_date filtering to prevent data leakage.

Runs TWO scenarios side-by-side (30-feature models + calibration):
  A) BEST:        DC 1X blacklisted, min confidence 70
  B) BEST_CONF60: DC 1X blacklisted, min confidence 60

Compare against previous baselines:
  CORRECTED (30-feat, no blacklist, conf 60): 1734 bets, -24.8u, -1.4% ROI
  42-feat V2 (blacklist, conf 70):             811 bets, -40.5u, -5.0% ROI

Read-only — does not modify any database tables.
"""

import asyncio
import sys
import os
import logging
import time

import numpy as np
from datetime import date, timedelta
from collections import defaultdict

sys.path.insert(0, r"c:\Users\vsrez\OneDrive\Documents\Projects\betwise\backend")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://betwise:BetWise2026Secure@localhost:5432/betwise",
)

logging.basicConfig(level=logging.WARNING)

from scipy.stats import poisson as poisson_dist
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session as session_factory
from app.models.fixture import Fixture
from app.models.league import League
from app.models.odds import Odds
from app.models.standing import Standing
from app.models.team_last20 import TeamLast20
from app.services.feature_engineering import compute_feature_vector
from app.services.league_config import (
    get_league_by_api_id,
    is_market_active,
    get_active_league_ids,
)
from app.services.prediction_engine import (
    MARKETS_CONFIG,
    ML_MARKETS,
    VALUE_BET_MARKETS,
    DISPLAY_ONLY_MARKETS,
    BLACKLISTED_SELECTIONS,
    MARKET_ALPHA,
    MARKET_ODDS_MIN,
)
from app.config import settings
from app.services.probability_calibrator import calibrate_probability

ODDS_MAX = settings.ODDS_MAX
GLOBAL_MIN_EDGE = settings.MIN_EDGE * 100  # 5.0
BACKTEST_START = date(2024, 8, 1)  # 2024-25 season onwards
BACKTEST_END = date(2026, 3, 21)


# ═══════════════════════════════════════════════════════════════════
# Poisson model — replicated with before_date filtering
# ═══════════════════════════════════════════════════════════════════


async def get_team_games(session, team_id, before_date, venue=None):
    """Load TeamLast20 rows BEFORE the given date, optionally filtered by venue."""
    q = select(TeamLast20).where(
        TeamLast20.team_id == team_id, TeamLast20.date < before_date
    )
    if venue:
        q = q.where(TeamLast20.venue == venue)
    q = q.order_by(TeamLast20.date.desc())
    result = await session.execute(q)
    return list(result.scalars().all())


def weighted_avg_goals(games, goals_field, xg_field):
    """Replicate PoissonPredictor._weighted_avg_goals."""
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


def calc_attack_strength(venue_games, all_games, league_avg_per_team, venue_weight=0.7):
    """Replicate PoissonPredictor._calc_attack_strength."""
    venue_avg = weighted_avg_goals(venue_games, "goals_for", "xg_for")
    overall_avg = weighted_avg_goals(all_games, "goals_for", "xg_for")
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


def calc_defense_weakness(venue_games, all_games, league_avg_per_team, venue_weight=0.7):
    """Replicate PoissonPredictor._calc_defense_weakness."""
    venue_avg = weighted_avg_goals(venue_games, "goals_against", "xg_against")
    overall_avg = weighted_avg_goals(all_games, "goals_against", "xg_against")
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


async def get_league_stats_before_date(session, league_id, season, before_date):
    """
    Compute league averages from FT fixtures BEFORE the given date.
    Avoids the standings leakage in PoissonPredictor.get_league_averages().
    """
    result = await session.execute(
        select(
            func.count(Fixture.id),
            func.sum(Fixture.score_home_ft),
            func.sum(Fixture.score_away_ft),
        ).where(
            Fixture.league_id == league_id,
            Fixture.season == season,
            Fixture.status == "FT",
            Fixture.date < before_date,
            Fixture.score_home_ft.is_not(None),
            Fixture.score_away_ft.is_not(None),
        )
    )
    row = result.one()
    total_games = row[0] or 0

    if total_games >= 10:
        total_home = float(row[1] or 0)
        total_away = float(row[2] or 0)
        avg_home = total_home / total_games
        avg_away = total_away / total_games

        hw_result = await session.execute(
            select(func.count(Fixture.id)).where(
                Fixture.league_id == league_id,
                Fixture.season == season,
                Fixture.status == "FT",
                Fixture.date < before_date,
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

    return {
        "avg_goals_per_game": 2.70,
        "avg_home_goals": 1.50,
        "avg_away_goals": 1.20,
        "home_win_rate": 0.46,
        "total_games": 0,
    }


def calc_home_advantage(league_stats):
    """Replicate PoissonPredictor._calc_home_advantage."""
    avg_home = league_stats["avg_home_goals"]
    avg_away = league_stats["avg_away_goals"]
    if avg_away > 0:
        ha = avg_home / avg_away
    else:
        ha = 1.25
    return float(np.clip(ha, 1.05, 1.45))


def build_poisson_matrix(lambda_home, lambda_away, max_goals=7):
    """7x7 bivariate Poisson probability matrix."""
    matrix = np.zeros((max_goals, max_goals))
    for i in range(max_goals):
        for j in range(max_goals):
            matrix[i][j] = poisson_dist.pmf(i, lambda_home) * poisson_dist.pmf(
                j, lambda_away
            )
    return matrix


def calc_double_chance(matrix):
    n = matrix.shape[0]
    home_win = sum(matrix[i][j] for i in range(n) for j in range(n) if i > j)
    draw = sum(matrix[i][i] for i in range(n))
    away_win = sum(matrix[i][j] for i in range(n) for j in range(n) if i < j)
    return {
        "1X": round(float(home_win + draw), 6),
        "12": round(float(home_win + away_win), 6),
        "X2": round(float(draw + away_win), 6),
    }


def calc_over_under(matrix, line):
    n = matrix.shape[0]
    under = sum(
        matrix[i][j] for i in range(n) for j in range(n) if (i + j) <= int(line)
    )
    over = 1.0 - under
    return {
        f"Over {line}": round(float(over), 6),
        f"Under {line}": round(float(under), 6),
    }


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def evaluate_bet(market_code, label, home_goals, away_goals):
    total = home_goals + away_goals
    if market_code == "dc":
        if label == "1X":
            return home_goals >= away_goals
        elif label == "12":
            return home_goals != away_goals
        elif label == "X2":
            return away_goals >= home_goals
    elif market_code == "ou15":
        return total > 1.5 if "Over" in label else total < 1.5
    elif market_code == "ou25":
        return total > 2.5 if "Over" in label else total < 2.5
    elif market_code == "ou35":
        return total > 3.5 if "Over" in label else total < 3.5
    return False


def calc_confidence(
    poisson_prob, ml_prob, edge, league, home_games, away_games, odds_values
):
    """Replicate PredictionEngine._calc_confidence — 5 signals, 100 max."""
    score = 0.0

    # Model agreement (25 max)
    if ml_prob is not None:
        agreement = 1 - abs(poisson_prob - ml_prob)
        score += agreement * 25
    else:
        score += 12.5

    # Probability decisiveness (25 max)
    max_prob = max(poisson_prob, ml_prob or 0)
    score += min(max_prob / 0.70, 1.0) * 25

    # Data quality (15 max)
    if league:
        if getattr(league, "has_statistics", False):
            score += 5
        if getattr(league, "has_odds", False):
            score += 5
        if getattr(league, "has_injuries", False):
            score += 5

    # Sample size (15 max)
    completeness = (min(home_games, 20) + min(away_games, 20)) / 40
    score += completeness * 15

    # Market consensus (20 max)
    if len(odds_values) >= 2:
        odds_arr = np.array(odds_values)
        variance = float(np.var(odds_arr))
        consensus = max(0, 1 - variance * 10) * 20
        score += consensus
    else:
        score += 10

    return int(min(score, 100))


# ═══════════════════════════════════════════════════════════════════
# Tracking
# ═══════════════════════════════════════════════════════════════════


def make_tracker():
    return {
        "stats": {
            "fixtures_analyzed": 0,
            "fixtures_skipped_no_form": 0,
            "fixtures_skipped_no_odds": 0,
            "predictions_generated": 0,
            "value_bets": 0,
            "value_correct": 0,
            "total_profit": 0.0,
        },
        "by_market": defaultdict(
            lambda: {"bets": 0, "correct": 0, "profit": 0.0, "avg_edge": [], "avg_odds": []}
        ),
        "by_league": defaultdict(lambda: {"bets": 0, "correct": 0, "profit": 0.0}),
        "by_odds": defaultdict(lambda: {"bets": 0, "correct": 0, "profit": 0.0}),
        "by_edge": defaultdict(lambda: {"bets": 0, "correct": 0, "profit": 0.0}),
        "by_selection": defaultdict(lambda: {"bets": 0, "correct": 0, "profit": 0.0}),
        "by_month": defaultdict(lambda: {"bets": 0, "correct": 0, "profit": 0.0}),
        "by_confidence": defaultdict(lambda: {"bets": 0, "correct": 0, "profit": 0.0}),
        "calibration": defaultdict(
            lambda: defaultdict(lambda: {"count": 0, "correct": 0})
        ),
        "all_calibration": defaultdict(
            lambda: defaultdict(lambda: {"count": 0, "correct": 0})
        ),
    }


def record_value_bet(
    tracker, market_code, label, league_name, odd_value, effective_edge,
    confidence, is_correct, fdate,
):
    profit = (odd_value - 1.0) if is_correct else -1.0
    tracker["stats"]["value_bets"] += 1
    tracker["stats"]["value_correct"] += int(is_correct)
    tracker["stats"]["total_profit"] += profit

    tracker["by_market"][market_code]["bets"] += 1
    tracker["by_market"][market_code]["correct"] += int(is_correct)
    tracker["by_market"][market_code]["profit"] += profit
    tracker["by_market"][market_code]["avg_edge"].append(effective_edge * 100)
    tracker["by_market"][market_code]["avg_odds"].append(odd_value)

    tracker["by_league"][league_name]["bets"] += 1
    tracker["by_league"][league_name]["correct"] += int(is_correct)
    tracker["by_league"][league_name]["profit"] += profit

    if odd_value < 1.30:
        obracket = "1.20-1.30"
    elif odd_value < 1.40:
        obracket = "1.30-1.40"
    elif odd_value < 1.50:
        obracket = "1.40-1.50"
    elif odd_value < 1.60:
        obracket = "1.50-1.60"
    elif odd_value < 1.80:
        obracket = "1.60-1.80"
    elif odd_value < 2.00:
        obracket = "1.80-2.00"
    else:
        obracket = "2.00-2.20"
    tracker["by_odds"][obracket]["bets"] += 1
    tracker["by_odds"][obracket]["correct"] += int(is_correct)
    tracker["by_odds"][obracket]["profit"] += profit

    epct = effective_edge * 100
    if epct < 7:
        ebracket = "05-07%"
    elif epct < 10:
        ebracket = "07-10%"
    elif epct < 15:
        ebracket = "10-15%"
    elif epct < 20:
        ebracket = "15-20%"
    else:
        ebracket = "20%+"
    tracker["by_edge"][ebracket]["bets"] += 1
    tracker["by_edge"][ebracket]["correct"] += int(is_correct)
    tracker["by_edge"][ebracket]["profit"] += profit

    sel_key = f"{market_code} {label}"
    tracker["by_selection"][sel_key]["bets"] += 1
    tracker["by_selection"][sel_key]["correct"] += int(is_correct)
    tracker["by_selection"][sel_key]["profit"] += profit

    mkey = fdate.strftime("%Y-%m") if hasattr(fdate, "strftime") else str(fdate)[:7]
    tracker["by_month"][mkey]["bets"] += 1
    tracker["by_month"][mkey]["correct"] += int(is_correct)
    tracker["by_month"][mkey]["profit"] += profit

    if confidence < 65:
        cbracket = "60-65"
    elif confidence < 70:
        cbracket = "65-70"
    elif confidence < 75:
        cbracket = "70-75"
    elif confidence < 80:
        cbracket = "75-80"
    elif confidence < 85:
        cbracket = "80-85"
    else:
        cbracket = "85+"
    tracker["by_confidence"][cbracket]["bets"] += 1
    tracker["by_confidence"][cbracket]["correct"] += int(is_correct)
    tracker["by_confidence"][cbracket]["profit"] += profit


# ═══════════════════════════════════════════════════════════════════
# Main backtest loop
# ═══════════════════════════════════════════════════════════════════


async def run_backtest():
    portfolio_ids = set(get_active_league_ids())

    from app.services.ml_model import MLPredictor

    ml = MLPredictor(session_factory)
    ml.load_models()
    has_ml = ml.is_ready()
    ml_model_keys = list(ml._models.keys()) if has_ml else []

    # Two scenarios — 30-feature models + calibration
    best = make_tracker()        # DC 1X blacklisted, min confidence 70
    best_c60 = make_tracker()    # DC 1X blacklisted, min confidence 60

    scenarios = [
        ("BEST", best, True, 70),        # (label, tracker, blacklist_1x, min_conf)
        ("C60", best_c60, True, 60),
    ]

    league_stats_cache = {}
    t0 = time.time()

    async with session_factory() as session:
        fixtures_result = await session.execute(
            text("""
            SELECT DISTINCT f.id, f.date, f.home_team_id, f.away_team_id,
                   f.league_id, f.season, f.score_home_ft, f.score_away_ft
            FROM fixtures f
            JOIN odds o ON f.id = o.fixture_id AND o.bookmaker_name = 'Pinnacle'
            WHERE f.status = 'FT'
              AND f.league_id = ANY(:league_ids)
              AND f.date >= :start_date
              AND f.date <= :end_date
              AND f.score_home_ft IS NOT NULL
              AND f.score_away_ft IS NOT NULL
            ORDER BY f.date
        """),
            {
                "league_ids": list(portfolio_ids),
                "start_date": BACKTEST_START,
                "end_date": BACKTEST_END,
            },
        )
        fixtures = fixtures_result.all()
        total = len(fixtures)

        print(f"Backtesting {total} fixtures from {BACKTEST_START} to {BACKTEST_END}")
        print(f"Config: VALUE_BET_MARKETS={VALUE_BET_MARKETS}, ODDS_MAX={ODDS_MAX}, MIN_EDGE={GLOBAL_MIN_EDGE}%")
        print(f"MARKET_ALPHA={MARKET_ALPHA}")
        print(f"ML models loaded: {has_ml} ({ml_model_keys})")
        print(f"Running TWO scenarios: BEST (conf70) / BEST_CONF60 (conf60)")
        print(f"Previous CORRECTED baseline: 1734 bets, -24.8u, -1.4% ROI")
        print(f"Previous 42-feat V2: 811 bets, -40.5u, -5.0% ROI")
        print()

        for i, row in enumerate(fixtures):
            fid, fdate, home_id, away_id, league_id, season, h_goals, a_goals = row

            if i % 500 == 0 and i > 0:
                elapsed = time.time() - t0
                rate = i / elapsed
                eta = (total - i) / rate if rate > 0 else 0
                for lbl, t_, _, _ in scenarios:
                    vb = t_["stats"]["value_bets"]
                    vc = t_["stats"]["value_correct"]
                    hr = round(vc / vb * 100, 1) if vb > 0 else 0
                    print(
                        f"  [{lbl}] {i}/{total} ({i/total*100:.0f}%) — "
                        f"{vb} bets, {hr}% hit, {t_['stats']['total_profit']:+.1f}u  "
                        f"[{elapsed:.0f}s elapsed, ETA {eta:.0f}s]"
                    )

            league_config = get_league_by_api_id(league_id)
            if not league_config:
                continue

            # ── Load team games with before_date filter ──
            home_venue = await get_team_games(session, home_id, fdate, venue="H")
            home_all = await get_team_games(session, home_id, fdate)
            away_venue = await get_team_games(session, away_id, fdate, venue="A")
            away_all = await get_team_games(session, away_id, fdate)

            if len(home_all) < 3 or len(away_all) < 3:
                for _, t_, _, _ in scenarios:
                    t_["stats"]["fixtures_skipped_no_form"] += 1
                continue

            for _, t_, _, _ in scenarios:
                t_["stats"]["fixtures_analyzed"] += 1

            # ── League stats (cached per league/season/month) ──
            cache_key = (league_id, season, fdate.year, fdate.month)
            if cache_key not in league_stats_cache:
                league_stats_cache[cache_key] = await get_league_stats_before_date(
                    session, league_id, season, fdate
                )
            league_stats = league_stats_cache[cache_key]

            # ── Compute Poisson (exact production formulas) ──
            avg_per_team = league_stats["avg_goals_per_game"] / 2
            home_attack = calc_attack_strength(home_venue, home_all, avg_per_team)
            home_defense = calc_defense_weakness(home_venue, home_all, avg_per_team)
            away_attack = calc_attack_strength(away_venue, away_all, avg_per_team)
            away_defense = calc_defense_weakness(away_venue, away_all, avg_per_team)
            home_adv = calc_home_advantage(league_stats)

            lambda_home = float(
                np.clip(home_attack * away_defense * avg_per_team * home_adv, 0.2, 4.5)
            )
            lambda_away = float(
                np.clip(away_attack * home_defense * avg_per_team, 0.2, 4.5)
            )

            matrix = build_poisson_matrix(lambda_home, lambda_away)
            poisson_markets = {
                "dc": calc_double_chance(matrix),
                "ou15": calc_over_under(matrix, 1.5),
                "ou25": calc_over_under(matrix, 2.5),
                "ou35": calc_over_under(matrix, 3.5),
            }

            # ── Load fixture ORM for ML feature engineering ──
            fixture_obj = await session.get(Fixture, fid)
            if not fixture_obj:
                continue

            # ── ML predictions ──
            # ml_raw[market] = [P(class0=Under), P(class1=Over)]
            ml_raw = {}
            if has_ml:
                try:
                    feature_vec = await compute_feature_vector(
                        session, fixture_obj, league_config, before_date=fdate
                    )
                    if feature_vec is not None and not np.all(np.isnan(feature_vec)):
                        for ml_market in ML_MARKETS:
                            if ml_market in ml._models:
                                try:
                                    proba = ml._models[ml_market].predict_proba(
                                        feature_vec.reshape(1, -1)
                                    )[0]
                                    ml_raw[ml_market] = proba
                                except Exception:
                                    pass
                except Exception:
                    pass

            # ── Load odds ──
            odds_result = await session.execute(
                select(Odds).where(Odds.fixture_id == fid)
            )
            all_odds = list(odds_result.scalars().all())
            if not all_odds:
                for _, t_, _, _ in scenarios:
                    t_["stats"]["fixtures_skipped_no_odds"] += 1
                continue

            best_odds = {}
            pinnacle_odds = {}
            odds_by_market = defaultdict(list)
            for o in all_odds:
                key = (o.market, o.label)
                if key not in best_odds or o.value > best_odds[key]:
                    best_odds[key] = o.value
                if o.bookmaker_name == "Pinnacle":
                    pkey = f"{o.market}_{o.label}".lower().replace(" ", "_")
                    pinnacle_odds[pkey] = o.value
                odds_by_market[o.market].append(o.value)

            # ── League ORM + team game counts for confidence ──
            league_orm = await session.get(League, league_id)

            hc_r = await session.execute(
                select(func.count(TeamLast20.id)).where(
                    TeamLast20.team_id == home_id
                )
            )
            home_games_count = hc_r.scalar() or 0
            ac_r = await session.execute(
                select(func.count(TeamLast20.id)).where(
                    TeamLast20.team_id == away_id
                )
            )
            away_games_count = ac_r.scalar() or 0

            # ══════════════════════════════════════════
            # EVALUATE EACH MARKET/SELECTION — THREE SCENARIOS
            # ══════════════════════════════════════════
            scenario_candidates = {lbl: [] for lbl, _, _, _ in scenarios}

            for market_code, config in MARKETS_CONFIG.items():
                if not is_market_active(league_id, market_code):
                    continue

                poisson_probs = poisson_markets.get(market_code, {})

                for label in config["labels"]:
                    poisson_prob = poisson_probs.get(label)
                    if not poisson_prob or poisson_prob <= 0:
                        continue

                    is_correct = evaluate_bet(market_code, label, h_goals, a_goals)

                    # ── ML prob: CORRECTED mapping (all scenarios use this) ──
                    ml_prob = None
                    if market_code in ml_raw and market_code in ML_MARKETS:
                        proba = ml_raw[market_code]
                        if "Over" in label:
                            ml_prob = float(proba[1])  # P(class1=Over)
                        elif "Under" in label:
                            ml_prob = float(proba[0])  # P(class0=Under)

                    alpha = MARKET_ALPHA.get(market_code, 0.50)

                    if ml_prob is not None and market_code in ML_MARKETS:
                        blended = alpha * poisson_prob + (1 - alpha) * ml_prob
                    else:
                        blended = poisson_prob

                    # Apply isotonic calibration (all scenarios)
                    blended = calibrate_probability(market_code, blended)

                    # Get best odds
                    odds_key = (market_code, label)
                    if odds_key not in best_odds:
                        # Still count predictions for calibration
                        for _, t_, _, _ in scenarios:
                            t_["stats"]["predictions_generated"] += 1
                            bucket = f"{int(blended * 10) / 10:.1f}"
                            t_["all_calibration"][market_code][bucket]["count"] += 1
                            t_["all_calibration"][market_code][bucket]["correct"] += int(is_correct)
                        continue

                    odd_value = best_odds[odds_key]
                    implied_prob = 1.0 / odd_value
                    edge = blended - implied_prob

                    # Pinnacle edge
                    pkey = f"{market_code}_{label}".lower().replace(" ", "_")
                    pinnacle_prob = (
                        1.0 / pinnacle_odds[pkey] if pkey in pinnacle_odds else None
                    )
                    pinnacle_edge = (
                        (blended - pinnacle_prob) if pinnacle_prob else None
                    )
                    effective_edge = (
                        pinnacle_edge if pinnacle_edge is not None else edge
                    )

                    # Confidence
                    confidence = calc_confidence(
                        poisson_prob,
                        ml_prob,
                        edge,
                        league_orm,
                        home_games_count,
                        away_games_count,
                        odds_by_market.get(market_code, []),
                    )

                    # Value detection per scenario
                    effective_min_edge = max(
                        GLOBAL_MIN_EDGE, league_config.min_edge_pct
                    )
                    odds_min = MARKET_ODDS_MIN.get(market_code, settings.ODDS_MIN)

                    for s_label, tracker, blacklist_1x, min_conf in scenarios:
                        tracker["stats"]["predictions_generated"] += 1
                        bucket = f"{int(blended * 10) / 10:.1f}"
                        tracker["all_calibration"][market_code][bucket]["count"] += 1
                        tracker["all_calibration"][market_code][bucket]["correct"] += int(is_correct)

                        effective_min_confidence = max(min_conf, league_config.min_confidence_pct)
                        is_value = (
                            (effective_edge * 100) >= effective_min_edge
                            and confidence >= effective_min_confidence
                            and odd_value >= odds_min
                            and odd_value <= ODDS_MAX
                            and market_code in VALUE_BET_MARKETS
                        )
                        if market_code in DISPLAY_ONLY_MARKETS:
                            is_value = False
                        if blacklist_1x and (market_code, label) in BLACKLISTED_SELECTIONS:
                            is_value = False

                        if is_value:
                            scenario_candidates[s_label].append({
                                "market_code": market_code,
                                "label": label,
                                "odd_value": odd_value,
                                "effective_edge": effective_edge,
                                "edge": edge,
                                "confidence": confidence,
                                "is_correct": is_correct,
                                "blended": blended,
                            })

            # ── Enforce one value bet per market per fixture ──
            for s_label, tracker, _, _ in scenarios:
                candidates = scenario_candidates[s_label]
                best_per_market = {}
                for c in candidates:
                    mkt = c["market_code"]
                    if mkt not in best_per_market or c["edge"] > best_per_market[mkt]["edge"]:
                        best_per_market[mkt] = c

                for c in best_per_market.values():
                    record_value_bet(
                        tracker,
                        c["market_code"],
                        c["label"],
                        league_config.name,
                        c["odd_value"],
                        c["effective_edge"],
                        c["confidence"],
                        c["is_correct"],
                        fdate,
                    )
                    bucket = f"{int(c['blended'] * 10) / 10:.1f}"
                    tracker["calibration"][c["market_code"]][bucket]["count"] += 1
                    tracker["calibration"][c["market_code"]][bucket]["correct"] += int(
                        c["is_correct"]
                    )

    elapsed = time.time() - t0
    print(f"\nBacktest completed in {elapsed:.0f}s ({elapsed/60:.1f}m)")
    print_results(best, best_c60)


# ═══════════════════════════════════════════════════════════════════
# Output
# ═══════════════════════════════════════════════════════════════════


def print_results(best, best_c60):
    for label_s, t in [
        ("BEST (30-feat, DC 1X blacklisted, conf>=70)", best),
        ("BEST_CONF60 (30-feat, DC 1X blacklisted, conf>=60)", best_c60),
    ]:
        s = t["stats"]
        vb = s["value_bets"]
        vc = s["value_correct"]
        hr = round(vc / vb * 100, 1) if vb > 0 else 0
        roi = round(s["total_profit"] / vb * 100, 1) if vb > 0 else 0

        print("\n" + "=" * 70)
        print(f"  SCENARIO: {label_s}")
        print("=" * 70)
        print(f"  Fixtures analyzed:        {s['fixtures_analyzed']}")
        print(f"  Skipped (no form):        {s['fixtures_skipped_no_form']}")
        print(f"  Skipped (no odds):        {s['fixtures_skipped_no_odds']}")
        print(f"  Predictions generated:    {s['predictions_generated']}")
        print(f"  Value bets:               {vb}")
        print(f"  Correct:                  {vc}")
        print(f"  HIT RATE:                 {hr}%")
        print(f"  Total P&L:                {s['total_profit']:+.1f}u")
        print(f"  ROI:                      {roi}%")
        print(f"  Selection rate:           {round(vb/max(s['fixtures_analyzed'],1)*100, 1)}%")

        # BY MARKET
        print(f"\n  {'Market':<10} {'Bets':>6} {'Correct':>8} {'Hit%':>7} {'P&L':>9} {'ROI':>7} {'AvgEdge':>8} {'AvgOdds':>8}")
        for market, data in sorted(t["by_market"].items()):
            h = round(data["correct"] / data["bets"] * 100, 1) if data["bets"] > 0 else 0
            r = round(data["profit"] / data["bets"] * 100, 1) if data["bets"] > 0 else 0
            ae = round(np.mean(data["avg_edge"]), 1) if data["avg_edge"] else 0
            ao = round(np.mean(data["avg_odds"]), 2) if data["avg_odds"] else 0
            print(f"  {market:<10} {data['bets']:>6} {data['correct']:>8} {h:>6.1f}% {data['profit']:>+8.1f}u {r:>+6.1f}% {ae:>7.1f}% {ao:>8.2f}")

        # BY LEAGUE
        print(f"\n  {'League':<30} {'Bets':>6} {'Hit%':>7} {'P&L':>9} {'ROI':>7}")
        for league, data in sorted(
            t["by_league"].items(),
            key=lambda x: -x[1]["correct"] / max(x[1]["bets"], 1),
        ):
            h = round(data["correct"] / data["bets"] * 100, 1) if data["bets"] > 0 else 0
            r = round(data["profit"] / data["bets"] * 100, 1) if data["bets"] > 0 else 0
            print(f"  {league:<30} {data['bets']:>6} {h:>6.1f}% {data['profit']:>+8.1f}u {r:>+6.1f}%")

        # BY ODDS BRACKET
        print(f"\n  {'Bracket':<12} {'Bets':>6} {'Hit%':>7} {'P&L':>9} {'ROI':>7}")
        for bracket, data in sorted(t["by_odds"].items()):
            h = round(data["correct"] / data["bets"] * 100, 1) if data["bets"] > 0 else 0
            r = round(data["profit"] / data["bets"] * 100, 1) if data["bets"] > 0 else 0
            print(f"  {bracket:<12} {data['bets']:>6} {h:>6.1f}% {data['profit']:>+8.1f}u {r:>+6.1f}%")

        # BY EDGE BRACKET
        print(f"\n  {'Edge':<10} {'Bets':>6} {'Hit%':>7} {'P&L':>9} {'ROI':>7}")
        for bracket, data in sorted(t["by_edge"].items()):
            h = round(data["correct"] / data["bets"] * 100, 1) if data["bets"] > 0 else 0
            r = round(data["profit"] / data["bets"] * 100, 1) if data["bets"] > 0 else 0
            print(f"  {bracket:<10} {data['bets']:>6} {h:>6.1f}% {data['profit']:>+8.1f}u {r:>+6.1f}%")

        # BY SELECTION
        print(f"\n  {'Selection':<18} {'Bets':>6} {'Hit%':>7} {'P&L':>9} {'ROI':>7}")
        for sel, data in sorted(
            t["by_selection"].items(),
            key=lambda x: -x[1]["correct"] / max(x[1]["bets"], 1),
        ):
            h = round(data["correct"] / data["bets"] * 100, 1) if data["bets"] > 0 else 0
            r = round(data["profit"] / data["bets"] * 100, 1) if data["bets"] > 0 else 0
            print(f"  {sel:<18} {data['bets']:>6} {h:>6.1f}% {data['profit']:>+8.1f}u {r:>+6.1f}%")

        # BY MONTH
        print(f"\n  {'Month':<10} {'Bets':>6} {'Hit%':>7} {'P&L':>9}")
        for month, data in sorted(t["by_month"].items()):
            h = round(data["correct"] / data["bets"] * 100, 1) if data["bets"] > 0 else 0
            print(f"  {month:<10} {data['bets']:>6} {h:>6.1f}% {data['profit']:>+8.1f}u")

        # BY CONFIDENCE
        print(f"\n  {'Conf':<10} {'Bets':>6} {'Hit%':>7} {'P&L':>9}")
        for conf, data in sorted(t["by_confidence"].items()):
            h = round(data["correct"] / data["bets"] * 100, 1) if data["bets"] > 0 else 0
            print(f"  {conf:<10} {data['bets']:>6} {h:>6.1f}% {data['profit']:>+8.1f}u")

        # CALIBRATION — all predictions
        print(f"\n  CALIBRATION — ALL PREDICTIONS")
        for market in ["dc", "ou15", "ou25", "ou35"]:
            buckets = t["all_calibration"][market]
            if not buckets:
                continue
            print(f"\n    --- {market} ---")
            print(f"    {'Bucket':<10} {'Count':>6} {'Predicted':>10} {'Actual':>8} {'Gap':>8}")
            for bucket, data in sorted(buckets.items()):
                if data["count"] < 3:
                    continue
                predicted = float(bucket) + 0.05
                actual = data["correct"] / data["count"]
                gap = predicted - actual
                direction = "OVER" if gap > 0.05 else "UNDER" if gap < -0.05 else "OK"
                print(f"    {bucket:<10} {data['count']:>6} {predicted:>10.2f} {actual:>8.3f} {gap:>+8.3f} {direction}")

        # CALIBRATION — value bets
        print(f"\n  CALIBRATION — VALUE BETS ONLY")
        for market in ["dc", "ou25"]:
            buckets = t["calibration"][market]
            if not buckets:
                continue
            print(f"\n    --- {market} ---")
            print(f"    {'Bucket':<10} {'Count':>6} {'Predicted':>10} {'Actual':>8} {'Gap':>8}")
            for bucket, data in sorted(buckets.items()):
                if data["count"] < 3:
                    continue
                predicted = float(bucket) + 0.05
                actual = data["correct"] / data["count"]
                gap = predicted - actual
                direction = "OVER" if gap > 0.05 else "UNDER" if gap < -0.05 else "OK"
                print(f"    {bucket:<10} {data['count']:>6} {predicted:>10.2f} {actual:>8.3f} {gap:>+8.3f} {direction}")

    # ═══════════════════════════════════════════════════
    # SIDE-BY-SIDE COMPARISON (3 scenarios + previous baseline)
    # ═══════════════════════════════════════════════════
    trackers = [
        ("BEST", best),
        ("C60", best_c60),
    ]

    def _roi(t_):
        vb_ = t_["stats"]["value_bets"]
        return round(t_["stats"]["total_profit"] / vb_ * 100, 1) if vb_ > 0 else 0

    def _hr(t_):
        vb_ = t_["stats"]["value_bets"]
        return round(t_["stats"]["value_correct"] / vb_ * 100, 1) if vb_ > 0 else 0

    print("\n" + "=" * 70)
    print("  SIDE-BY-SIDE COMPARISON")
    print("=" * 70)
    print(f"  Previous CORRECTED baseline: 1734 bets, -24.8u, -1.4% ROI")
    print(f"  Previous 42-feat V2:          811 bets, -40.5u, -5.0% ROI")
    print()
    print(f"  {'Metric':<25} {'BEST':>12} {'C60':>12}")
    print(f"  {'-'*25} {'-'*12} {'-'*12}")
    for metric in ["fixtures_analyzed", "value_bets", "value_correct"]:
        vals = [t_["stats"][metric] for _, t_ in trackers]
        print(f"  {metric:<25} {vals[0]:>12,} {vals[1]:>12,}")
    hr_vals = [f"{_hr(t_)}%" for _, t_ in trackers]
    pnl_vals = [f"{t_['stats']['total_profit']:+.1f}u" for _, t_ in trackers]
    roi_vals = [f"{_roi(t_)}%" for _, t_ in trackers]
    sel_vals = [f"{round(t_['stats']['value_bets']/max(t_['stats']['fixtures_analyzed'],1)*100,1)}%" for _, t_ in trackers]
    print(f"  {'Hit rate':<25} {hr_vals[0]:>12} {hr_vals[1]:>12}")
    print(f"  {'P&L':<25} {pnl_vals[0]:>12} {pnl_vals[1]:>12}")
    print(f"  {'ROI':<25} {roi_vals[0]:>12} {roi_vals[1]:>12}")
    print(f"  {'Selection rate':<25} {sel_vals[0]:>12} {sel_vals[1]:>12}")

    # Per-market comparison
    all_markets = sorted(
        set().union(*(t_["by_market"].keys() for _, t_ in trackers))
    )
    print(f"\n  {'Market':<10} {'BEST.Bets':>9} {'BEST.ROI':>9}  |  {'C60.Bets':>8} {'C60.ROI':>8}")
    print(f"  {'-'*10} {'-'*9} {'-'*9}  |  {'-'*8} {'-'*8}")
    for mkt in all_markets:
        row_parts = []
        for _, t_ in trackers:
            d = t_["by_market"][mkt]
            r = round(d["profit"] / d["bets"] * 100, 1) if d["bets"] > 0 else 0
            row_parts.append(f"{d['bets']:>9} {r:>+8.1f}%")
        print(f"  {mkt:<10} {row_parts[0]}  |  {row_parts[1]}")

    # VERDICT
    best_roi = _roi(best)
    c60_roi = _roi(best_c60)
    best_pnl = best["stats"]["total_profit"]
    c60_pnl = best_c60["stats"]["total_profit"]
    print(f"\n  VERDICT:")
    print(f"    Previous CORRECTED (30-feat, no blacklist, conf60): -24.8u (-1.4% ROI)")
    print(f"    Previous 42-feat V2 (blacklist, conf70):           -40.5u (-5.0% ROI)")
    print(f"    BEST (30-feat, blacklist, conf70):   {best_pnl:+.1f}u ({best_roi}% ROI)")
    print(f"    BEST_CONF60 (30-feat, blacklist, conf60): {c60_pnl:+.1f}u ({c60_roi}% ROI)")
    if best_roi > c60_roi:
        print(f"    --> conf70 helps: {best_roi - c60_roi:+.1f}% ROI vs conf60")
    else:
        print(f"    --> conf60 better: {c60_roi - best_roi:+.1f}% ROI advantage")


if __name__ == "__main__":
    asyncio.run(run_backtest())
