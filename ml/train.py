"""XGBoost training pipeline — Phase 4.

Walk-forward validation: train on 2023+2024, validate on 2025.
Separate models for 1x2 (3-class), ou25 (binary), btts (binary), htft (9-class).
Optuna hyperparameter tuning with log_loss objective.

Run from the backend/ directory:
    python ../ml/train.py
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
import optuna
import xgboost as xgb
from sklearn.metrics import accuracy_score, log_loss

# Add backend/ to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(env_path)

# Override for local execution
os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://betwise:BetWise2026Secure@localhost:5432/betwise"
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.fixture import Fixture
from app.services.ml_model import FEATURE_NAMES, MLPredictor

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Silence Optuna's verbose logging
optuna.logging.set_verbosity(optuna.logging.WARNING)
logger = logging.getLogger("train")
logger.setLevel(logging.INFO)

DB_URL = os.environ["DATABASE_URL"]
MODEL_DIR = Path(__file__).parent / "models"
MODEL_DIR.mkdir(exist_ok=True)

# Markets and their config
MARKETS = {
    "1x2": {"objective": "multi:softprob", "num_class": 3, "eval_metric": "mlogloss"},
    "ou25": {"objective": "binary:logistic", "num_class": None, "eval_metric": "logloss"},
    "btts": {"objective": "binary:logistic", "num_class": None, "eval_metric": "logloss"},
    "htft": {"objective": "multi:softprob", "num_class": 9, "eval_metric": "mlogloss"},
}

TRAIN_SEASONS = [2023, 2024]
VAL_SEASON = 2025


async def load_fixtures(session_factory, seasons: list[int]) -> list[Fixture]:
    """Load all completed fixtures for the given seasons."""
    async with session_factory() as session:
        q = (
            select(Fixture)
            .where(
                Fixture.season.in_(seasons),
                Fixture.status == "FT",
                Fixture.score_home_ft.isnot(None),
                Fixture.score_away_ft.isnot(None),
            )
            .order_by(Fixture.date, Fixture.id)
        )
        result = await session.execute(q)
        return list(result.scalars().all())


async def build_all_features(
    session_factory: async_sessionmaker,
    fixtures: list[Fixture],
    label: str = "all",
) -> tuple[np.ndarray, dict[str, np.ndarray], list[int]]:
    """
    Build feature matrix X and all label vectors for a set of fixtures.
    Features are built ONCE and shared across all markets.
    Returns (X, labels_dict, fixture_ids).
    """
    ml = MLPredictor(session_factory)

    X_list = []
    labels_dict = {m: [] for m in MARKETS}
    ids = []
    skipped = 0

    total = len(fixtures)
    t0 = time.time()

    async with session_factory() as session:
        for idx, f in enumerate(fixtures):
            all_labels = MLPredictor.get_labels(f)
            if not all_labels:
                skipped += 1
                continue

            try:
                vec = await ml.build_feature_vector(session, f, before_date=f.date)
            except Exception as e:
                skipped += 1
                if skipped <= 3:
                    logger.warning("Skipped fixture %d: %s", f.id, e)
                continue

            X_list.append(vec)
            for m in MARKETS:
                labels_dict[m].append(all_labels.get(m))
            ids.append(f.id)

            if (idx + 1) % 200 == 0:
                elapsed = time.time() - t0
                rate = (idx + 1) / elapsed
                eta = (total - idx - 1) / rate if rate > 0 else 0
                print(
                    f"\r    {idx+1}/{total} fixtures "
                    f"({len(X_list)} valid, {skipped} skipped) "
                    f"ETA {eta:.0f}s",
                    end="", flush=True,
                )

    print(f"\r    {total}/{total} fixtures "
          f"({len(X_list)} valid, {skipped} skipped)              ")

    if not X_list:
        return np.array([]), {m: np.array([]) for m in MARKETS}, []

    X = np.vstack(X_list)
    # Convert labels to numpy arrays, filtering out None values per market
    labels_np = {}
    for m in MARKETS:
        labels_np[m] = labels_dict[m]  # keep as list for now, filter per market

    return X, labels_np, ids


def filter_for_market(
    X: np.ndarray, labels: list, ids: list[int]
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Filter out samples where label is None (e.g., htft missing HT scores)."""
    valid = [(x, l, i) for x, l, i in zip(X, labels, ids) if l is not None]
    if not valid:
        return np.array([]), np.array([]), []
    X_f = np.vstack([v[0] for v in valid])
    y_f = np.array([v[1] for v in valid])
    ids_f = [v[2] for v in valid]
    return X_f, y_f, ids_f


