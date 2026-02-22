"""Walk-forward backtest — Phase 4.

For each 2025 fixture in the validation set:
1. Get Poisson prediction
2. Get ML prediction
3. Blend (alpha=0.50)
4. Compare against actual outcome
5. Simulate betting on value bets

Run from the backend/ directory:
    python ../ml/backtest.py
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
import xgboost as xgb
from sklearn.metrics import accuracy_score, log_loss

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(env_path)

os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://betwise:BetWise2026Secure@localhost:5432/betwise"
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.fixture import Fixture
from app.models.odds import Odds
from app.models.team import Team
from app.services.ml_model import FEATURE_NAMES, MLPredictor
from app.services.poisson_model import PoissonPredictor

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("backtest")
logger.setLevel(logging.INFO)

DB_URL = os.environ["DATABASE_URL"]
MODEL_DIR = Path(__file__).parent / "models"
ALPHA = 0.50  # blending weight: alpha * poisson + (1 - alpha) * ml

MARKETS_CONFIG = {
    "1x2": {"num_class": 3, "labels": ["Home", "Draw", "Away"]},
    "ou25": {"num_class": 2, "labels": ["Under 2.5", "Over 2.5"]},
    "btts": {"num_class": 2, "labels": ["No", "Yes"]},
    "htft": {
        "num_class": 9,
        "labels": ["1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2"],
    },
}


def load_xgb_model(market: str) -> xgb.XGBClassifier | None:
    path = MODEL_DIR / f"{market}_model.json"
    if not path.exists():
        return None
    model = xgb.XGBClassifier()
    model.load_model(str(path))
    return model


def poisson_probs_for_market(poisson_result: dict, market: str) -> np.ndarray | None:
    """Extract Poisson probabilities as array matching market class order."""
    mkts = poisson_result.get("markets", {})
    if market == "1x2":
        p = mkts.get("1x2")
        if not p:
            return None
        return np.array([p["Home"], p["Draw"], p["Away"]])
    elif market == "ou25":
        p = mkts.get("ou25")
        if not p:
            return None
        return np.array([p["Under 2.5"], p["Over 2.5"]])
    elif market == "btts":
        p = mkts.get("btts")
        if not p:
            return None
        return np.array([p["No"], p["Yes"]])
    elif market == "htft":
        p = mkts.get("htft")
        if not p:
            return None
        order = ["1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2"]
        return np.array([p.get(k, 0.0) for k in order])
    return None


async def main():
    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    print("\n" + "=" * 70)
    print("  BETWISE WALK-FORWARD BACKTEST")
    print("=" * 70)

    # Load models
    models = {}
    for market in MARKETS_CONFIG:
        m = load_xgb_model(market)
        if m:
            models[market] = m
            print(f"  Loaded model: {market}")
        else:
            print(f"  WARNING: No model for {market}")

    if not models:
        print("  ERROR: No trained models found. Run train.py first.")
        await engine.dispose()
        return

    # Load 2025 fixtures
    async with session_factory() as session:
        q = (
            select(Fixture)
            .where(
                Fixture.season == 2025,
                Fixture.status == "FT",
                Fixture.score_home_ft.isnot(None),
                Fixture.score_away_ft.isnot(None),
            )
            .order_by(Fixture.date, Fixture.id)
        )
        result = await session.execute(q)
        fixtures = list(result.scalars().all())

    print(f"\n  Validation fixtures: {len(fixtures)} (season 2025)")

    ml_predictor = MLPredictor(session_factory)
    poisson_predictor = PoissonPredictor(session_factory)

    # ── Collect predictions ────────────────────────────────────
    # Structure: market -> {"y_true": [], "y_pred_poisson": [], "y_pred_ml": [], "y_pred_blend": [], "odds": []}
    data = {m: {"y_true": [], "poisson": [], "ml": [], "blend": [], "odds_data": []}
            for m in MARKETS_CONFIG}

    t0 = time.time()
    processed = 0
    skipped = 0

    async with session_factory() as session:
        for idx, f in enumerate(fixtures):
            labels = MLPredictor.get_labels(f)

            # Build feature vector
            try:
                feature_vec = await ml_predictor.build_feature_vector(
                    session, f, before_date=f.date
                )
            except Exception:
                skipped += 1
                continue

            # Get Poisson prediction
            try:
                poisson_result = await poisson_predictor.predict(f.id)
            except Exception:
                skipped += 1
                continue

            # Load odds for this fixture
            odds_result = await session.execute(
                select(Odds).where(Odds.fixture_id == f.id)
            )
            odds_rows = list(odds_result.scalars().all())

            for market, cfg in MARKETS_CONFIG.items():
                if market not in labels or labels[market] is None:
                    continue
                if market not in models:
                    continue

                y_true = labels[market]

                # ML prediction
                ml_proba = models[market].predict_proba(
                    feature_vec.reshape(1, -1)
                )[0]

                # Poisson prediction
                poisson_proba = poisson_probs_for_market(poisson_result, market)
                if poisson_proba is None:
                    continue

                # Ensure same length
                n_class = cfg["num_class"]
                if len(ml_proba) != n_class or len(poisson_proba) != n_class:
                    continue

                # Blend
                blend_proba = ALPHA * poisson_proba + (1 - ALPHA) * ml_proba
                # Renormalize
                blend_proba = blend_proba / blend_proba.sum()

                # Find best odds for the winning selection
                sel_label = cfg["labels"][y_true]
                best_odd = None
                for o in odds_rows:
                    if o.market == market and o.label == sel_label:
                        if best_odd is None or o.value > best_odd:
                            best_odd = o.value

                data[market]["y_true"].append(y_true)
                data[market]["poisson"].append(poisson_proba)
                data[market]["ml"].append(ml_proba)
                data[market]["blend"].append(blend_proba)
                data[market]["odds_data"].append({
                    "fixture_id": f.id,
                    "best_odd_winning": best_odd,
                    "blend_proba": blend_proba.tolist(),
                    "y_true": y_true,
                    "all_odds": [
                        {"market": o.market, "label": o.label, "value": o.value}
                        for o in odds_rows if o.market == market
                    ],
                })

            processed += 1
            if (idx + 1) % 100 == 0:
                elapsed = time.time() - t0
                rate = (idx + 1) / elapsed
                eta = (len(fixtures) - idx - 1) / rate if rate > 0 else 0
                print(
                    f"\r  Processing: {idx+1}/{len(fixtures)} "
                    f"({processed} ok, {skipped} skipped) ETA {eta:.0f}s",
                    end="", flush=True,
                )

    print(f"\r  Processed: {len(fixtures)}/{len(fixtures)} "
          f"({processed} ok, {skipped} skipped)              ")

    # ── Per-market results ─────────────────────────────────────
    for market, cfg in MARKETS_CONFIG.items():
        d = data[market]
        if not d["y_true"]:
            print(f"\n  {market.upper()}: No data")
            continue

        y_true = np.array(d["y_true"])
        poisson_arr = np.array(d["poisson"])
        ml_arr = np.array(d["ml"])
        blend_arr = np.array(d["blend"])

        n_class = cfg["num_class"]
        labels_range = list(range(n_class))

        # Accuracy
        poisson_preds = poisson_arr.argmax(axis=1)
        ml_preds = ml_arr.argmax(axis=1)
        blend_preds = blend_arr.argmax(axis=1)

        poisson_acc = accuracy_score(y_true, poisson_preds)
        ml_acc = accuracy_score(y_true, ml_preds)
        blend_acc = accuracy_score(y_true, blend_preds)

        # Log loss
        poisson_ll = log_loss(y_true, poisson_arr, labels=labels_range)
        ml_ll = log_loss(y_true, ml_arr, labels=labels_range)
        blend_ll = log_loss(y_true, blend_arr, labels=labels_range)

        print(f"\n{'─' * 70}")
        print(f"  MARKET: {market.upper()} ({len(y_true)} fixtures)")
        print(f"{'─' * 70}")
        print(f"\n  {'Model':<12} {'Accuracy':>10} {'Log Loss':>10}")
        print(f"  {'─'*12} {'─'*10} {'─'*10}")
        print(f"  {'Poisson':<12} {poisson_acc*100:9.2f}% {poisson_ll:10.4f}")
        print(f"  {'XGBoost':<12} {ml_acc*100:9.2f}% {ml_ll:10.4f}")
        print(f"  {'Blended':<12} {blend_acc*100:9.2f}% {blend_ll:10.4f}")

        # Calibration summary (group predicted probabilities into bins)
        print(f"\n  Calibration (blended, class with highest true frequency):")
        for c in range(min(n_class, 3)):  # show up to 3 classes
            class_label = cfg["labels"][c]
            probs = blend_arr[:, c]
            actuals = (y_true == c).astype(float)

            # Bin into 5 buckets
            bins = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
            print(f"    {class_label}:")
            for b_lo, b_hi in zip(bins[:-1], bins[1:]):
                mask = (probs >= b_lo) & (probs < b_hi)
                if mask.sum() == 0:
                    continue
                avg_pred = probs[mask].mean()
                avg_actual = actuals[mask].mean()
                n = mask.sum()
                print(
                    f"      Predicted {b_lo:.1f}-{b_hi:.1f}: "
                    f"avg_pred={avg_pred:.3f}, actual={avg_actual:.3f}, n={n}"
                )

        # ── Betting simulation ─────────────────────────────────
        has_odds = any(
            od["all_odds"] for od in d["odds_data"]
        )
        if has_odds:
            print(f"\n  Betting simulation (flat $10 stake on value bets):")
            total_bets = 0
            total_staked = 0.0
            total_return = 0.0

            for od in d["odds_data"]:
                blend_p = od["blend_proba"]
                y_actual = od["y_true"]

                for odds_entry in od["all_odds"]:
                    sel_label = odds_entry["label"]
                    odd_val = odds_entry["value"]

                    # Find which class index this label corresponds to
                    if sel_label not in cfg["labels"]:
                        continue
                    class_idx = cfg["labels"].index(sel_label)
                    model_prob = blend_p[class_idx]
                    implied_prob = 1.0 / odd_val

                    edge = model_prob - implied_prob
                    if edge > 0.02 and 1.20 <= odd_val <= 2.50:
                        total_bets += 1
                        total_staked += 10.0
                        if y_actual == class_idx:
                            total_return += 10.0 * odd_val

            if total_bets > 0:
                profit = total_return - total_staked
                roi = profit / total_staked * 100
                print(f"    Bets placed:  {total_bets}")
                print(f"    Total staked: ${total_staked:.2f}")
                print(f"    Total return: ${total_return:.2f}")
                print(f"    Profit/Loss:  ${profit:+.2f}")
                print(f"    ROI:          {roi:+.2f}%")
            else:
                print(f"    No value bets found (edge > 2%, odds 1.20-2.50)")
        else:
            print(f"\n  No odds data available for betting simulation.")

    # ── Overall summary ────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  BACKTEST SUMMARY")
    print("=" * 70)

    print(f"\n  Blending: {ALPHA*100:.0f}% Poisson + {(1-ALPHA)*100:.0f}% XGBoost")
    print(f"\n  {'Market':<8} {'N':>6} {'Poisson':>10} {'XGBoost':>10} {'Blended':>10}  (Log Loss)")
    print(f"  {'─'*8} {'─'*6} {'─'*10} {'─'*10} {'─'*10}")

    for market in MARKETS_CONFIG:
        d = data[market]
        if not d["y_true"]:
            continue
        y_true = np.array(d["y_true"])
        n_class = MARKETS_CONFIG[market]["num_class"]
        labels_range = list(range(n_class))

        poisson_ll = log_loss(y_true, np.array(d["poisson"]), labels=labels_range)
        ml_ll = log_loss(y_true, np.array(d["ml"]), labels=labels_range)
        blend_ll = log_loss(y_true, np.array(d["blend"]), labels=labels_range)

        best = "P" if poisson_ll < ml_ll else "M"
        best_blend = blend_ll < min(poisson_ll, ml_ll)

        print(
            f"  {market:<8} {len(y_true):>6} "
            f"{poisson_ll:10.4f} {ml_ll:10.4f} {blend_ll:10.4f}"
            f"  {'★' if best_blend else ''}"
        )

    print("\n" + "=" * 70 + "\n")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
