"""Run the full daily pipeline manually — no Celery dependency.

Usage (with Railway env vars):
    railway run -- python scripts/run_pipeline.py

Or locally with .env:
    python scripts/run_pipeline.py
"""

import asyncio
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

# Ensure backend/ is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("pipeline")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.fixture import Fixture
from app.services.api_football import APIFootballClient
from app.services.data_sync import DataSyncService
from app.services.prediction_engine import PredictionEngine


async def run_pipeline():
    logger.info("=== Starting manual pipeline run ===")
    logger.info("DATABASE_URL: %s...%s", settings.DATABASE_URL[:30], settings.DATABASE_URL[-10:])

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    client = APIFootballClient(api_key=settings.API_FOOTBALL_KEY)

    try:
        sync = DataSyncService(session_factory, client)
        today = date.today()
        tomorrow = today + timedelta(days=1)

        # Step 1: Sync fixtures for today + tomorrow
        logger.info("--- Step 1: Syncing fixtures ---")
        today_count = await sync.sync_fixtures_for_date(today.isoformat())
        tomorrow_count = await sync.sync_fixtures_for_date(tomorrow.isoformat())
        logger.info("Fixtures synced: %d today, %d tomorrow", today_count, tomorrow_count)

        # Step 2: Sync fixture data (form, H2H, injuries, standings)
        logger.info("--- Step 2: Syncing fixture data ---")
        async with session_factory() as session:
            result = await session.execute(
                select(Fixture).where(Fixture.date == today)
            )
            fixtures = result.scalars().all()

        logger.info("Found %d fixtures for today (%s)", len(fixtures), today.isoformat())

        for fx in fixtures:
            try:
                logger.info("  Fixture %d: syncing team data...", fx.id)
                await sync.sync_team_last20(fx.home_team_id, fx.league_id, fx.season)
                await sync.sync_team_last20(fx.away_team_id, fx.league_id, fx.season)
                await sync.sync_head_to_head(fx.home_team_id, fx.away_team_id)
                await sync.sync_injuries(fx.id)
                await sync.sync_standings(fx.league_id, fx.season)
            except Exception as e:
                logger.error("  Failed fixture %d: %s", fx.id, e)

        # Step 3: Sync odds
        logger.info("--- Step 3: Syncing odds ---")
        async with session_factory() as session:
            result = await session.execute(
                select(Fixture).where(
                    Fixture.date == today,
                    Fixture.status == "NS",
                )
            )
            ns_fixtures = result.scalars().all()

        logger.info("Found %d NS fixtures for odds sync", len(ns_fixtures))
        total_odds = 0
        for fx in ns_fixtures:
            try:
                count = await sync.sync_odds(fx.id)
                total_odds += count
            except Exception as e:
                logger.error("  Failed odds for fixture %d: %s", fx.id, e)
        logger.info("Odds synced: %d rows", total_odds)

        # Step 4: Run predictions
        logger.info("--- Step 4: Running predictions ---")
        pred_engine = PredictionEngine(session_factory)
        pred_engine.load_models()

        async with session_factory() as session:
            result = await session.execute(
                select(Fixture).where(
                    Fixture.date == today,
                    Fixture.status.in_(["NS", "TBD"]),
                )
            )
            pred_fixtures = list(result.scalars().all())

        total_preds = 0
        total_value = 0
        errors = 0
        for fx in pred_fixtures:
            try:
                preds = await pred_engine.predict_fixture(fx.id)
                total_preds += len(preds)
                total_value += sum(1 for p in preds if p.is_value_bet)
                logger.info("  Fixture %d: %d predictions, %d value bets",
                            fx.id, len(preds), sum(1 for p in preds if p.is_value_bet))
            except Exception as e:
                logger.error("  Prediction failed for fixture %d: %s", fx.id, e)
                errors += 1

        logger.info("=== Pipeline complete ===")
        logger.info("Predictions: %d total, %d value bets, %d errors across %d fixtures",
                     total_preds, total_value, errors, len(pred_fixtures))

    finally:
        await client.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_pipeline())
