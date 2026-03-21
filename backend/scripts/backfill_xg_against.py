"""
One-time backfill: populate xg_against in team_last20 and xg_home/xg_away
in head_to_head from existing fixture_statistics data.

Run from project root:
    DATABASE_URL=postgresql+asyncpg://betwise:betwise@localhost:5432/betwise \
    python backend/scripts/backfill_xg_against.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

# Set local DATABASE_URL BEFORE load_dotenv so .env doesn't override it
os.environ["DATABASE_URL"] = "postgresql+asyncpg://betwise:BetWise2026Secure@localhost:5432/betwise?ssl=disable"

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.fixture_statistics import FixtureStatistics
from app.models.head_to_head import HeadToHead
from app.models.team_last20 import TeamLast20

DATABASE_URL = os.environ["DATABASE_URL"]


async def backfill_team_last20_xg_against(session: AsyncSession) -> int:
    """Fill xg_against for all TeamLast20 rows where it's NULL."""
    rows = (await session.execute(
        select(TeamLast20).where(TeamLast20.xg_against.is_(None))
    )).scalars().all()

    updated = 0
    for row in rows:
        opp_stat = (await session.execute(
            select(FixtureStatistics.expected_goals).where(
                FixtureStatistics.fixture_id == row.fixture_id,
                FixtureStatistics.team_id == row.opponent_id,
            )
        )).scalar_one_or_none()

        if opp_stat is not None:
            row.xg_against = opp_stat
            updated += 1

        if updated % 500 == 0 and updated > 0:
            await session.flush()
            print(f"  team_last20: {updated} rows updated so far...")

    await session.commit()
    return updated


async def backfill_h2h_xg(session: AsyncSession) -> int:
    """Fill xg_home/xg_away for all HeadToHead rows where both are NULL."""
    rows = (await session.execute(
        select(HeadToHead).where(
            HeadToHead.xg_home.is_(None),
            HeadToHead.xg_away.is_(None),
        )
    )).scalars().all()

    updated = 0
    for row in rows:
        # home_team_id is stored on the H2H row
        home_stat = (await session.execute(
            select(FixtureStatistics.expected_goals).where(
                FixtureStatistics.fixture_id == row.fixture_id,
                FixtureStatistics.team_id == row.home_team_id,
            )
        )).scalar_one_or_none()

        # Away team is whichever of team1/team2 is NOT home
        away_team_id = row.team2_id if row.home_team_id == row.team1_id else row.team1_id
        away_stat = (await session.execute(
            select(FixtureStatistics.expected_goals).where(
                FixtureStatistics.fixture_id == row.fixture_id,
                FixtureStatistics.team_id == away_team_id,
            )
        )).scalar_one_or_none()

        if home_stat is not None or away_stat is not None:
            row.xg_home = home_stat
            row.xg_away = away_stat
            updated += 1

        if updated % 500 == 0 and updated > 0:
            await session.flush()
            print(f"  head_to_head: {updated} rows updated so far...")

    await session.commit()
    return updated


async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        print("=== Backfilling xg_against in team_last20 ===")
        count1 = await backfill_team_last20_xg_against(session)
        print(f"Done: {count1} team_last20 rows updated with xg_against")

    async with session_factory() as session:
        print("\n=== Backfilling xg_home/xg_away in head_to_head ===")
        count2 = await backfill_h2h_xg(session)
        print(f"Done: {count2} head_to_head rows updated with xG")

    await engine.dispose()
    print(f"\nTotal: {count1 + count2} rows backfilled")


if __name__ == "__main__":
    asyncio.run(main())
