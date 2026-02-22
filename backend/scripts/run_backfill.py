"""
Historical data backfill for all 15 target leagues × 3 seasons.

Modes:
    python scripts/run_backfill.py              # dry run (estimate only)
    python scripts/run_backfill.py --backfill   # actual backfill

Dry run fetches fixture counts from the API (45 calls) and prints
estimated totals without syncing any statistics.

Backfill has resume capability: fixtures and stats already in the DB
are skipped automatically.
"""

import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
load_dotenv(env_path)

# Override DATABASE_URL for local execution (localhost, not Docker 'db')
os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://betwise:BetWise2026Secure@localhost:5432/betwise"
)

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.fixture import Fixture
from app.models.fixture_statistics import FixtureStatistics
from app.models.team_last20 import TeamLast20
from app.services.api_football import (
    APIFootballClient,
    BACKFILL_SEASONS,
    TARGET_LEAGUE_IDS,
)
from app.services.data_sync import DataSyncService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("backfill")

DB_URL = os.environ["DATABASE_URL"]

LEAGUE_NAMES = {
    39: "Premier League",
    140: "La Liga",
    135: "Serie A",
    78: "Bundesliga",
    61: "Ligue 1",
    2: "Champions League",
    3: "Europa League",
    88: "Eredivisie",
    94: "Primeira Liga",
    179: "Premiership",
    203: "Super Lig",
    144: "Pro League",
    40: "Championship",
    136: "Serie B",
    79: "2. Bundesliga",
}


# ══════════════════════════════════════════════════════════════
#  DRY RUN
# ══════════════════════════════════════════════════════════════


async def dry_run(session_factory, client):
    """Count fixtures for all leagues+seasons and estimate API calls."""
    print("\n" + "=" * 75)
    print("  BACKFILL DRY RUN — ESTIMATING API CALLS")
    print("=" * 75)

    results = []
    api_calls_used = 0

    for league_id in sorted(TARGET_LEAGUE_IDS):
        name = LEAGUE_NAMES.get(league_id, f"League {league_id}")

        for season in BACKFILL_SEASONS:
            # ── Check what's already in DB ────────────────────
            async with session_factory() as session:
                db_fx = (
                    await session.execute(
                        select(func.count())
                        .select_from(Fixture)
                        .where(
                            Fixture.league_id == league_id,
                            Fixture.season == season,
                            Fixture.status == "FT",
                        )
                    )
                ).scalar() or 0

                db_stats = (
                    await session.execute(
                        select(func.count(func.distinct(FixtureStatistics.fixture_id)))
                        .where(
                            FixtureStatistics.fixture_id.in_(
                                select(Fixture.id).where(
                                    Fixture.league_id == league_id,
                                    Fixture.season == season,
                                )
                            )
                        )
                    )
                ).scalar() or 0

            # ── Fetch from API (1 call) ───────────────────────
            try:
                api_fixtures = await client.get_fixtures_by_league_season(
                    league_id, season, status="FT"
                )
                api_calls_used += 1
            except Exception as exc:
                print(f"  ERROR  {name:<22} {season}  {exc}")
                results.append({
                    "league": name, "league_id": league_id, "season": season,
                    "api_fx": 0, "db_fx": db_fx, "db_stats": db_stats,
                    "teams": 0, "status": "ERROR",
                    "stats_needed": 0, "team_calls": 0,
                })
                continue

            api_count = len(api_fixtures)

            # Count unique teams
            teams = set()
            for fx in api_fixtures:
                t = fx.get("teams", {})
                h = t.get("home", {}).get("id")
                a = t.get("away", {}).get("id")
                if h:
                    teams.add(h)
                if a:
                    teams.add(a)
            num_teams = len(teams)

            # ── Determine status ──────────────────────────────
            if db_fx >= api_count and db_stats >= api_count:
                status = "SKIP"
                stats_needed = 0
                team_calls = 0
            elif db_fx >= api_count:
                status = "STATS ONLY"
                stats_needed = api_count - db_stats
                team_calls = num_teams
            else:
                status = "FULL"
                stats_needed = api_count
                team_calls = num_teams

            db_note = ""
            if db_fx > 0:
                db_note = f"  (DB: {db_fx} fx, {db_stats} stats)"

            print(
                f"  {name:<22} {season}  "
                f"{api_count:>4} fixtures  {num_teams:>2} teams  "
                f"[{status:<10}]{db_note}"
            )

            results.append({
                "league": name, "league_id": league_id, "season": season,
                "api_fx": api_count, "db_fx": db_fx, "db_stats": db_stats,
                "teams": num_teams, "status": status,
                "stats_needed": stats_needed, "team_calls": team_calls,
            })

    # ── Summary ───────────────────────────────────────────────
    total_fx = sum(r["api_fx"] for r in results)
    total_stats = sum(r["stats_needed"] for r in results)
    total_teams = sum(r["team_calls"] for r in results)
    n_skip = sum(1 for r in results if r["status"] == "SKIP")
    n_need = len(results) - n_skip
    fixture_fetch_calls = n_need  # 1 per league+season that needs work
    total_api = fixture_fetch_calls + total_stats + total_teams

    print("\n" + "=" * 75)
    print("  ESTIMATE SUMMARY")
    print("=" * 75)

    print(f"\n  League+season combos:    {len(results)}")
    print(f"  Already complete (skip): {n_skip}")
    print(f"  Need processing:         {n_need}")
    print(f"\n  Total fixtures found:    {total_fx:>7,}")

    print(f"\n  ESTIMATED API CALLS FOR ACTUAL BACKFILL:")
    print(f"    Fixture list fetches:  {fixture_fetch_calls:>7,}  (1 per league+season)")
    print(f"    Fixture stats fetches: {total_stats:>7,}  (1 per fixture)")
    print(f"    Team last20 fetches:   {total_teams:>7,}  (1 per team)")
    print(f"    {'─' * 40}")
    print(f"    TOTAL:                 {total_api:>7,}")

    print(f"\n  API calls used by this dry run:  {api_calls_used}")
    print(f"  Ultra plan daily limit:          75,000")
    pct = total_api / 75_000 * 100
    print(f"  Backfill as % of daily limit:    {pct:.1f}%")

    est_secs = total_api / 10
    est_mins = est_secs / 60
    print(f"  Estimated time @ 10 req/s:       ~{est_mins:.0f} min")

    print(f"\n  Per-season breakdown:")
    print(f"    {'Season':<8} {'Fixtures':>9} {'Stats calls':>13} {'Team calls':>12}")
    print(f"    {'─' * 8} {'─' * 9} {'─' * 13} {'─' * 12}")
    for season in BACKFILL_SEASONS:
        s_fx = sum(r["api_fx"] for r in results if r["season"] == season)
        s_st = sum(r["stats_needed"] for r in results if r["season"] == season)
        s_tm = sum(r["team_calls"] for r in results if r["season"] == season)
        print(f"    {season:<8} {s_fx:>9,} {s_st:>13,} {s_tm:>12,}")

    print("\n" + "=" * 75)
    print("  DRY RUN COMPLETE — run with --backfill to start actual backfill")
    print("=" * 75 + "\n")


