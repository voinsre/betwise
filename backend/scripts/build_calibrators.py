"""
Builds isotonic calibration models for each market.

Uses the PRODUCTION Poisson + XGBoost pipeline against all FT fixtures
to generate (raw_probability, actual_outcome) pairs.
Then fits IsotonicRegression per market and saves the calibrators.

The calibrators are loaded at runtime by predict_fixture() and applied
AFTER blending but BEFORE edge calculation.

Output: ml/calibrators/{market}_calibrator.pkl
"""

import asyncio
import logging
import os
import pickle
import sys
import time

import numpy as np
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss

sys.path.insert(0, r"c:\Users\vsrez\OneDrive\Documents\Projects\betwise\backend")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://betwise:BetWise2026Secure@localhost:5432/betwise",
)

logging.basicConfig(level=logging.WARNING)

from scipy.stats import poisson as poisson_dist
from sqlalchemy import func, select, text

from app.database import async_session as session_factory
from app.models.fixture import Fixture
from app.models.team_last20 import TeamLast20
from app.services.feature_engineering import FEATURE_NAMES, compute_feature_vector
from app.services.league_config import (
    get_active_league_ids,
    get_league_by_api_id,
    is_market_active,
)
from app.services.prediction_engine import (
    MARKETS_CONFIG,
    ML_MARKETS,
    MARKET_ALPHA,
)

CALIBRATOR_DIR = Path("ml/calibrators")
CALIBRATOR_DIR.mkdir(parents=True, exist_ok=True)

# Use data from 2024-08 onward (where we have form data + Pinnacle odds)
CAL_START = date(2024, 8, 1)
CAL_END = date.today() - timedelta(days=1)


# ═══════════════════════════════════════════════════════════════════
# Poisson model — replicated with before_date (from backtest)
# ═══════════════════════════════════════════════════════════════════


async def get_team_games(session, team_id, before_date, venue=None):
    q = select(TeamLast20).where(
        TeamLast20.team_id == team_id, TeamLast20.date < before_date
    )
    if venue:
        q = q.where(TeamLast20.venue == venue)
    q = q.order_by(TeamLast20.date.desc())
    result = await session.execute(q)
    return list(result.scalars().all())


def weighted_avg_goals(games, goals_field, xg_field):
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
    avg_home = league_stats["avg_home_goals"]
    avg_away = league_stats["avg_away_goals"]
    if avg_away > 0:
        ha = avg_home / avg_away
    else:
        ha = 1.25
    return float(np.clip(ha, 1.05, 1.45))


def build_poisson_matrix(lambda_home, lambda_away, max_goals=7):
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


def evaluate_outcome(market_code, label, home_goals, away_goals):
    """Returns 1 if bet would have won, 0 otherwise."""
    total = home_goals + away_goals
    if market_code == "dc":
        if label == "1X":
            return int(home_goals >= away_goals)
        elif label == "12":
            return int(home_goals != away_goals)
        elif label == "X2":
            return int(away_goals >= home_goals)
    elif market_code == "ou15":
        return int(total > 1.5) if "Over" in label else int(total < 1.5)
    elif market_code == "ou25":
        return int(total > 2.5) if "Over" in label else int(total < 2.5)
    elif market_code == "ou35":
        return int(total > 3.5) if "Over" in label else int(total < 3.5)
    return 0


# ═══════════════════════════════════════════════════════════════════
# Collect calibration data
# ═══════════════════════════════════════════════════════════════════


