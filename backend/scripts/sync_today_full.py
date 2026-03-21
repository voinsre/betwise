"""Full sync for today's fixtures — odds, last20, H2H, standings, injuries, predictions.

Connects to localhost:5432. Syncs ALL data needed for prediction engine.
Then runs predictions on every fixture and prints a summary.

Run from backend/:
    python scripts/sync_today_full.py
"""

import asyncio
import os
import sys
import time

# Setup path and env
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://betwise:changeme@localhost:5432/betwise",
)

import logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Show info for our services
logging.getLogger("app.services.data_sync").setLevel(logging.INFO)
logging.getLogger("app.services.prediction_engine").setLevel(logging.INFO)
# Keep API-Football at WARNING to reduce noise
logging.getLogger("app.services.api_football").setLevel(logging.WARNING)

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.fixture import Fixture
from app.models.odds import Odds
from app.models.prediction import Prediction
from app.models.team import Team
from app.services.api_football import APIFootballClient
from app.services.league_config import get_active_league_ids
from app.services.data_sync import DataSyncService
from app.services.prediction_engine import PredictionEngine


def stars(confidence: int) -> str:
    if confidence >= 80:
        return "\u2605\u2605\u2605"
    if confidence >= 65:
        return "\u2605\u2605\u2606"
    return "\u2605\u2606\u2606"


