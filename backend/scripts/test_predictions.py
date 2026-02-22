"""
Test the Poisson prediction model, value detector, and bankroll manager
against live DB data.

Run from the backend/ directory:
    python scripts/test_predictions.py
"""

import asyncio
import logging
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
load_dotenv(env_path)

# Override DATABASE_URL for local execution (localhost, not Docker 'db')
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://betwise:changeme@localhost:5432/betwise",
)

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.fixture import Fixture
from app.models.league import League
from app.models.odds import Odds
from app.models.team import Team
from app.models.team_last20 import TeamLast20
from app.services.bankroll import BankrollManager
from app.services.poisson_model import PoissonPredictor
from app.services.value_detector import ValueDetector

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("test_predictions")

DB_URL = os.environ["DATABASE_URL"]


async def main():
    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    # ── Find a fixture to test ────────────────────────────────
    async with session_factory() as session:
        fixture = None
        # Try top-5 leagues first
        for target_league in [39, 140, 135, 78, 61]:
            result = await session.execute(
                select(Fixture)
                .where(Fixture.league_id == target_league)
                .limit(1)
            )
            fixture = result.scalar_one_or_none()
            if fixture:
                break

        if not fixture:
            result = await session.execute(select(Fixture).limit(1))
            fixture = result.scalar_one_or_none()

        if not fixture:
            print("ERROR: No fixtures found in the database.")
            await engine.dispose()
            return

        # Load team/league names
        home = await session.get(Team, fixture.home_team_id)
        away = await session.get(Team, fixture.away_team_id)
        league = await session.get(League, fixture.league_id)

        # Count available data
        h_count = (
            await session.execute(
                select(func.count())
                .select_from(TeamLast20)
                .where(TeamLast20.team_id == fixture.home_team_id)
            )
        ).scalar()
        a_count = (
            await session.execute(
                select(func.count())
                .select_from(TeamLast20)
                .where(TeamLast20.team_id == fixture.away_team_id)
            )
        ).scalar()
        odds_count = (
            await session.execute(
                select(func.count())
                .select_from(Odds)
                .where(Odds.fixture_id == fixture.id)
            )
        ).scalar()

    home_name = home.name if home else f"Team {fixture.home_team_id}"
    away_name = away.name if away else f"Team {fixture.away_team_id}"
    league_name = league.name if league else f"League {fixture.league_id}"

    # ══════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  BETWISE POISSON PREDICTION MODEL — TEST RUN")
    print("=" * 70)
    print(f"\n  Match:    {home_name} vs {away_name}")
    print(f"  League:   {league_name} (season {fixture.season})")
    print(f"  Fixture:  ID {fixture.id}, Date {fixture.date}, Status {fixture.status}")
    print(f"  Data:     {h_count} last20 (home team), {a_count} last20 (away team), {odds_count} odds rows")

    # ── Run Poisson model ────────────────────────────────────
    print("\n" + "-" * 70)
    print("  POISSON MODEL PARAMETERS")
    print("-" * 70)

    predictor = PoissonPredictor(session_factory)
    result = await predictor.predict(fixture.id)

    print(f"\n  Lambda (home):    {result['lambda_home']:.4f}  ({home_name} expected goals)")
    print(f"  Lambda (away):    {result['lambda_away']:.4f}  ({away_name} expected goals)")
    print(f"  Expected total:   {result['lambda_home'] + result['lambda_away']:.4f}")
    print(f"\n  Home attack:      {result['home_attack']:.4f}  (>1 = above avg)")
    print(f"  Home defense:     {result['home_defense']:.4f}  (>1 = leaky defense)")
    print(f"  Away attack:      {result['away_attack']:.4f}")
    print(f"  Away defense:     {result['away_defense']:.4f}")
    print(f"  Home advantage:   {result['home_advantage']:.4f}")
    print(f"  League avg goals: {result['league_avg_goals']:.2f} per game")

    # ── Market probabilities ─────────────────────────────────
    print("\n" + "-" * 70)
    print("  MARKET PROBABILITIES")
    print("-" * 70)

    # 1X2
    p = result["markets"]["1x2"]
    print(f"\n  1X2 (Match Winner):")
    print(f"    Home ({home_name:<20}):  {p['Home']*100:6.2f}%")
    print(f"    Draw:                        {p['Draw']*100:6.2f}%")
    print(f"    Away ({away_name:<20}):  {p['Away']*100:6.2f}%")

    # Over/Under
    p = result["markets"]["ou25"]
    print(f"\n  Over/Under 2.5 Goals:")
    print(f"    Over 2.5:    {p['Over 2.5']*100:6.2f}%")
    print(f"    Under 2.5:   {p['Under 2.5']*100:6.2f}%")

    # BTTS
    p = result["markets"]["btts"]
    print(f"\n  Both Teams To Score:")
    print(f"    Yes:  {p['Yes']*100:6.2f}%")
    print(f"    No:   {p['No']*100:6.2f}%")

    # Double Chance
    p = result["markets"]["dc"]
    print(f"\n  Double Chance:")
    print(f"    1X (Home or Draw):  {p['1X']*100:6.2f}%")
    print(f"    12 (Home or Away):  {p['12']*100:6.2f}%")
    print(f"    X2 (Draw or Away):  {p['X2']*100:6.2f}%")

    # HT/FT
    p = result["markets"]["htft"]
    print(f"\n  Half-Time / Full-Time:")
    sorted_htft = sorted(p.items(), key=lambda x: x[1], reverse=True)
    for combo, prob in sorted_htft:
        bar = "#" * int(prob * 100)
        print(f"    {combo}:  {prob*100:6.2f}%  {bar}")

    # Combos
    p = result["markets"]["combo"]
    print(f"\n  Best Combo Bets (Top 5):")
    for combo, prob in p.items():
        print(f"    {combo:<25}  {prob*100:6.2f}%")

    # ── Most likely scorelines ───────────────────────────────
    print(f"\n  Most Likely Scorelines:")
    matrix = result["matrix"]
    scorelines = []
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            scorelines.append((i, j, matrix[i][j]))
    scorelines.sort(key=lambda x: x[2], reverse=True)
    for home_g, away_g, prob in scorelines[:8]:
        print(f"    {home_g}-{away_g}:  {prob*100:5.2f}%")

    # ── Value detection ──────────────────────────────────────
    print("\n" + "-" * 70)
    print("  VALUE BET ANALYSIS")
    print("-" * 70)

    detector = ValueDetector()
    async with session_factory() as session:
        value_bets = await detector.detect(session, result)

    if not value_bets:
        print("\n  No odds data found for this fixture.")
    else:
        # All comparisons table
        print(f"\n  {'Market':<8} {'Selection':<14} {'Model%':>7} {'Odds':>6} {'Impl%':>7} {'Edge%':>7} {'EV':>7} {'Value?':>7}")
        print(f"  {'─'*8} {'─'*14} {'─'*7} {'─'*6} {'─'*7} {'─'*7} {'─'*7} {'─'*7}")

        for vb in value_bets:
            marker = "  ★" if vb["is_value"] else ""
            print(
                f"  {vb['market']:<8} {vb['label']:<14} "
                f"{vb['model_prob']*100:6.2f}% "
                f"{vb['best_odd']:5.2f} "
                f"{vb['implied_prob']*100:6.2f}% "
                f"{vb['edge']*100:+6.2f}% "
                f"{vb['ev']:+6.4f}"
                f"{marker}"
            )

        # Value bets summary
        actual_values = [vb for vb in value_bets if vb["is_value"]]
        print(f"\n  ★ VALUE BETS FOUND: {len(actual_values)} "
              f"(edge > {detector.min_edge*100:.0f}%, odds {detector.odds_min:.2f}–{detector.odds_max:.2f})")

        if actual_values:
            print("\n" + "-" * 70)
            print("  TOP VALUE BETS + KELLY STAKES")
            print("-" * 70)

            bankroll_mgr = BankrollManager()
            bankroll = 1000.0

            for i, vb in enumerate(actual_values[:3], 1):
                stake = bankroll_mgr.calc_kelly_stake(
                    vb["model_prob"], vb["best_odd"], bankroll
                )
                potential_return = stake * vb["best_odd"]
                profit = potential_return - stake

                print(f"\n  #{i}  {vb['market'].upper()} — {vb['label']}")
                print(f"      Model probability:  {vb['model_prob']*100:.2f}%")
                print(f"      Best odds:          {vb['best_odd']:.2f} ({vb['bookmaker']})")
                print(f"      Implied probability:{vb['implied_prob']*100:.2f}%")
                print(f"      Edge:               {vb['edge']*100:+.2f}%")
                print(f"      Expected value:     {vb['ev']:+.4f}")
                print(f"      Kelly stake:        ${stake:.2f} / ${bankroll:.0f} "
                      f"({stake/bankroll*100:.1f}% of bankroll)")
                print(f"      Potential return:    ${potential_return:.2f} "
                      f"(profit ${profit:.2f})")

            # Accumulator example
            if len(actual_values) >= 2:
                print(f"\n  ACCUMULATOR (top {min(len(actual_values), 3)} value bets combined):")
                acca_legs = [
                    {
                        "blended_probability": vb["model_prob"],
                        "best_odd": vb["best_odd"],
                    }
                    for vb in actual_values[:3]
                ]
                acca_stake = bankroll_mgr.calc_accumulator_stake(acca_legs, bankroll)
                combined_odds = 1.0
                for leg in acca_legs:
                    combined_odds *= leg["best_odd"]
                print(f"      Combined odds:    {combined_odds:.2f}")
                print(f"      Kelly stake:      ${acca_stake:.2f}")
                print(f"      Potential return: ${acca_stake * combined_odds:.2f}")

    # ══════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  TEST COMPLETE")
    print("=" * 70 + "\n")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