# ══════════════════════════════════════════════════════════════
#  ACTUAL BACKFILL
# ══════════════════════════════════════════════════════════════


async def backfill_league_with_resume(
    sync: DataSyncService,
    session_factory: async_sessionmaker,
    league_id: int,
    season: int,
) -> tuple[int, int, int]:
    """
    Backfill one league+season with resume support.

    1. Fetch all FT fixtures from API, upsert into DB.
    2. For fixtures missing stats, fetch and store statistics.
    3. Returns (fixture_count, stats_synced, stats_skipped).
    """
    # Step 1: Fetch fixtures
    raw = await sync.client.get_fixtures_by_league_season(league_id, season, status="FT")
    if not raw:
        return 0, 0, 0

    # Step 2: Upsert all fixtures
    count = 0
    async with sync.session_factory() as session:
        for fx in raw:
            await sync._ensure_fixture(session, fx)
            count += 1
            if count % 50 == 0:
                await session.commit()
        await session.commit()

    # Step 3: Find which fixtures already have stats
    fixture_ids = []
    for fx in raw:
        fid = fx.get("fixture", {}).get("id")
        if fid:
            fixture_ids.append(fid)

    async with session_factory() as session:
        existing = (
            await session.execute(
                select(FixtureStatistics.fixture_id)
                .where(FixtureStatistics.fixture_id.in_(fixture_ids))
                .distinct()
            )
        ).scalars().all()

    existing_set = set(existing)
    missing = [fid for fid in fixture_ids if fid not in existing_set]
    skipped = len(fixture_ids) - len(missing)

    # Step 4: Sync stats only for missing fixtures
    synced = 0
    for i, fid in enumerate(missing, 1):
        try:
            await sync.sync_fixture_statistics(fid)
            synced += 1
        except Exception as exc:
            logger.warning("Stats failed for fixture %d: %s", fid, exc)

        if i % 50 == 0:
            logger.info("  Stats progress: %d/%d", i, len(missing))

    return count, synced, skipped


