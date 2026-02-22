"""Weekly ML retrain service — rolling window XGBoost training.

Queries all settled fixtures from the last 18 months, splits into
train (15 months) and validation (3 months), tunes hyperparameters
with Optuna, and saves updated models to ml/models/.

Called by the retrain_ml_model Celery task (Mondays 03:00 UTC).
"""

import json
import logging
import shutil
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import optuna
import xgboost as xgb
from sklearn.metrics import accuracy_score, log_loss
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.fixture import Fixture
from app.services.ml_model import FEATURE_NAMES, MLPredictor

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parent.parent.parent.parent / "ml" / "models"

# Market configs — must match ml/train.py and ml_model.py
MARKETS = {
    "1x2": {"objective": "multi:softprob", "num_class": 3, "eval_metric": "mlogloss"},
    "ou25": {"objective": "binary:logistic", "num_class": None, "eval_metric": "logloss"},
    "btts": {"objective": "binary:logistic", "num_class": None, "eval_metric": "logloss"},
    "htft": {"objective": "multi:softprob", "num_class": 9, "eval_metric": "mlogloss"},
}

# Rolling window parameters
TRAIN_MONTHS = 15
VAL_MONTHS = 3
MIN_TRAIN_FIXTURES = 500
MIN_VAL_FIXTURES = 100
OPTUNA_TRIALS = 15

# Silence Optuna's verbose logging
optuna.logging.set_verbosity(optuna.logging.WARNING)


