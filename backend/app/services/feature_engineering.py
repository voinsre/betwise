"""Feature engineering — stub (Phase 8 will implement fully).

Exports FEATURE_NAMES and compute_feature_vector() so prediction_engine
can import without crashing. Returns NaN array until Phase 8 builds the
real 30-feature vector.
"""

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fixture import Fixture

# Same 32-feature list used by the current XGBoost models.
# Phase 8 will replace with the new 30-feature set.
FEATURE_NAMES = [
    "home_goals_avg",
    "away_goals_avg",
    "home_conceded_avg",
    "away_conceded_avg",
    "home_xg_avg",
    "away_xg_avg",
    "home_xga_avg",
    "away_xga_avg",
    "home_sot_avg",
    "away_sot_avg",
    "home_possession_avg",
    "away_possession_avg",
    "home_form_pts",
    "away_form_pts",
    "home_clean_sheet_rate",
    "away_clean_sheet_rate",
    "home_btts_rate",
    "away_btts_rate",
    "home_o25_rate",
    "away_o25_rate",
    "position_diff",
    "points_gap",
    "h2h_home_wins",
    "h2h_draws",
    "h2h_away_wins",
    "h2h_avg_goals",
    "home_injury_impact",
    "away_injury_impact",
    "home_advantage",
    "poisson_home",
    "poisson_draw",
    "poisson_away",
]


async def compute_feature_vector(
    session: AsyncSession,
    fixture: Fixture,
    league_config=None,
) -> np.ndarray:
    """Stub — returns NaN array. Phase 8 replaces with real features."""
    return np.full(len(FEATURE_NAMES), float("nan"), dtype=np.float32)
