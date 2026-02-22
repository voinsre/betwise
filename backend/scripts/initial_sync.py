"""
Initial data sync: populate the database with leagues, today's fixtures,
and full data for one sample fixture.

Run from the backend/ directory:
    python scripts/initial_sync.py
"""

import asyncio
import logging
import os
import sys
from datetime import date as date_type

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
load_dotenv(env_path)

# Override DATABASE_URL for local execution (localhost, not Docker 'db')
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://betwise:changeme@localhost:5432/betwise",
)

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.fixture import Fixture
from app.models.fixture_statistics import FixtureStatistics
from app.models.head_to_head import HeadToHead
from app.models.injury import Injury
from app.models.league import League
from app.models.odds import Odds
from app.models.standing import Standing
from app.models.team import Team
from app.models.team_last20 import TeamLast20
from app.services.api_football import APIFootballClient, TARGET_LEAGUE_IDS
from app.services.data_sync import DataSyncService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("initial_sync")

DB_URL = os.environ["DATABASE_URL"]


async def print_table_counts(session: AsyncSession):
    """Print row counts for all key tables."""
    tables = [
        ("leagues", League),
        ("teams", Team),
        ("fixtures", Fixture),
        ("fixture_statistics", FixtureStatistics),
        ("team_last20", TeamLast20),
        ("head_to_head", HeadToHead),
        ("odds", Odds),
        ("standings", Standing),
        ("injuries", Injury),
    ]
    print("\n" + "=" * 50)
    print("DATABASE TABLE COUNTS")
    print("=" * 50)
    for name, model in tables:
        result = await session.execute(select(func.count()).select_from(model))
        count = result.scalar()
        print(f"  {name:<25} {count:>6} rows")
    print("=" * 50)


async def main():
    api_key = os.getenv("API_FOOTBALL_KEY", "")
    if not api_key:
        print("ERROR: API_FOOTBALL_KEY not set in .env")
        sys.exit(1)

    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with APIFootballClient(api_key=api_key) as client:
        sync = DataSyncService(session_factory, client)

        # ── Step 1: Sync all leagues ────────────────────────
        print("\n[1] Syncing all leagues...")
        league_count = await sync.sync_leagues()
        print(f"    Upserted {league_count} leagues")

        # Show our target leagues
        async with session_factory() as session:
            result = await session.execute(
                select(League).where(League.is_active == True).order_by(League.id)
            )
            active = result.scalars().all()
            print(f"    Active target leagues: {len(active)}")
            for lg in active:
                print(f"      {lg.id:>4}  {lg.name:<25} ({lg.country}) season={lg.season}")

        # ── Step 2: Sync today's fixtures ───────────────────
        today_str = "2026-02-22"
        today = date_type.fromisoformat(today_str)
        print(f"\n[2] Syncing fixtures for {today_str}...")
        fx_count = await sync.sync_fixtures_for_date(today_str)
        print(f"    Upserted {fx_count} fixtures in target leagues")

        # ── Step 3: Pick one fixture for full sync ──────────
        async with session_factory() as session:
            # Try Premier League first, fall back to any target league
            for target_league in [39, 140, 135, 78, 61]:
                result = await session.execute(
                    select(Fixture).where(
                        Fixture.league_id == target_league,
                        Fixture.date == today,
                    ).limit(1)
                )
                sample = result.scalar_one_or_none()
                if sample:
                    break

            if not sample:
                # Fall back to any fixture today
                result = await session.execute(
                    select(Fixture).where(Fixture.date == today).limit(1)
                )
                sample = result.scalar_one_or_none()

            if not sample:
                print("\n[3] No fixtures found for today. Skipping detailed sync.")
                async with session_factory() as s:
                    await print_table_counts(s)
                await engine.dispose()
                return

            # Get team names
            home = await session.get(Team, sample.home_team_id)
            away = await session.get(Team, sample.away_team_id)
            league = await session.get(League, sample.league_id)

        home_name = home.name if home else f"Team {sample.home_team_id}"
        away_name = away.name if away else f"Team {sample.away_team_id}"
        league_name = league.name if league else f"League {sample.league_id}"

        print(f"\n[3] Full sync for: {home_name} vs {away_name} ({league_name})")
        print(f"    Fixture ID: {sample.id}, League ID: {sample.league_id}, Season: {sample.season}")

        # ── Step 3a: Team last 20 for both teams ────────────
        print(f"\n    [3a] Syncing last 20 for {home_name} (id={sample.home_team_id})...")
        home_l20 = await sync.sync_team_last20(sample.home_team_id, sample.league_id, sample.season)
        print(f"         → {home_l20} rows")

        print(f"    [3b] Syncing last 20 for {away_name} (id={sample.away_team_id})...")
        away_l20 = await sync.sync_team_last20(sample.away_team_id, sample.league_id, sample.season)
        print(f"         → {away_l20} rows")

        # ── Step 3b: Head to head ───────────────────────────
        print(f"\n    [3c] Syncing H2H {home_name} vs {away_name}...")
        h2h_count = await sync.sync_head_to_head(sample.home_team_id, sample.away_team_id)
        print(f"         → {h2h_count} H2H records")

        # ── Step 3c: Odds ───────────────────────────────────
        print(f"\n    [3d] Syncing odds for fixture {sample.id}...")
        odds_count = await sync.sync_odds(sample.id)
        print(f"         → {odds_count} odds rows")

        # ── Step 3d: Injuries ───────────────────────────────
        print(f"\n    [3e] Syncing injuries for fixture {sample.id}...")
        inj_count = await sync.sync_injuries(sample.id)
        print(f"         → {inj_count} injury records")

        # ── Step 3e: Standings ──────────────────────────────
        print(f"\n    [3f] Syncing standings for {league_name} season {sample.season}...")
        stand_count = await sync.sync_standings(sample.league_id, sample.season)
        print(f"         → {stand_count} standing rows")

    # ── Final: Print all table counts ───────────────────────
    async with session_factory() as session:
        await print_table_counts(session)

    await engine.dispose()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