def train_model_optuna(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    market: str,
    n_trials: int = 20,
) -> xgb.XGBClassifier:
    """Train XGBoost with Optuna hyperparameter tuning."""
    cfg = MARKETS[market]

    def objective(trial):
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 100, 1000),
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
            "objective": cfg["objective"],
            "eval_metric": cfg["eval_metric"],
            "tree_method": "hist",
            "verbosity": 0,
            "random_state": 42,
        }
        if cfg["num_class"]:
            params["num_class"] = cfg["num_class"]

        model = xgb.XGBClassifier(**params)
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )

        y_pred_proba = model.predict_proba(X_val)
        if cfg["num_class"] is None:
            loss = log_loss(y_val, y_pred_proba, labels=[0, 1])
        else:
            labels = list(range(cfg["num_class"]))
            loss = log_loss(y_val, y_pred_proba, labels=labels)

        return loss

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    # Retrain with best params
    best_params = study.best_params
    best_params["objective"] = cfg["objective"]
    best_params["eval_metric"] = cfg["eval_metric"]
    best_params["tree_method"] = "hist"
    best_params["verbosity"] = 0
    best_params["random_state"] = 42
    if cfg["num_class"]:
        best_params["num_class"] = cfg["num_class"]

    best_model = xgb.XGBClassifier(**best_params)
    best_model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    return best_model


def evaluate_model(
    model: xgb.XGBClassifier, X_val: np.ndarray, y_val: np.ndarray,
    market: str,
) -> dict:
    """Evaluate model and return metrics."""
    cfg = MARKETS[market]
    y_pred = model.predict(X_val)
    y_pred_proba = model.predict_proba(X_val)

    acc = accuracy_score(y_val, y_pred)

    if cfg["num_class"] is None:
        ll = log_loss(y_val, y_pred_proba, labels=[0, 1])
    else:
        labels = list(range(cfg["num_class"]))
        ll = log_loss(y_val, y_pred_proba, labels=labels)

    return {"accuracy": acc, "log_loss": ll}


def print_feature_importance(model: xgb.XGBClassifier, market: str, top_n: int = 10):
    """Print top N features by importance."""
    importances = model.feature_importances_
    indices = np.argsort(importances)[::-1][:top_n]

    print(f"\n    Top {top_n} features ({market}):")
    for rank, idx in enumerate(indices, 1):
        name = FEATURE_NAMES[idx] if idx < len(FEATURE_NAMES) else f"feature_{idx}"
        print(f"      {rank:2d}. {name:<25} {importances[idx]:.4f}")


