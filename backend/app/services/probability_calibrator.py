"""
Runtime probability calibration.
Loads pre-fitted isotonic regression models and applies them
to raw blended probabilities before edge calculation.

Calibrators are built by scripts/build_calibrators.py using
historical prediction data. They correct systematic biases
in the Poisson and XGBoost models (e.g., DC overconfidence
at 0.75+ probabilities).

Usage in predict_fixture():
    from app.services.probability_calibrator import calibrate_probability
    calibrated_prob = calibrate_probability(market_code, raw_blended_prob)
"""

import logging
import os
import pickle
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

CALIBRATOR_DIR = Path(
    os.environ.get(
        "CALIBRATOR_DIR",
        str(Path(__file__).resolve().parent.parent.parent / "ml" / "calibrators"),
    )
)
_calibrators: dict = {}


def _load_calibrators():
    """Load all calibrator files at module import."""
    global _calibrators
    if not CALIBRATOR_DIR.exists():
        logger.info("Calibrator directory not found: %s", CALIBRATOR_DIR)
        return
    for cal_file in CALIBRATOR_DIR.glob("*_calibrator.pkl"):
        market = cal_file.stem.replace("_calibrator", "")
        try:
            with open(cal_file, "rb") as f:
                _calibrators[market] = pickle.load(f)
            logger.info("Loaded calibrator for %s", market)
        except Exception as e:
            logger.warning("Failed to load calibrator for %s: %s", market, e)


def calibrate_probability(market_code: str, raw_prob: float) -> float:
    """
    Apply isotonic calibration to a raw blended probability.
    If no calibrator exists for the market, returns raw probability unchanged.
    """
    if market_code not in _calibrators:
        return raw_prob

    try:
        calibrated = float(
            _calibrators[market_code].predict(np.array([raw_prob]))[0]
        )
        return max(0.01, min(0.99, calibrated))
    except Exception:
        return raw_prob


def is_calibrator_loaded(market_code: str) -> bool:
    return market_code in _calibrators


def get_loaded_calibrators() -> list:
    return list(_calibrators.keys())


# Load calibrators when module is imported
_load_calibrators()
