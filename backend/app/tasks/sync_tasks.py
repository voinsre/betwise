"""Data sync Celery tasks — Phase 2.3.

Each task creates its own async engine/client, runs the async sync methods
via asyncio.run(), then cleans up. This bridges Celery's synchronous task
model with our fully-async DataSyncService.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.fixture import Fixture
from app.services.api_football import APIFootballClient
from app.services.data_sync import DataSyncService
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _sync_context():
    """Async context manager that yields (sync_service, session_factory)."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    client = APIFootballClient(api_key=settings.API_FOOTBALL_KEY)
    sync_service = DataSyncService(session_factory, client)
    try:
        yield sync_service, session_factory
    finally:
        await client.close()
        await engine.dispose()


# ── sync_daily_fixtures ───────────────────────────────────────────

@celery_app.task
def sync_daily_fixtures():
    """Sync fixtures for today and tomorrow across all active leagues."""
    asyncio.run(_sync_daily_fixtures())


async def _sync_daily_fixtures():
    async with _sync_context() as (sync, _session_factory):
        today = date.today()
        tomorrow = today + timedelta(days=1)

        today_count = await sync.sync_fixtures_for_date(today.isoformat())
        tomorrow_count = await sync.sync_fixtures_for_date(tomorrow.isoformat())

        logger.info(
            "Daily fixtures sync complete: %d today (%s), %d tomorrow (%s)",
            today_count, today.isoformat(), tomorrow_count, tomorrow.isoformat(),
        )


# ── sync_all_fixture_data ────────────────────────────────────────

@celery_app.task
def sync_all_fixture_data():
    """For each today's fixture: sync both teams' last20, H2H, injuries, standings."""
    asyncio.run(_sync_all_fixture_data())


async def _sync_all_fixture_data():
    async with _sync_context() as (sync, session_factory):
        today = date.today()

        async with session_factory() as session:
            result = await session.execute(
                select(Fixture).where(Fixture.date == today)
            )
            fixtures = result.scalars().all()

        logger.info("Syncing fixture data for %d fixtures on %s", len(fixtures), today.isoformat())

        for fx in fixtures:
            try:
                await _sync_single_fixture_data(sync, fx)
            except Exception as exc:
                logger.error("Failed to sync data for fixture %d: %s", fx.id, exc)


async def _sync_single_fixture_data(sync: DataSyncService, fx: Fixture):
    """Sync all supporting data for a single fixture."""
    logger.info("Syncing data for fixture %d (league=%d, season=%d)", fx.id, fx.league_id, fx.season)

    # Last 20 for both teams
    await sync.sync_team_last20(fx.home_team_id, fx.league_id, fx.season)
    await sync.sync_team_last20(fx.away_team_id, fx.league_id, fx.season)

    # Head-to-head
    await sync.sync_head_to_head(fx.home_team_id, fx.away_team_id)

    # Injuries
    await sync.sync_injuries(fx.id)

    # Standings for the league/season
    await sync.sync_standings(fx.league_id, fx.season)


# ── sync_fixture_data (single fixture) ───────────────────────────

@celery_app.task
def sync_fixture_data(fixture_id: int):
    """Sync all supporting data for a specific fixture."""
    asyncio.run(_sync_fixture_data(fixture_id))


async def _sync_fixture_data(fixture_id: int):
    async with _sync_context() as (sync, session_factory):
        async with session_factory() as session:
            fx = await session.get(Fixture, fixture_id)
            if not fx:
                logger.warning("Fixture %d not found in DB, skipping", fixture_id)
                return

        await _sync_single_fixture_data(sync, fx)
        logger.info("Fixture data sync complete for fixture %d", fixture_id)


# ── sync_all_odds ─────────────────────────────────────────────────

@celery_app.task
def sync_all_odds():
    """For all today's NS (not started) fixtures, sync odds."""
    asyncio.run(_sync_all_odds())


async def _sync_all_odds():
    async with _sync_context() as (sync, session_factory):
        today = date.today()

        async with session_factory() as session:
            result = await session.execute(
                select(Fixture).where(
                    Fixture.date == today,
                    Fixture.status == "NS",
                )
            )
            fixtures = result.scalars().all()

        logger.info("Syncing odds for %d NS fixtures on %s", len(fixtures), today.isoformat())

        total_odds = 0
        for fx in fixtures:
            try:
                count = await sync.sync_odds(fx.id)
                total_odds += count
            except Exception as exc:
                logger.error("Failed to sync odds for fixture %d: %s", fx.id, exc)

        logger.info("Odds sync complete: %d odds rows for %d fixtures", total_odds, len(fixtures))


# ── refresh_odds_and_predict ──────────────────────────────────────

@celery_app.task
def refresh_odds_and_predict():
    """Refresh odds for today's NS fixtures, then re-run predictions."""
    asyncio.run(_refresh_odds_and_predict())


async def _refresh_odds_and_predict():
    from app.tasks.prediction_tasks import _run_all_predictions

    await _sync_all_odds()
    await _run_all_predictions()


# ── backfill_historical ──────────────────────────────────────────

@celery_app.task
def backfill_historical(league_id: int, season: int):
    """Full historical backfill for one league+season."""
    asyncio.run(_backfill_historical(league_id, season))


async def _backfill_historical(league_id: int, season: int):
    async with _sync_context() as (sync, _session_factory):
        logger.info("Starting backfill for league %d season %d", league_id, season)
        count = await sync.backfill_league(league_id, season)
        logger.info("Backfill complete: %d fixtures for league %d season %d", count, league_id, season)