async def collect_calibration_data():
    """
    Run the production Poisson+ML pipeline against historical fixtures.
    Collect (raw_blended_probability, actual_outcome) pairs per market.
    """
    from app.services.ml_model import MLPredictor

    ml = MLPredictor(session_factory)
    ml.load_models()
    has_ml = ml.is_ready()
    ml_model_keys = list(ml._models.keys()) if has_ml else []
    portfolio_ids = set(get_active_league_ids())

    # Collect: market -> {"probs": [...], "outcomes": [...]}
    cal_data = defaultdict(lambda: {"probs": [], "outcomes": []})
    league_stats_cache = {}

    t0 = time.time()

    async with session_factory() as session:
        fixtures_result = await session.execute(
            text("""
            SELECT f.id, f.date, f.home_team_id, f.away_team_id,
                   f.league_id, f.season, f.score_home_ft, f.score_away_ft
            FROM fixtures f
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
                "start_date": CAL_START,
                "end_date": CAL_END,
            },
        )
        fixtures = fixtures_result.all()
        total = len(fixtures)
        print(f"Collecting calibration data from {total} fixtures ({CAL_START} to {CAL_END})")
        print(f"ML models loaded: {has_ml} ({ml_model_keys})")
        print(f"MARKET_ALPHA={MARKET_ALPHA}")

        skipped_form = 0

        for i, row in enumerate(fixtures):
            fid, fdate, home_id, away_id, league_id, season, h_goals, a_goals = row

            if i % 1000 == 0 and i > 0:
                elapsed = time.time() - t0
                total_points = sum(len(v["probs"]) for v in cal_data.values())
                print(
                    f"  Progress: {i}/{total} ({i / total * 100:.0f}%) — "
                    f"{total_points} data points — {elapsed:.0f}s elapsed"
                )

            league_config = get_league_by_api_id(league_id)
            if not league_config:
                continue

            # ── Team form data with before_date ──
            home_venue = await get_team_games(session, home_id, fdate, venue="H")
            home_all = await get_team_games(session, home_id, fdate)
            away_venue = await get_team_games(session, away_id, fdate, venue="A")
            away_all = await get_team_games(session, away_id, fdate)

            if len(home_all) < 3 or len(away_all) < 3:
                skipped_form += 1
                continue

            # ── League stats (cached per league/season/month) ──
            cache_key = (league_id, season, fdate.year, fdate.month)
            if cache_key not in league_stats_cache:
                league_stats_cache[cache_key] = await get_league_stats_before_date(
                    session, league_id, season, fdate
                )
            league_stats = league_stats_cache[cache_key]

            # ── Compute Poisson ──
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

            # ── ML predictions (with before_date) ──
            ml_raw = {}
            if has_ml:
                fixture_obj = await session.get(Fixture, fid)
                if fixture_obj:
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

            # ── Compute blended probabilities for each selection ──
            for market_code, config in MARKETS_CONFIG.items():
                if not is_market_active(league_id, market_code):
                    continue

                poisson_probs = poisson_markets.get(market_code, {})

                for label in config["labels"]:
                    poisson_prob = poisson_probs.get(label)
                    if not poisson_prob or poisson_prob <= 0 or poisson_prob >= 1:
                        continue

                    # Blend (CORRECTED mapping)
                    alpha = MARKET_ALPHA.get(market_code, 0.50)
                    ml_prob = None

                    if market_code in ml_raw and market_code in ML_MARKETS:
                        proba = ml_raw[market_code]
                        if "Over" in label or "Yes" in label:
                            ml_prob = float(proba[1])  # P(class1=Over)
                        else:
                            ml_prob = float(proba[0])  # P(class0=Under)

                    if ml_prob is not None and market_code in ML_MARKETS:
                        blended = alpha * poisson_prob + (1 - alpha) * ml_prob
                    else:
                        blended = poisson_prob

                    # Clamp to valid range
                    blended = max(0.01, min(0.99, blended))

                    # Get actual outcome
                    outcome = evaluate_outcome(market_code, label, h_goals, a_goals)

                    # Store
                    cal_data[market_code]["probs"].append(blended)
                    cal_data[market_code]["outcomes"].append(outcome)

    elapsed = time.time() - t0
    print(f"\nCollection completed in {elapsed:.0f}s")
    print(f"Skipped (no form): {skipped_form}")
    return cal_data


# ═══════════════════════════════════════════════════════════════════
# Fit calibrators
# ═══════════════════════════════════════════════════════════════════


def fit_calibrators(cal_data: dict):
    """Fit isotonic regression calibrator per market and save."""
    calibrators = {}

    for market, data in sorted(cal_data.items()):
        probs = np.array(data["probs"])
        outcomes = np.array(data["outcomes"])

        if len(probs) < 100:
            print(f"\n  {market}: only {len(probs)} points — skipping calibration")
            continue

        print(f"\n{'=' * 60}")
        print(f"FITTING CALIBRATOR: {market} ({len(probs)} data points)")
        print(f"{'=' * 60}")

        # Fit isotonic regression
        calibrator = IsotonicRegression(
            y_min=0.01, y_max=0.99, out_of_bounds="clip"
        )
        calibrator.fit(probs, outcomes)

        # Evaluate: show calibration before and after
        calibrated = calibrator.predict(probs)

        # Bucket analysis
        print(
            f"\n  {'Bucket':<10} {'Count':>6} {'RawProb':>8} {'Actual':>8} "
            f"{'Calibrated':>10} {'RawGap':>8} {'CalGap':>8}"
        )
        for bucket_start in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
            bucket_end = bucket_start + 0.1
            mask = (probs >= bucket_start) & (probs < bucket_end)
            if mask.sum() < 10:
                continue
            bucket_probs = probs[mask]
            bucket_outcomes = outcomes[mask]
            bucket_calibrated = calibrated[mask]

            avg_raw = bucket_probs.mean()
            avg_actual = bucket_outcomes.mean()
            avg_cal = bucket_calibrated.mean()
            raw_gap = avg_raw - avg_actual
            cal_gap = avg_cal - avg_actual

            raw_status = "OVER" if raw_gap > 0.05 else "UNDER" if raw_gap < -0.05 else "OK"
            cal_status = "OVER" if cal_gap > 0.05 else "UNDER" if cal_gap < -0.05 else "OK"

            print(
                f"  {bucket_start:.1f}-{bucket_end:.1f}   {mask.sum():>6} "
                f"{avg_raw:>8.3f} {avg_actual:>8.3f} {avg_cal:>10.3f} "
                f"{raw_gap:>+8.3f} {raw_status:<5} {cal_gap:>+8.3f} {cal_status}"
            )

        # Overall metrics
        raw_brier = brier_score_loss(outcomes, probs)
        cal_brier = brier_score_loss(outcomes, calibrated)
        raw_logloss = log_loss(outcomes, np.clip(probs, 0.01, 0.99))
        cal_logloss = log_loss(outcomes, np.clip(calibrated, 0.01, 0.99))

        brier_improve = (raw_brier - cal_brier) / raw_brier * 100 if raw_brier > 0 else 0
        ll_improve = (raw_logloss - cal_logloss) / raw_logloss * 100 if raw_logloss > 0 else 0

        print(
            f"\n  Brier score: {raw_brier:.4f} (raw) -> {cal_brier:.4f} (calibrated) [{brier_improve:+.1f}%]"
        )
        print(
            f"  Log loss:    {raw_logloss:.4f} (raw) -> {cal_logloss:.4f} (calibrated) [{ll_improve:+.1f}%]"
        )

        # Save calibrator
        cal_path = CALIBRATOR_DIR / f"{market}_calibrator.pkl"
        with open(cal_path, "wb") as f:
            pickle.dump(calibrator, f)
        print(f"\n  Saved: {cal_path}")

        # Show key probability mappings
        test_probs = np.array(
            [0.30, 0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
        )
        test_cal = calibrator.predict(test_probs)
        print(f"\n  Probability mapping (raw -> calibrated):")
        for raw, cal in zip(test_probs, test_cal):
            shift = cal - raw
            print(f"    {raw:.2f} -> {cal:.3f} ({shift:+.3f})")

        calibrators[market] = calibrator

    return calibrators


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════


async def main():
    print("STEP 1: Collecting calibration data from production models...")
    cal_data = await collect_calibration_data()

    print(f"\nData collected per market:")
    for market, data in sorted(cal_data.items()):
        print(
            f"  {market}: {len(data['probs'])} data points, "
            f"mean prob: {np.mean(data['probs']):.3f}, "
            f"actual rate: {np.mean(data['outcomes']):.3f}"
        )

    print("\nSTEP 2: Fitting calibrators...")
    calibrators = fit_calibrators(cal_data)

    print(f"\n{'=' * 60}")
    print(f"CALIBRATORS BUILT: {list(calibrators.keys())}")
    print(f"Files saved in: {CALIBRATOR_DIR}/")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
