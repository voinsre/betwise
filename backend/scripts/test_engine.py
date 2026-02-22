"""Test script for Phase 5 — Prediction Engine.

Runs the prediction engine on today's fixtures (or a specified date),
prints top 10 value bets, and builds a sample ticket.

Run from the backend/ directory:
    python scripts/test_engine.py [YYYY-MM-DD]
"""

import asyncio
import os
import sys
from datetime import date

# Setup path and env
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://betwise:BetWise2026Secure@localhost:5432/betwise"
)

import logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("app.services.prediction_engine").setLevel(logging.INFO)

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.fixture import Fixture
from app.models.team import Team
from app.services.prediction_engine import PredictionEngine
from app.services.ticket_builder import TicketBuilder


async def main():
    target_date = date.today()
    if len(sys.argv) > 1:
        try:
            target_date = date.fromisoformat(sys.argv[1])
        except ValueError:
            print(f"Invalid date: {sys.argv[1]}. Use YYYY-MM-DD format.")
            return

    db_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print("\n" + "=" * 70)
    print("  BETWISE PREDICTION ENGINE TEST")
    print("=" * 70)
    print(f"  Date: {target_date}")

    # Check fixtures for this date
    async with session_factory() as session:
        count_result = await session.execute(
            select(func.count(Fixture.id)).where(Fixture.date == target_date)
        )
        fixture_count = count_result.scalar() or 0
        print(f"  Fixtures found: {fixture_count}")

    if fixture_count == 0:
        print("\n  No fixtures found for this date.")
        print("  Try a date with data, e.g.: python scripts/test_engine.py 2025-03-15")

        # Show some dates with fixtures
        async with session_factory() as session:
            result = await session.execute(
                select(Fixture.date, func.count(Fixture.id))
                .where(Fixture.status == "FT")
                .group_by(Fixture.date)
                .order_by(Fixture.date.desc())
                .limit(10)
            )
            dates = result.all()
            if dates:
                print("\n  Recent dates with fixtures:")
                for d, c in dates:
                    print(f"    {d}: {c} fixtures")

        await engine.dispose()
        return

    # Initialize prediction engine
    pred_engine = PredictionEngine(session_factory)
    pred_engine.load_models()

    print(f"\n  ML models loaded: {list(pred_engine.ml._models.keys())}")

    # Run predictions
    print(f"\n  Running predictions for {target_date}...")
    result = await pred_engine.predict_all_for_date(target_date)

    print(f"\n  Results:")
    print(f"    Fixtures processed: {result['fixtures_processed']}")
    print(f"    Total predictions:  {result['total_predictions']}")
    print(f"    Value bets found:   {result['value_bets_found']}")
    print(f"    Errors:             {result['errors']}")

    # Top 10 value bets
    value_bets = await pred_engine.get_value_bets_for_date(target_date)

    if value_bets:
        print(f"\n{'─' * 70}")
        print(f"  TOP {min(10, len(value_bets))} VALUE BETS")
        print(f"{'─' * 70}")
        print(
            f"  {'#':>2} {'Match':<35} {'Market':<6} {'Selection':<12} "
            f"{'Odd':>5} {'Edge':>7} {'Conf':>4} {'EV':>7}"
        )
        print(f"  {'─'*2} {'─'*35} {'─'*6} {'─'*12} {'─'*5} {'─'*7} {'─'*4} {'─'*7}")

        for i, vb in enumerate(value_bets[:10], 1):
            match = f"{vb['home_team'][:16]} v {vb['away_team'][:16]}"
            print(
                f"  {i:>2} {match:<35} {vb['market']:<6} {vb['selection']:<12} "
                f"{vb['best_odd']:>5.2f} {vb['edge']:>+6.1%} {vb['confidence_score']:>4} "
                f"{vb['expected_value']:>+6.2f}"
            )
    else:
        print("\n  No value bets found.")

    # Build sample ticket
    if len(value_bets) >= 3:
        print(f"\n{'─' * 70}")
        print(f"  SAMPLE TICKET (3 games)")
        print(f"{'─' * 70}")

        builder = TicketBuilder(session_factory, pred_engine)
        ticket = await builder.build_ticket(
            target_date=target_date,
            num_games=min(3, len(value_bets)),
            bankroll=1000.0,
        )

        if "error" in ticket:
            print(f"  Error: {ticket['error']}")
        else:
            for j, game in enumerate(ticket["games"], 1):
                print(
                    f"  {j}. {game['home_team']} v {game['away_team']} — "
                    f"{game['market']} {game['selection']} @ {game['odd']:.2f} "
                    f"(edge: {game['edge']:+.1%})"
                )
            print(f"\n  Combined odds:        {ticket['combined_odds']:.2f}")
            print(f"  Combined probability: {ticket['combined_probability_pct']:.1f}%")
            print(f"  Kelly stake:          ${ticket['kelly_stake']:.2f} ({ticket['kelly_stake_pct']:.1f}% of $1000)")

    print("\n" + "=" * 70 + "\n")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