async def main():
    db_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    today = date.today()
    today_str = today.isoformat()

    print("\n" + "=" * 80)
    print("  BETWISE — FULL TODAY SYNC")
    print(f"  Date: {today_str}")
    print("=" * 80)

    t_start = time.time()

    # --- Step 1: Sync today's fixtures from API ---
    print(f"\n[1/6] Syncing fixtures for {today_str}...")
    async with APIFootballClient() as client:
        sync = DataSyncService(session_factory, client)

        fixture_count = await sync.sync_fixtures_for_date(today_str)
        print(f"       Synced {fixture_count} fixtures in target leagues")

        # Load all today's fixtures from DB
        async with session_factory() as session:
            result = await session.execute(
                select(Fixture)
                .where(Fixture.date == today, Fixture.league_id.in_(get_active_league_ids()))
                .order_by(Fixture.kickoff_time)
            )
            fixtures = list(result.scalars().all())

        print(f"       {len(fixtures)} fixtures in DB for today")
        if not fixtures:
            print("\n  No fixtures found for today. Exiting.")
            await engine.dispose()
            return

        # --- Step 2: Sync odds for every fixture ---
        print(f"\n[2/6] Syncing odds for {len(fixtures)} fixtures...")
        odds_total = 0
        fixtures_with_odds = 0
        for i, fx in enumerate(fixtures):
            try:
                count = await sync.sync_odds(fx.id)
                odds_total += count
                if count > 0:
                    fixtures_with_odds += 1
                if (i + 1) % 10 == 0:
                    print(f"       Progress: {i + 1}/{len(fixtures)} fixtures ({odds_total} odds rows)")
            except Exception as e:
                print(f"       WARNING: Odds sync failed for fixture {fx.id}: {e}")

        print(f"       Done: {odds_total} odds rows, {fixtures_with_odds}/{len(fixtures)} fixtures have odds")

        # --- Step 3: Sync team last20 for all teams ---
        print(f"\n[3/6] Syncing team last20 form data...")
        team_ids_done = set()
        last20_count = 0
        for i, fx in enumerate(fixtures):
            for team_id in (fx.home_team_id, fx.away_team_id):
                if team_id in team_ids_done:
                    continue
                team_ids_done.add(team_id)
                try:
                    count = await sync.sync_team_last20(team_id, fx.league_id, fx.season)
                    last20_count += count
                except Exception as e:
                    print(f"       WARNING: Last20 sync failed for team {team_id}: {e}")
            if (i + 1) % 10 == 0:
                print(f"       Progress: {i + 1}/{len(fixtures)} fixtures ({len(team_ids_done)} teams, {last20_count} rows)")

        print(f"       Done: {len(team_ids_done)} teams synced, {last20_count} last20 rows")

        # --- Step 4: Sync H2H for all fixture matchups ---
        print(f"\n[4/6] Syncing head-to-head data...")
        h2h_count = 0
        for i, fx in enumerate(fixtures):
            try:
                count = await sync.sync_head_to_head(fx.home_team_id, fx.away_team_id)
                h2h_count += count
            except Exception as e:
                print(f"       WARNING: H2H sync failed for fixture {fx.id}: {e}")
            if (i + 1) % 10 == 0:
                print(f"       Progress: {i + 1}/{len(fixtures)} ({h2h_count} H2H rows)")

        print(f"       Done: {h2h_count} H2H rows")

        # --- Step 5: Sync standings for all leagues with fixtures today ---
        print(f"\n[5/6] Syncing standings and injuries...")
        league_seasons_done = set()
        standings_count = 0
        injuries_count = 0
        for fx in fixtures:
            key = (fx.league_id, fx.season)
            if key not in league_seasons_done:
                league_seasons_done.add(key)
                try:
                    count = await sync.sync_standings(fx.league_id, fx.season)
                    standings_count += count
                except Exception as e:
                    print(f"       WARNING: Standings sync failed for league {fx.league_id}: {e}")

            try:
                count = await sync.sync_injuries(fx.id)
                injuries_count += count
            except Exception as e:
                print(f"       WARNING: Injuries sync failed for fixture {fx.id}: {e}")

        print(f"       Done: {standings_count} standing rows ({len(league_seasons_done)} leagues), {injuries_count} injuries")

    # --- Step 6: Run prediction engine on ALL today's fixtures ---
    print(f"\n[6/6] Running prediction engine on {len(fixtures)} fixtures...")
    pred_engine = PredictionEngine(session_factory)
    pred_engine.load_models()

    total_predictions = 0
    total_value_bets = 0
    fixtures_with_predictions = 0

    for i, fx in enumerate(fixtures):
        try:
            preds = await pred_engine.predict_fixture(fx.id)
            if preds:
                fixtures_with_predictions += 1
                total_predictions += len(preds)
                total_value_bets += sum(1 for p in preds if p.is_value_bet)
        except Exception as e:
            print(f"       WARNING: Prediction failed for fixture {fx.id}: {e}")
        if (i + 1) % 10 == 0:
            print(f"       Progress: {i + 1}/{len(fixtures)} ({total_predictions} predictions, {total_value_bets} value bets)")

    t_elapsed = time.time() - t_start

    # --- Summary ---
    print("\n" + "=" * 80)
    print("  SYNC COMPLETE")
    print("=" * 80)
    print(f"  Time elapsed:              {t_elapsed:.0f}s ({t_elapsed/60:.1f} min)")
    print(f"  Fixtures synced:           {fixture_count}")
    print(f"  Fixtures with odds:        {fixtures_with_odds}/{len(fixtures)}")
    print(f"  Teams synced (last20):     {len(team_ids_done)}")
    print(f"  H2H matchups synced:       {len(fixtures)}")
    print(f"  Standings synced:          {len(league_seasons_done)} leagues")
    print(f"  Injuries synced:           {injuries_count}")
    print(f"  Total predictions:         {total_predictions}")
    print(f"  Fixtures with predictions: {fixtures_with_predictions}/{len(fixtures)}")
    print(f"  Total value bets:          {total_value_bets}")

    # --- Top 10 Value Bets ---
    print(f"\n{'─' * 80}")
    print("  TOP 10 VALUE BETS")
    print(f"{'─' * 80}")

    value_bets = await pred_engine.get_value_bets_for_date(today)
    if not value_bets:
        print("  No value bets found.")
    else:
        print(f"  {'#':<3} {'Match':<35} {'Market':<6} {'Selection':<12} {'Odd':>5} {'Edge%':>7} {'Conf':>5} {'Stars'}")
        print(f"  {'─'*3} {'─'*35} {'─'*6} {'─'*12} {'─'*5} {'─'*7} {'─'*5} {'─'*5}")
        for i, vb in enumerate(value_bets[:10], 1):
            match_name = f"{vb['home_team']} vs {vb['away_team']}"
            if len(match_name) > 33:
                match_name = match_name[:32] + "."
            print(
                f"  {i:<3} {match_name:<35} {vb['market']:<6} {vb['selection']:<12} "
                f"{vb['best_odd']:>5.2f} {vb['edge']*100:>+6.1f}% {vb['confidence_score']:>5} {stars(vb['confidence_score'])}"
            )

        if len(value_bets) > 10:
            print(f"\n  ... and {len(value_bets) - 10} more value bets")

    print("\n" + "=" * 80 + "\n")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