async def load_fixtures_rolling(
    session_factory: async_sessionmaker,
    start_date: date,
    end_date: date,
) -> list[Fixture]:
    """Load all completed fixtures within a date range."""
    async with session_factory() as session:
        q = (
            select(Fixture)
            .where(
                Fixture.date >= start_date,
                Fixture.date < end_date,
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
) -> tuple[np.ndarray, dict[str, list], list[int]]:
    """
    Build feature matrix X and all label vectors for a set of fixtures.
    Features are built ONCE and shared across all 4 markets.
    Returns (X, labels_dict, fixture_ids).
    """
    ml = MLPredictor(session_factory)

    X_list: list[np.ndarray] = []
    labels_dict: dict[str, list] = {m: [] for m in MARKETS}
    ids: list[int] = []
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
                if skipped <= 5:
                    logger.warning("Skipped fixture %d: %s", f.id, e)
                continue

            X_list.append(vec)
            for m in MARKETS:
                labels_dict[m].append(all_labels.get(m))
            ids.append(f.id)

            if (idx + 1) % 500 == 0:
                elapsed = time.time() - t0
                rate = (idx + 1) / elapsed if elapsed > 0 else 0
                eta = (total - idx - 1) / rate if rate > 0 else 0
                logger.info(
                    "Feature progress: %d/%d fixtures (%d valid, %d skipped) ETA %.0fs",
                    idx + 1, total, len(X_list), skipped, eta,
                )

    logger.info(
        "Feature building complete: %d/%d fixtures (%d valid, %d skipped) in %.1fs",
        total, total, len(X_list), skipped, time.time() - t0,
    )

    if not X_list:
        return np.array([]), {m: [] for m in MARKETS}, []

    X = np.vstack(X_list)
    return X, labels_dict, ids


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
    n_trials: int = OPTUNA_TRIALS,
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


def _backup_model(market: str) -> None:
    """Back up existing model file before overwriting."""
    model_path = MODEL_DIR / f"{market}_model.json"
    if model_path.exists():
        backup_path = MODEL_DIR / f"{market}_model_prev.json"
        shutil.copy2(model_path, backup_path)
        logger.info("Backed up %s → %s", model_path.name, backup_path.name)


def _save_model(model: xgb.XGBClassifier, market: str, metrics: dict,
                train_samples: int, val_samples: int,
                train_range: str, val_range: str) -> None:
    """Save model and metadata to disk."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    model_path = MODEL_DIR / f"{market}_model.json"
    model.save_model(str(model_path))

    meta = {
        "market": market,
        "retrain_date": date.today().isoformat(),
        "train_range": train_range,
        "val_range": val_range,
        "train_samples": train_samples,
        "val_samples": val_samples,
        "accuracy": round(metrics["accuracy"], 4),
        "log_loss": round(metrics["log_loss"], 4),
        "best_params": {
            k: v for k, v in model.get_params().items()
            if k in ["n_estimators", "max_depth", "learning_rate",
                      "subsample", "colsample_bytree", "min_child_weight"]
        },
        "feature_names": FEATURE_NAMES,
    }
    meta_path = MODEL_DIR / f"{market}_meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    logger.info("Saved model %s (accuracy=%.2f%%, log_loss=%.4f)",
                model_path.name, metrics["accuracy"] * 100, metrics["log_loss"])


async def retrain_all_models(session_factory: async_sessionmaker) -> dict:
    """
    Full retrain pipeline with rolling data window.

    Returns dict of {market: {accuracy, log_loss, train_samples, val_samples}}
    or {"error": "..."} if insufficient data.
    """
    today = date.today()
    val_end = today
    val_start = today - timedelta(days=VAL_MONTHS * 30)
    train_end = val_start
    train_start = today - timedelta(days=(TRAIN_MONTHS + VAL_MONTHS) * 30)

    train_range = f"{train_start} to {train_end}"
    val_range = f"{val_start} to {val_end}"

    logger.info("Retrain starting — train: %s, validate: %s", train_range, val_range)

    # Load fixtures
    train_fixtures = await load_fixtures_rolling(session_factory, train_start, train_end)
    val_fixtures = await load_fixtures_rolling(session_factory, val_start, val_end)

    logger.info("Loaded %d train fixtures, %d val fixtures",
                len(train_fixtures), len(val_fixtures))

    if len(train_fixtures) < MIN_TRAIN_FIXTURES:
        msg = (f"Insufficient training data: {len(train_fixtures)} fixtures "
               f"(need {MIN_TRAIN_FIXTURES}). Skipping retrain.")
        logger.warning(msg)
        return {"error": msg}

    if len(val_fixtures) < MIN_VAL_FIXTURES:
        msg = (f"Insufficient validation data: {len(val_fixtures)} fixtures "
               f"(need {MIN_VAL_FIXTURES}). Skipping retrain.")
        logger.warning(msg)
        return {"error": msg}

    # Build features
    logger.info("Building training features...")
    t0 = time.time()
    X_train_all, labels_train, train_ids = await build_all_features(
        session_factory, train_fixtures
    )
    logger.info("Training features built in %.1fs (%d samples)", time.time() - t0, len(X_train_all))

    logger.info("Building validation features...")
    t0 = time.time()
    X_val_all, labels_val, val_ids = await build_all_features(
        session_factory, val_fixtures
    )
    logger.info("Validation features built in %.1fs (%d samples)", time.time() - t0, len(X_val_all))

    if len(X_train_all) == 0 or len(X_val_all) == 0:
        msg = "No valid feature vectors built. Skipping retrain."
        logger.error(msg)
        return {"error": msg}

    # Train each market
    results = {}
    succeeded = 0

    for market, cfg in MARKETS.items():
        logger.info("Training market: %s", market.upper())

        X_train, y_train, _ = filter_for_market(X_train_all, labels_train[market], train_ids)
        X_val, y_val, _ = filter_for_market(X_val_all, labels_val[market], val_ids)

        if len(X_train) == 0 or len(X_val) == 0:
            logger.warning("Market %s: insufficient data (train=%d, val=%d), skipping",
                           market, len(X_train), len(X_val))
            results[market] = {"error": "insufficient data"}
            continue

        try:
            t0 = time.time()
            model = train_model_optuna(X_train, y_train, X_val, y_val, market)
            train_dur = time.time() - t0
            logger.info("Market %s trained in %.1fs (%d trials)", market, train_dur, OPTUNA_TRIALS)

            metrics = evaluate_model(model, X_val, y_val, market)

            # Back up old model, then save new one
            _backup_model(market)
            _save_model(model, market, metrics,
                        train_samples=len(X_train), val_samples=len(X_val),
                        train_range=train_range, val_range=val_range)

            results[market] = {
                "accuracy": round(metrics["accuracy"], 4),
                "log_loss": round(metrics["log_loss"], 4),
                "train_samples": len(X_train),
                "val_samples": len(X_val),
            }
            succeeded += 1

        except Exception as e:
            logger.error("Market %s training failed: %s", market, e, exc_info=True)
            results[market] = {"error": str(e)}

    logger.info("Retrain complete: %d/%d markets succeeded. Results: %s",
                succeeded, len(MARKETS), results)

    return results
