"""Smoke test for retrain pipeline fixes.

Verifies:
- XGBoost trains with early_stopping active
- NaN values handled correctly
- Model save/load roundtrip produces identical predictions
"""

import tempfile
from pathlib import Path

import numpy as np
import pytest
import xgboost as xgb

# Import the retrain function directly (no DB needed for this test)
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.retrain import train_model_optuna, MARKETS


def _make_synthetic_data(n_samples: int, n_features: int = 32, nan_fraction: float = 0.1):
    """Create synthetic dataset with some NaN values."""
    rng = np.random.RandomState(42)
    X = rng.randn(n_samples, n_features).astype(np.float32)

    # Inject NaN values
    nan_mask = rng.random(X.shape) < nan_fraction
    X[nan_mask] = np.nan

    return X


@pytest.fixture
def ou25_data():
    """Synthetic binary classification data for ou25 market."""
    rng = np.random.RandomState(42)
    X_train = _make_synthetic_data(200, nan_fraction=0.05)
    X_val = _make_synthetic_data(50, nan_fraction=0.05)
    y_train = rng.randint(0, 2, size=200)
    y_val = rng.randint(0, 2, size=50)
    return X_train, y_train, X_val, y_val


@pytest.fixture
def multiclass_data():
    """Synthetic 3-class data for 1x2 market."""
    rng = np.random.RandomState(42)
    X_train = _make_synthetic_data(200, nan_fraction=0.05)
    X_val = _make_synthetic_data(50, nan_fraction=0.05)
    y_train = rng.randint(0, 3, size=200)
    y_val = rng.randint(0, 3, size=50)
    return X_train, y_train, X_val, y_val


class TestTrainModelOptuna:
    """Tests for train_model_optuna with audit fixes."""

    def test_trains_without_error(self, ou25_data):
        X_train, y_train, X_val, y_val = ou25_data
        model = train_model_optuna(X_train, y_train, X_val, y_val, "ou25", n_trials=1)
        assert model is not None

    def test_early_stopping_active(self, ou25_data):
        X_train, y_train, X_val, y_val = ou25_data
        model = train_model_optuna(X_train, y_train, X_val, y_val, "ou25", n_trials=1)
        # best_iteration exists when early_stopping_rounds is used
        assert hasattr(model, "best_iteration")
        assert model.best_iteration >= 0

    def test_handles_nan_values(self, ou25_data):
        X_train, y_train, X_val, y_val = ou25_data
        # Confirm NaN values are present
        assert np.isnan(X_val).any(), "Test data should contain NaN values"

        model = train_model_optuna(X_train, y_train, X_val, y_val, "ou25", n_trials=1)
        # Model should predict without error on NaN data
        preds = model.predict_proba(X_val)
        assert preds.shape == (50, 2)
        assert not np.isnan(preds).any(), "Predictions should not contain NaN"

    def test_save_load_roundtrip(self, ou25_data):
        X_train, y_train, X_val, y_val = ou25_data
        model = train_model_optuna(X_train, y_train, X_val, y_val, "ou25", n_trials=1)

        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "ou25_model.json"
            model.save_model(str(model_path))

            loaded = xgb.XGBClassifier()
            loaded.load_model(str(model_path))

            orig_preds = model.predict_proba(X_val)
            loaded_preds = loaded.predict_proba(X_val)

            np.testing.assert_array_almost_equal(
                orig_preds, loaded_preds,
                decimal=6,
                err_msg="Loaded model predictions differ from original",
            )

    def test_multiclass_no_num_class_param(self, multiclass_data):
        """Verify 1x2 (3-class) trains without explicit num_class."""
        X_train, y_train, X_val, y_val = multiclass_data
        model = train_model_optuna(X_train, y_train, X_val, y_val, "1x2", n_trials=1)
        preds = model.predict_proba(X_val)
        assert preds.shape == (50, 3), f"Expected 3 classes, got shape {preds.shape}"

    def test_num_class_still_in_markets_config(self):
        """Verify num_class is still present in MARKETS dict for evaluate_model."""
        assert MARKETS["1x2"]["num_class"] == 3
        assert MARKETS["ou25"]["num_class"] is None
        assert MARKETS["btts"]["num_class"] is None
        assert MARKETS["htft"]["num_class"] == 9
