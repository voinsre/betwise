#!/bin/sh
set -e

# Run database migrations
python -m alembic -c alembic/alembic.ini upgrade head

# Start Celery worker in background (conserve memory)
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2 --max-memory-per-child=256000 &

# Start Celery beat scheduler in background
celery -A app.tasks.celery_app beat --loglevel=info &

# Start uvicorn in foreground (Railway monitors this process)
exec uvicorn app.main:app --host 0.0.0.0 --port 2323
