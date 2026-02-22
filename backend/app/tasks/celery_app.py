from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "betwise",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.sync_tasks",
        "app.tasks.prediction_tasks",
        "app.tasks.settlement_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)

celery_app.conf.beat_schedule = {
    # ── Morning data pipeline (04:00–05:30 UTC) ──────────────────
    "sync-daily-fixtures": {
        "task": "app.tasks.sync_tasks.sync_daily_fixtures",
        "schedule": crontab(hour=4, minute=0),
    },
    "sync-fixture-data": {
        "task": "app.tasks.sync_tasks.sync_all_fixture_data",
        "schedule": crontab(hour=4, minute=20),
    },
    "sync-odds": {
        "task": "app.tasks.sync_tasks.sync_all_odds",
        "schedule": crontab(hour=5, minute=0),
    },
    "run-predictions": {
        "task": "app.tasks.prediction_tasks.run_all_predictions",
        "schedule": crontab(hour=5, minute=30),
    },
    # ── Odds + predictions refresh during match window ────────────
    # European kickoffs span ~11:00–20:30 UTC.  Refresh odds and
    # re-run predictions so edge/value-bet flags stay current.
    "refresh-odds-and-predict": {
        "task": "app.tasks.sync_tasks.refresh_odds_and_predict",
        "schedule": crontab(hour="10,12,14,16,18", minute=0),
    },
    "refresh-odds-and-predict-late": {
        "task": "app.tasks.sync_tasks.refresh_odds_and_predict",
        "schedule": crontab(hour=19, minute=30),
    },
    # ── Settlement (two passes to catch late finishers) ───────────
    "settle-results": {
        "task": "app.tasks.settlement_tasks.settle_completed_fixtures",
        "schedule": crontab(hour=0, minute=30),
    },
    "settle-results-late": {
        "task": "app.tasks.settlement_tasks.settle_completed_fixtures",
        "schedule": crontab(hour=2, minute=0),
    },
    # ── Weekly ML retrain ─────────────────────────────────────────
    "retrain-ml": {
        "task": "app.tasks.prediction_tasks.retrain_ml_model",
        "schedule": crontab(hour=3, minute=0, day_of_week="monday"),
    },
}
