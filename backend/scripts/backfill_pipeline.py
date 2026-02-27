"""Backfill pipeline: sync odds + predict + settle for past dates.

Usage (inside Docker):
    python scripts/backfill_pipeline.py 2026-02-21 2026-02-25 2026-02-26 2026-02-27
"""

import asyncio
import logging
import sys
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.services.api_football import APIFootballClient
from app.services.data_sync import DataSyncService
from app.services.prediction_engine import PredictionEngine
from app.services.settlement import settle_fixtures_for_date
from app.models.fixture import Fixture
from app.models.prediction import Prediction

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("backfill")


async def backfill_date(target_date: date, session_factory, sync, pred_engine):
    """Sync odds, generate predictions, and settle for a single date."""
    logger.info("=== Processing %s ===", target_date)

    # 1. Sync fixtures for the date
    logger.info("Step 1: Syncing fixtures for %s", target_date)
    await sync.sync_fixtures_for_date(target_date.isoformat())

    # 2. Get all fixtures for this date
    async with session_factory() as session:
        result = await session.execute(
            select(Fixture).where(Fixture.date == target_date)
        )
        fixtures = list(result.scalars().all())

    logger.info("Found %d fixtures for %s", len(fixtures), target_date)
    if not fixtures:
        return

    # 3. Sync odds for ALL fixtures (not just NS)
    logger.info("Step 2: Syncing odds for %d fixtures", len(fixtures))
    odds_synced = 0
    for fx in fixtures:
        try:
            await sync.sync_odds(fx.id)
            odds_synced += 1
        except Exception as e:
            logger.warning("Odds sync failed for fixture %d: %s", fx.id, e)
    logger.info("Synced odds for %d/%d fixtures", odds_synced, len(fixtures))

    # 4. Check which fixtures now have odds but no predictions
    async with session_factory() as session:
        result = await session.execute(
            select(Fixture).where(Fixture.date == target_date)
        )
        all_fixtures = list(result.scalars().all())

        # Check existing predictions
        existing = await session.execute(
            select(Prediction.fixture_id).where(
                Prediction.fixture_id.in_([f.id for f in all_fixtures])
            ).distinct()
        )
        predicted_fixture_ids = {row[0] for row in existing.all()}

    unpredicted = [f for f in all_fixtures if f.id not in predicted_fixture_ids]
    logger.info("Step 3: %d fixtures need predictions (%d already predicted)",
                len(unpredicted), len(predicted_fixture_ids))

    # 5. Generate predictions
    total_preds = 0
    total_value = 0
    for fx in unpredicted:
        try:
            preds = await pred_engine.predict_fixture(fx.id)
            total_preds += len(preds)
            total_value += sum(1 for p in preds if p.is_value_bet)
        except Exception as e:
            logger.warning("Prediction failed for fixture %d: %s", fx.id, e)

    logger.info("Generated %d predictions (%d value bets) for %s",
                total_preds, total_value, target_date)

    # 6. Settle if date is in the past
    if target_date < date.today():
        logger.info("Step 4: Settling %s", target_date)
        try:
            summary = await settle_fixtures_for_date(target_date, session_factory, sync)
            logger.info("Settlement result: %d fixtures, %d predictions evaluated, "
                       "accuracy %.1f%%",
                       summary["fixtures_settled"],
                       summary["predictions_evaluated"],
                       summary["overall_accuracy"])
        except Exception as e:
            logger.error("Settlement failed for %s: %s", target_date, e)
    else:
        logger.info("Skipping settlement for %s (today/future)", target_date)

    logger.info("=== Done %s ===\n", target_date)


async def main(dates: list[str]):
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    client = APIFootballClient(api_key=settings.API_FOOTBALL_KEY)
    sync = DataSyncService(session_factory, client)

    pred_engine = PredictionEngine(session_factory)
    pred_engine.load_models()

    try:
        for date_str in dates:
            target = date.fromisoformat(date_str)
            await backfill_date(target, session_factory, sync, pred_engine)
    finally:
        await client.close()
        await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/backfill_pipeline.py YYYY-MM-DD [YYYY-MM-DD ...]")
        sys.exit(1)
    asyncio.run(main(sys.argv[1:]))
