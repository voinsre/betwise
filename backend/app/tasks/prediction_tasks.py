"""Prediction Celery tasks — Phase 10 + Phase 12 retrain.

Runs the prediction engine for all today's fixtures and
weekly ML model retrain with rolling data window.
"""

import asyncio
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.fixture import Fixture
from app.services.prediction_engine import PredictionEngine
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task
def run_all_predictions():
    """For all today's NS fixtures with sufficient data, run prediction engine."""
    asyncio.run(_run_all_predictions())


async def _run_all_predictions():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        pred_engine = PredictionEngine(session_factory)
        pred_engine.load_models()

        today = date.today()

        async with session_factory() as session:
            result = await session.execute(
                select(Fixture).where(
                    Fixture.date == today,
                    Fixture.status.in_(["NS", "TBD"]),
                )
            )
            fixtures = list(result.scalars().all())

        logger.info("Running predictions for %d fixtures on %s", len(fixtures), today.isoformat())

        total_preds = 0
        total_value = 0
        errors = 0

        for fx in fixtures:
            try:
                preds = await pred_engine.predict_fixture(fx.id)
                total_preds += len(preds)
                total_value += sum(1 for p in preds if p.is_value_bet)
            except Exception as e:
                logger.error("Prediction failed for fixture %d: %s", fx.id, e, exc_info=True)
                errors += 1

        logger.info(
            "Predictions complete: %d predictions, %d value bets, %d errors across %d fixtures",
            total_preds, total_value, errors, len(fixtures),
        )
    finally:
        await engine.dispose()


@celery_app.task(time_limit=1800, soft_time_limit=1500)
def retrain_ml_model():
    """Weekly ML model retrain using rolling data window."""
    asyncio.run(_retrain_ml_model())


async def _retrain_ml_model():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        from app.services.retrain import retrain_all_models

        results = await retrain_all_models(session_factory)

        if "error" in results:
            logger.warning("Retrain skipped: %s", results["error"])
        else:
            for market, metrics in results.items():
                if "error" in metrics:
                    logger.warning("Market %s failed: %s", market, metrics["error"])
                else:
                    logger.info(
                        "Market %s: accuracy=%.2f%%, log_loss=%.4f, samples=%d/%d",
                        market,
                        metrics["accuracy"] * 100,
                        metrics["log_loss"],
                        metrics["train_samples"],
                        metrics["val_samples"],
                    )
    except Exception as e:
        logger.error("Retrain failed: %s", e, exc_info=True)
    finally:
        await engine.dispose()
