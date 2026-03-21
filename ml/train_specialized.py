"""V6 ML training pipeline — 30-feature rolling-window XGBoost.

Trains 3 binary classifiers (ou15, ou25, ou35) using:
- 30-feature engineering from feature_engineering.py
- Rolling window: 15 months train, 3 months validation
- Optuna hyperparameter tuning (15 trials per market)
- Quality gates + model backups

Usage (from project root):
    # Local (requires DB on localhost:5432):
    cd backend && python ../ml/train_specialized.py

    # Docker (one-liner — see bottom of file for command):
    # Uses retrain_all_models() directly inside the container.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# ── path setup ──────────────────────────────────────────────────────────
backend_dir = str(Path(__file__).resolve().parent.parent / "backend")
sys.path.insert(0, backend_dir)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://betwise:BetWise2026Secure@localhost:5432/betwise",
)

# ── logging ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("train_specialized")

# ── imports (after path setup) ──────────────────────────────────────────
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.services.retrain import retrain_all_models  # noqa: E402


async def main():
    db_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    print("\n" + "=" * 70)
    print("  BETWISE V6 TRAINING PIPELINE")
    print("  30-feature rolling-window XGBoost (ou15, ou25, ou35)")
    print("=" * 70)

    results = await retrain_all_models(session_factory, triggered_by="manual_v6")

    print("\n" + "=" * 70)
    print("  TRAINING RESULTS")
    print("=" * 70)

    if "error" in results:
        print(f"\n  ERROR: {results['error']}")
    else:
        print(f"\n  {'Market':<8} {'Accuracy':>10} {'Log Loss':>10} {'Train':>8} {'Val':>6}")
        print(f"  {'─' * 8} {'─' * 10} {'─' * 10} {'─' * 8} {'─' * 6}")
        for market, m in results.items():
            if "error" in m:
                print(f"  {market:<8} ERROR: {m['error']}")
            else:
                print(
                    f"  {market:<8} {m['accuracy'] * 100:9.2f}% "
                    f"{m['log_loss']:10.4f} {m['train_samples']:>8} {m['val_samples']:>6}"
                )

    print("=" * 70 + "\n")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())


# ── Docker run command ──────────────────────────────────────────────────
# From project root (Git Bash / MSYS2):
#
# MSYS_NO_PATHCONV=1 docker run --rm --user root \
#   --network betwise_internal \
#   --env-file .env \
#   -e DATABASE_URL=postgresql+asyncpg://betwise:BetWise2026Secure@db:5432/betwise \
#   -e MODEL_DIR=/app/ml/models \
#   -v "$(pwd)/backend:/app" \
#   -v "$(pwd)/ml/models:/app/ml/models" \
#   -w //app \
#   betwise-backend \
#   python -c "
# import asyncio, logging, os
# logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
# os.environ['MODEL_DIR'] = '/app/ml/models'
# from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
# from app.services.retrain import retrain_all_models
# engine = create_async_engine(os.environ['DATABASE_URL'], echo=False)
# sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
# r = asyncio.run(retrain_all_models(sf, triggered_by='manual_v6'))
# print(f'Results: {r}')
# asyncio.run(engine.dispose())
# "
