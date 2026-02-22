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
)

celery_app.conf.beat_schedule = {
    "sync-daily-fixtures": {
        "task": "app.tasks.sync_tasks.sync_daily_fixtures",
        "schedule": crontab(hour=4, minute=0),
    },
    "sync-fixture-data": {
        "task": "app.tasks.sync_tasks.sync_all_fixture_data",
        "schedule": crontab(hour=4, minute=5),
    },
    "sync-odds": {
        "task": "app.tasks.sync_tasks.sync_all_odds",
        "schedule": crontab(hour=4, minute=30),
    },
    "run-predictions": {
        "task": "app.tasks.prediction_tasks.run_all_predictions",
        "schedule": crontab(hour=5, minute=0),
    },
    "refresh-odds": {
        "task": "app.tasks.sync_tasks.sync_all_odds",
        "schedule": crontab(hour="6,8,10,12,14,16,18,20", minute=0),
    },
    "settle-results": {
        "task": "app.tasks.settlement_tasks.settle_completed_fixtures",
        "schedule": crontab(hour=23, minute=0),
    },
    "retrain-ml": {
        "task": "app.tasks.prediction_tasks.retrain_ml_model",
        "schedule": crontab(hour=2, minute=0, day_of_week="monday"),
    },
}