async def main():
    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    print("\n" + "=" * 70)
    print("  BETWISE XGBOOST TRAINING PIPELINE")
    print("=" * 70)

    # ── Load fixtures ──────────────────────────────────────────
    print(f"\n  Loading fixtures...")
    train_fixtures = await load_fixtures(session_factory, TRAIN_SEASONS)
    val_fixtures = await load_fixtures(session_factory, [VAL_SEASON])

    print(f"  Training set:   {len(train_fixtures)} fixtures (seasons {TRAIN_SEASONS})")
    print(f"  Validation set: {len(val_fixtures)} fixtures (season {VAL_SEASON})")

    if not train_fixtures or not val_fixtures:
        print("  ERROR: Not enough fixtures to train. Run backfill first.")
        await engine.dispose()
        return

    # ── Build features ONCE for all markets ────────────────────
    print(f"\n  Building training features (all markets at once)...")
    t0 = time.time()
    X_train_all, labels_train, train_ids = await build_all_features(
        session_factory, train_fixtures
    )
    train_feat_time = time.time() - t0
    print(f"  Training features built in {train_feat_time:.1f}s ({len(X_train_all)} samples)")

    print(f"\n  Building validation features...")
    t0 = time.time()
    X_val_all, labels_val, val_ids = await build_all_features(
        session_factory, val_fixtures
    )
    val_feat_time = time.time() - t0
    print(f"  Validation features built in {val_feat_time:.1f}s ({len(X_val_all)} samples)")

    if len(X_train_all) == 0 or len(X_val_all) == 0:
        print("  ERROR: No valid feature vectors built.")
        await engine.dispose()
        return

    # ── Train each market ──────────────────────────────────────
    results = {}
    for market, cfg in MARKETS.items():
        print(f"\n{'─' * 70}")
        print(f"  MARKET: {market.upper()}")
        print(f"{'─' * 70}")

        # Filter for this market (remove None labels)
        X_train, y_train, _ = filter_for_market(X_train_all, labels_train[market], train_ids)
        X_val, y_val, _ = filter_for_market(X_val_all, labels_val[market], val_ids)

        if len(X_train) == 0 or len(X_val) == 0:
            print(f"  SKIPPED: insufficient data (train={len(X_train)}, val={len(X_val)})")
            continue

        print(f"  Train: {len(X_train)} samples")
        print(f"  Val:   {len(X_val)} samples")

        # Class distribution
        n_classes = cfg["num_class"] or 2
        print(f"  Train class dist: ", end="")
        for c in range(n_classes):
            n = (y_train == c).sum()
            print(f"[{c}]={n}({n/len(y_train)*100:.0f}%) ", end="")
        print()

        # Optuna training
        print(f"\n  Running Optuna (20 trials)...")
        t0 = time.time()
        model = train_model_optuna(X_train, y_train, X_val, y_val, market, n_trials=20)
        train_dur = time.time() - t0
        print(f"  Training completed in {train_dur:.1f}s")

        # Evaluate
        metrics = evaluate_model(model, X_val, y_val, market)
        results[market] = metrics

        print(f"\n  Results ({market}):")
        print(f"    Accuracy:  {metrics['accuracy']*100:.2f}%")
        print(f"    Log Loss:  {metrics['log_loss']:.4f}")

        # Feature importance
        print_feature_importance(model, market)

        # Save model
        model_path = MODEL_DIR / f"{market}_model.json"
        model.save_model(str(model_path))
        print(f"\n  Model saved: {model_path}")

        # Save metadata
        meta = {
            "market": market,
            "train_seasons": TRAIN_SEASONS,
            "val_season": VAL_SEASON,
            "train_samples": int(len(X_train)),
            "val_samples": int(len(X_val)),
            "accuracy": round(metrics["accuracy"], 4),
            "log_loss": round(metrics["log_loss"], 4),
            "best_params": {k: v for k, v in model.get_params().items()
                           if k in ["n_estimators", "max_depth", "learning_rate",
                                     "subsample", "colsample_bytree", "min_child_weight"]},
            "feature_names": FEATURE_NAMES,
        }
        meta_path = MODEL_DIR / f"{market}_meta.json"
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

    # ── Summary ────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  TRAINING SUMMARY")
    print("=" * 70)
    print(f"\n  {'Market':<8} {'Accuracy':>10} {'Log Loss':>10}")
    print(f"  {'─'*8} {'─'*10} {'─'*10}")
    for market, metrics in results.items():
        print(f"  {market:<8} {metrics['accuracy']*100:9.2f}% {metrics['log_loss']:10.4f}")

    print(f"\n  Models saved to: {MODEL_DIR}")
    print("=" * 70 + "\n")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
