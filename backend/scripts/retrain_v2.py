"""
Retrain XGBoost models with:
1. CORRECTED label mapping (Over = class 1, Under = class 0)
2. FULL 30-feature set (Tier A + Tier B including Pinnacle implied probs + Elo)
3. Rolling temporal validation (no data leakage)

Trains 3 models: ou15, ou25, ou35
DC remains Poisson-only (no ML model).

Output: ml/models/{market}_model.json + {market}_meta.json
"""

import asyncio
import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import xgboost as xgb
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    classification_report,
    log_loss,
    roc_auc_score,
)
from sqlalchemy import text

sys.path.insert(0, r"c:\Users\vsrez\OneDrive\Documents\Projects\betwise\backend")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://betwise:BetWise2026Secure@localhost:5432/betwise",
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from app.database import async_session as session_factory
from app.models.fixture import Fixture
from app.services.feature_engineering import FEATURE_NAMES, compute_feature_vector
from app.services.league_config import get_active_league_ids, get_league_by_api_id

MODEL_DIR = Path("ml/models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)

MARKETS = {
    "ou15": {"threshold": 1.5},
    "ou25": {"threshold": 2.5},
    "ou35": {"threshold": 3.5},
}

# Rolling window training
TRAIN_MONTHS = 15
VAL_MONTHS = 3

# XGBoost hyperparameters (conservative to avoid overfitting)
XGB_PARAMS = {
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "max_depth": 5,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 10,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "random_state": 42,
    "n_estimators": 300,
    "early_stopping_rounds": 30,
    "use_label_encoder": False,
}


async def collect_training_data():
    """Collect feature vectors and labels for all FT fixtures."""
    portfolio_ids = set(get_active_league_ids())

    # Date boundaries
    today = date.today()
    val_end = today - timedelta(days=1)
    val_start = today - timedelta(days=VAL_MONTHS * 30)
    train_start = val_start - timedelta(days=TRAIN_MONTHS * 30)

    print(f"Training window:   {train_start} to {val_start}")
    print(f"Validation window: {val_start} to {val_end}")

    data = {
        "train": {"features": [], "labels": defaultdict(list), "dates": [], "leagues": []},
        "val": {"features": [], "labels": defaultdict(list), "dates": [], "leagues": []},
    }

    t0 = time.time()

    async with session_factory() as session:
        fixtures_result = await session.execute(
            text("""
            SELECT f.id, f.date, f.home_team_id, f.away_team_id,
                   f.league_id, f.score_home_ft, f.score_away_ft
            FROM fixtures f
            WHERE f.status = 'FT'
              AND f.league_id = ANY(:league_ids)
              AND f.date >= :start_date
              AND f.date <= :end_date
              AND f.score_home_ft IS NOT NULL
            ORDER BY f.date
        """),
            {
                "league_ids": list(portfolio_ids),
                "start_date": train_start,
                "end_date": val_end,
            },
        )
        fixtures = fixtures_result.all()
        total = len(fixtures)
        print(f"Total FT fixtures in window: {total}")

        skipped = 0
        for i, row in enumerate(fixtures):
            fid, fdate, home_id, away_id, league_id, h, a = row

            if i % 500 == 0 and i > 0:
                elapsed = time.time() - t0
                print(
                    f"  Progress: {i}/{total} ({i / total * 100:.0f}%) — "
                    f"train={len(data['train']['features'])}, "
                    f"val={len(data['val']['features'])} — "
                    f"{elapsed:.0f}s"
                )

            league_config = get_league_by_api_id(league_id)
            if not league_config:
                continue

            fixture_obj = await session.get(Fixture, fid)
            if not fixture_obj:
                continue

            # Compute feature vector with before_date
            try:
                vec = await compute_feature_vector(
                    session, fixture_obj, league_config, before_date=fdate
                )
            except Exception:
                skipped += 1
                continue

            if vec is None or len(vec) == 0:
                skipped += 1
                continue

            # Compute labels (CORRECTED mapping: class 1 = Over)
            total_goals = (h or 0) + (a or 0)
            labels = {
                "ou15": 1 if total_goals > 1.5 else 0,
                "ou25": 1 if total_goals > 2.5 else 0,
                "ou35": 1 if total_goals > 3.5 else 0,
            }

            # Assign to train or val split
            split = "val" if fdate >= val_start else "train"
            data[split]["features"].append(vec)
            for market, label in labels.items():
                data[split]["labels"][market].append(label)
            data[split]["dates"].append(fdate)
            data[split]["leagues"].append(league_id)

    elapsed = time.time() - t0
    print(f"\nData collected in {elapsed:.0f}s:")
    print(f"  Training: {len(data['train']['features'])} fixtures")
    print(f"  Validation: {len(data['val']['features'])} fixtures")
    print(f"  Skipped: {skipped}")

    # Feature availability report
    if data["train"]["features"]:
        train_matrix = np.array(data["train"]["features"])
        print(f"\n  Feature matrix shape: {train_matrix.shape}")
        print(f"  Feature availability (% non-NaN):")
        for j, fname in enumerate(FEATURE_NAMES):
            pct = (1 - np.isnan(train_matrix[:, j]).mean()) * 100
            status = "OK" if pct > 50 else "LOW" if pct > 10 else "MISS"
            if pct < 100:  # Only show features with some missing data
                print(f"    [{status}] {fname}: {pct:.1f}%")

    return data


def train_models(data: dict):
    """Train XGBClassifier model per market with early stopping."""
    train_X = np.array(data["train"]["features"])
    val_X = np.array(data["val"]["features"])

    results = {}

    for market, config in MARKETS.items():
        print(f"\n{'=' * 60}")
        print(f"TRAINING: {market}")
        print(f"{'=' * 60}")

        train_y = np.array(data["train"]["labels"][market])
        val_y = np.array(data["val"]["labels"][market])

        # Class distribution
        train_pos = train_y.mean()
        val_pos = val_y.mean()
        print(f"  Train: {len(train_y)} samples, {train_pos:.1%} positive (Over)")
        print(f"  Val:   {len(val_y)} samples, {val_pos:.1%} positive (Over)")

        # Train XGBClassifier (sklearn API — compatible with predict_proba)
        model = xgb.XGBClassifier(**XGB_PARAMS)
        model.fit(
            train_X,
            train_y,
            eval_set=[(train_X, train_y), (val_X, val_y)],
            verbose=50,
        )

        # Evaluate
        val_proba = model.predict_proba(val_X)[:, 1]  # P(Over)
        val_pred = (val_proba >= 0.5).astype(int)

        accuracy = accuracy_score(val_y, val_pred)
        ll = log_loss(val_y, np.clip(val_proba, 0.01, 0.99))
        brier = brier_score_loss(val_y, val_proba)
        try:
            auc = roc_auc_score(val_y, val_proba)
        except ValueError:
            auc = 0.0

        print(f"\n  Validation results:")
        print(f"    Accuracy:    {accuracy:.4f} ({accuracy * 100:.1f}%)")
        print(f"    Log loss:    {ll:.4f}")
        print(f"    Brier score: {brier:.4f}")
        print(f"    AUC:         {auc:.4f}")
        print(f"    Best round:  {model.best_iteration}")

        print(f"\n  Classification report:")
        print(classification_report(val_y, val_pred, target_names=["Under", "Over"]))

        # Feature importance
        importance = model.get_booster().get_score(importance_type="gain")
        sorted_imp = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:15]
        print(f"  Top 15 features by gain:")
        for fname, score in sorted_imp:
            idx = int(fname.replace("f", ""))
            real_name = FEATURE_NAMES[idx] if idx < len(FEATURE_NAMES) else fname
            print(f"    {real_name:<35} {score:.1f}")

        # Calibration check on validation set
        print(f"\n  Validation calibration:")
        print(f"  {'Bucket':<10} {'Count':>6} {'Predicted':>10} {'Actual':>8} {'Gap':>8}")
        for bucket_start in np.arange(0.1, 1.0, 0.1):
            mask = (val_proba >= bucket_start) & (val_proba < bucket_start + 0.1)
            if mask.sum() < 10:
                continue
            avg_pred = val_proba[mask].mean()
            avg_actual = val_y[mask].mean()
            gap = avg_pred - avg_actual
            status = "OVER" if gap > 0.05 else "UNDER" if gap < -0.05 else "OK"
            print(
                f"  {bucket_start:.1f}-{bucket_start + 0.1:.1f}   "
                f"{mask.sum():>6} {avg_pred:>10.3f} {avg_actual:>8.3f} "
                f"{gap:>+8.3f} {status}"
            )

        # Save model
        model_path = MODEL_DIR / f"{market}_model.json"
        model.save_model(str(model_path))

        # Save metadata
        meta = {
            "market": market,
            "trained_at": str(date.today()),
            "train_samples": int(len(train_y)),
            "val_samples": int(len(val_y)),
            "train_positive_rate": float(train_pos),
            "val_positive_rate": float(val_pos),
            "accuracy": float(accuracy),
            "log_loss": float(ll),
            "brier_score": float(brier),
            "auc": float(auc),
            "best_round": int(model.best_iteration),
            "feature_count": int(train_X.shape[1]),
            "feature_names": list(FEATURE_NAMES),
            "xgb_params": {k: v for k, v in XGB_PARAMS.items()},
            "label_mapping": "class0=Under, class1=Over",
        }
        meta_path = MODEL_DIR / f"{market}_meta.json"
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

        print(f"\n  Saved: {model_path}")
        print(f"  Saved: {meta_path}")

        results[market] = {
            "accuracy": accuracy,
            "log_loss": ll,
            "brier": brier,
            "auc": auc,
        }

    return results


async def main():
    print("STEP 1: Collecting training data...")
    data = await collect_training_data()

    print("\nSTEP 2: Training models...")
    results = train_models(data)

    print(f"\n{'=' * 60}")
    print("TRAINING SUMMARY")
    print(f"{'=' * 60}")
    print(f"  {'Market':<10} {'Accuracy':>10} {'LogLoss':>10} {'Brier':>10} {'AUC':>10}")
    for market, r in results.items():
        print(
            f"  {market:<10} {r['accuracy']:>10.4f} {r['log_loss']:>10.4f} "
            f"{r['brier']:>10.4f} {r['auc']:>10.4f}"
        )

    print(f"\nLabel mapping: class 0 = Under, class 1 = Over (CORRECTED)")
    print(f"Feature set: {len(FEATURE_NAMES)} features (Tier A + Tier B)")
    print(f"Models saved to: {MODEL_DIR}/")


if __name__ == "__main__":
    asyncio.run(main())
