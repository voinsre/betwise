"""Settlement Celery tasks — Phase 10.

Thin Celery wrapper around the settlement service.
Self-healing: queries for unsettled predictions rather than guessing dates.
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.services.api_football import APIFootballClient
from app.services.data_sync import DataSyncService
from app.services.settlement import find_unsettled_dates, settle_fixtures_for_date
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task
def settle_completed_fixtures():
    """Find all dates with unsettled predictions on FT fixtures, settle them."""
    asyncio.run(_settle_completed_fixtures())


async def _settle_completed_fixtures():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    client = APIFootballClient(api_key=settings.API_FOOTBALL_KEY)
    sync_service = DataSyncService(session_factory, client)

    try:
        dates_to_settle = await find_unsettled_dates(session_factory)

        if not dates_to_settle:
            logger.info("No unsettled predictions found — nothing to do.")
            return

        logger.info("Found %d dates needing settlement: %s", len(dates_to_settle), dates_to_settle)

        for target_date in dates_to_settle:
            try:
                summary = await settle_fixtures_for_date(target_date, session_factory, sync_service)
                logger.info("Settlement for %s complete: %s", target_date, summary)
            except Exception as e:
                logger.error("Settlement failed for %s: %s", target_date, e, exc_info=True)
    finally:
        await client.close()
        await engine.dispose()
