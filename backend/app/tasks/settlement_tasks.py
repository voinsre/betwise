"""Settlement Celery tasks — Phase 10.

Thin Celery wrapper around the settlement service.
"""

import asyncio
import logging
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.services.api_football import APIFootballClient
from app.services.data_sync import DataSyncService
from app.services.settlement import settle_fixtures_for_date
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task
def settle_completed_fixtures():
    """Fetch results, update scores, settle predictions/tickets, log accuracy."""
    asyncio.run(_settle_completed_fixtures())


async def _settle_completed_fixtures():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    client = APIFootballClient(api_key=settings.API_FOOTBALL_KEY)
    sync_service = DataSyncService(session_factory, client)

    try:
        today = date.today()
        summary = await settle_fixtures_for_date(today, session_factory, sync_service)
        logger.info("Settlement task complete: %s", summary)
    finally:
        await client.close()
        await engine.dispose()