async def backfill(session_factory, client):
    """Run the full backfill for all leagues+seasons."""
    sync = DataSyncService(session_factory, client)

    print("\n" + "=" * 75)
    print("  STARTING HISTORICAL BACKFILL")
    print("=" * 75)

    jobs = [
        (lid, s) for lid in sorted(TARGET_LEAGUE_IDS) for s in BACKFILL_SEASONS
    ]

    grand_fx = 0
    grand_stats_synced = 0
    grand_stats_skipped = 0
    grand_teams = 0
    grand_skipped_jobs = 0
    start_time = time.monotonic()

    for idx, (league_id, season) in enumerate(jobs, 1):
        name = LEAGUE_NAMES.get(league_id, f"League {league_id}")
        job_start = time.monotonic()

        # ── Resume check ──────────────────────────────────────
        async with session_factory() as session:
            db_fx = (
                await session.execute(
                    select(func.count())
                    .select_from(Fixture)
                    .where(
                        Fixture.league_id == league_id,
                        Fixture.season == season,
                        Fixture.status == "FT",
                    )
                )
            ).scalar() or 0

            db_stats = (
                await session.execute(
                    select(func.count(func.distinct(FixtureStatistics.fixture_id)))
                    .where(
                        FixtureStatistics.fixture_id.in_(
                            select(Fixture.id).where(
                                Fixture.league_id == league_id,
                                Fixture.season == season,
                            )
                        )
                    )
                )
            ).scalar() or 0

        if db_fx > 0 and db_stats >= db_fx * 0.9:
            print(
                f"  [{idx:>2}/{len(jobs)}] {name:<22} {season}  "
                f"SKIP (DB has {db_fx} fx, {db_stats} stats)"
            )
            grand_skipped_jobs += 1
            continue

        print(
            f"\n  [{idx:>2}/{len(jobs)}] {name:<22} {season}  "
            f"(DB: {db_fx} fx, {db_stats} stats)"
        )

        # ── Fixtures + stats ──────────────────────────────────
        try:
            fx_count, stats_synced, stats_skipped = (
                await backfill_league_with_resume(
                    sync, session_factory, league_id, season
                )
            )
        except Exception as exc:
            logger.error("FAILED %s %d: %s", name, season, exc)
            print(f"         ERROR: {exc}")
            continue

        grand_fx += fx_count
        grand_stats_synced += stats_synced
        grand_stats_skipped += stats_skipped

        print(
            f"         {fx_count} fixtures | "
            f"stats: {stats_synced} synced, {stats_skipped} already had"
        )

        # ── Rebuild team_last20 ───────────────────────────────
        async with session_factory() as session:
            home_ids = (
                await session.execute(
                    select(Fixture.home_team_id)
                    .where(
                        Fixture.league_id == league_id,
                        Fixture.season == season,
                    )
                    .distinct()
                )
            ).scalars().all()

            away_ids = (
                await session.execute(
                    select(Fixture.away_team_id)
                    .where(
                        Fixture.league_id == league_id,
                        Fixture.season == season,
                    )
                    .distinct()
                )
            ).scalars().all()

        all_teams = set(home_ids) | set(away_ids)
        team_count = 0
        for team_id in sorted(all_teams):
            try:
                await sync.sync_team_last20(team_id, league_id, season)
                team_count += 1
            except Exception as exc:
                logger.warning("last20 failed team %d: %s", team_id, exc)

        grand_teams += team_count

        job_secs = time.monotonic() - job_start
        elapsed = time.monotonic() - start_time
        done = idx - grand_skipped_jobs
        if done > 0:
            avg = elapsed / done
            remaining_jobs = len(jobs) - idx
            eta = avg * remaining_jobs
        else:
            eta = 0

        print(
            f"         {team_count} teams last20 | "
            f"job {job_secs:.0f}s | elapsed {elapsed/60:.1f}m | "
            f"ETA {eta/60:.1f}m"
        )

    # ── Final summary ─────────────────────────────────────────
    elapsed = time.monotonic() - start_time

    async with session_factory() as session:
        fx_total = (
            await session.execute(select(func.count()).select_from(Fixture))
        ).scalar()
        stats_total = (
            await session.execute(
                select(func.count()).select_from(FixtureStatistics)
            )
        ).scalar()
        last20_total = (
            await session.execute(
                select(func.count()).select_from(TeamLast20)
            )
        ).scalar()

    print("\n" + "=" * 75)
    print("  BACKFILL COMPLETE")
    print("=" * 75)
    print(f"\n  Time elapsed:            {elapsed/60:.1f} minutes")
    print(f"  Jobs processed:          {len(jobs) - grand_skipped_jobs} / {len(jobs)}")
    print(f"  Jobs skipped (resume):   {grand_skipped_jobs}")
    print(f"  Fixtures upserted:       {grand_fx:,}")
    print(f"  Stats synced:            {grand_stats_synced:,}")
    print(f"  Stats skipped (resume):  {grand_stats_skipped:,}")
    print(f"  Teams last20 rebuilt:    {grand_teams}")
    print(f"\n  DATABASE TOTALS:")
    print(f"    fixtures:              {fx_total:>8,}")
    print(f"    fixture_statistics:    {stats_total:>8,}")
    print(f"    team_last20:           {last20_total:>8,}")
    print("=" * 75 + "\n")


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════


async def main():
    mode = "--dry-run"
    if len(sys.argv) > 1 and sys.argv[1] == "--backfill":
        mode = "--backfill"

    api_key = os.getenv("API_FOOTBALL_KEY", "")
    if not api_key:
        print("ERROR: API_FOOTBALL_KEY not set in .env")
        sys.exit(1)

    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with APIFootballClient(api_key=api_key) as client:
        if mode == "--backfill":
            await backfill(session_factory, client)
        else:
            await dry_run(session_factory, client)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
