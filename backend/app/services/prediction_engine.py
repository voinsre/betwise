"""Prediction engine orchestrator.

Blends Poisson + XGBoost predictions, calculates confidence scores,
detects value bets, and saves predictions to the database.

Markets: dc (Poisson-only), ou15, ou25, ou35 (Poisson + XGBoost).
"""

import logging
from datetime import date, datetime

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.models.fixture import Fixture
from app.models.league import League
from app.models.odds import Odds
from app.models.prediction import Prediction
from app.models.team import Team
from app.models.team_last20 import TeamLast20
from app.services.bankroll import BankrollManager
from app.services.feature_engineering import compute_feature_vector
from app.services.league_config import get_league_by_api_id, is_market_active
from app.services.ml_model import MLPredictor
from app.services.pinnacle_sync import get_pinnacle_odds_for_fixture, _pinnacle_key
from app.services.poisson_model import PoissonPredictor
from app.services.probability_calibrator import calibrate_probability

logger = logging.getLogger(__name__)

MARKETS_CONFIG = {
    "dc":   {"labels": ["1X", "12", "X2"]},
    "ou15": {"labels": ["Over 1.5", "Under 1.5"]},
    "ou25": {"labels": ["Over 2.5", "Under 2.5"]},
    "ou35": {"labels": ["Over 3.5", "Under 3.5"]},
}

# Markets that have trained XGBoost models
ML_MARKETS = {"ou15", "ou25", "ou35"}

# Markets with Poisson probabilities only (no ML)
POISSON_ONLY_MARKETS = {"dc"}

# Markets that can flag is_value_bet = True
VALUE_BET_MARKETS = {"dc", "ou15", "ou25", "ou35"}

# Markets that generate predictions but NEVER flag as value
DISPLAY_ONLY_MARKETS = set()

# Selections that generate predictions but NEVER flag as value.
# DC 1X is blacklisted because the Poisson model systematically
# overestimates home+draw probability (backtest: 748 bets, -7.9% ROI).
# DC 12 and DC X2 remain active (breakeven or profitable).
BLACKLISTED_SELECTIONS = {("dc", "1X")}

# Per-market blend weight: alpha * poisson + (1 - alpha) * ml
MARKET_ALPHA = {
    "dc":   1.00,   # Pure Poisson (no ML model)
    "ou15": 0.00,   # Pure XGBoost (backtest: Poisson overconfident for OU)
    "ou25": 0.00,   # Pure XGBoost (backtest: 66% hit, +95.6u, 18.5% ROI)
    "ou35": 0.00,   # Pure XGBoost (backtest: Poisson overconfident for OU)
}

# Per-market minimum odds (override global ODDS_MIN)
MARKET_ODDS_MIN = {
    "dc":   1.22,
    "ou15": 1.22,
    "ou25": 1.20,
    "ou35": 1.20,
}

# Per-market maximum odds (override global ODDS_MAX).
# OU markets need wider range — odds commonly exceed 2.20.
MARKET_ODDS_MAX = {
    "dc":   2.20,
    "ou15": 2.60,
    "ou25": 2.60,
    "ou35": 2.60,
}


class PredictionEngine:
    """Orchestrates Poisson + ML predictions for all markets."""

    def __init__(self, session_factory: async_sessionmaker):
        self.session_factory = session_factory
        self.poisson = PoissonPredictor(session_factory)
        self.ml = MLPredictor(session_factory)
        self.bankroll = BankrollManager(
            kelly_multiplier=settings.KELLY_MULTIPLIER,
        )

    def load_models(self):
        """Load XGBoost models from disk."""
        self.ml.load_models()
        logger.info("ML models loaded: %s", list(self.ml._models.keys()))

    async def predict_fixture(self, fixture_id: int) -> list[Prediction]:
        """
        Run full prediction pipeline for one fixture.
        Returns list of Prediction objects for all markets + selections.
        """
        # 1. Poisson predictions (opens its own session)
        try:
            poisson_result = await self.poisson.predict(fixture_id)
        except Exception as e:
            logger.error("Poisson prediction failed for fixture %d: %s", fixture_id, e)
            return []

        # 1b. League gating — skip fixtures not in our 25-league portfolio
        league_id = poisson_result.get("league_id")
        league_config = get_league_by_api_id(league_id) if league_id else None
        if league_config is None:
            logger.debug("Fixture %d: league %s not in portfolio, skipping", fixture_id, league_id)
            return []

        # 2. ML predictions (if models loaded)
        ml_probas = {}
        if self.ml.is_ready():
            async with self.session_factory() as session:
                fixture = await session.get(Fixture, fixture_id)
                if fixture:
                    try:
                        feature_vec = await compute_feature_vector(session, fixture, league_config)
                        for market in ML_MARKETS:
                            if market in self.ml._models:
                                proba = self.ml._models[market].predict_proba(
                                    feature_vec.reshape(1, -1)
                                )[0]
                                ml_probas[market] = proba
                    except Exception as e:
                        logger.warning("ML prediction failed for fixture %d: %s", fixture_id, e)

        # 3. Load odds + Pinnacle odds for this fixture
        async with self.session_factory() as session:
            fixture = await session.get(Fixture, fixture_id)
            league = await session.get(League, fixture.league_id) if fixture else None

            odds_result = await session.execute(
                select(Odds).where(Odds.fixture_id == fixture_id)
            )
            odds_rows = list(odds_result.scalars().all())

            # Best odds per (market, label)
            best_odds: dict[tuple[str, str], Odds] = {}
            for o in odds_rows:
                key = (o.market, o.label)
                if key not in best_odds or o.value > best_odds[key].value:
                    best_odds[key] = o

            # Pinnacle odds for value detection
            pinnacle_odds = await get_pinnacle_odds_for_fixture(session, fixture_id)

            # Count team games for data quality
            home_games_count = 0
            away_games_count = 0
            if fixture:
                for tid, attr in [(fixture.home_team_id, "home"), (fixture.away_team_id, "away")]:
                    cnt_result = await session.execute(
                        select(func.count(TeamLast20.id)).where(
                            TeamLast20.team_id == tid
                        )
                    )
                    cnt = cnt_result.scalar() or 0
                    if attr == "home":
                        home_games_count = cnt
                    else:
                        away_games_count = cnt

            # Odds variance per market
            odds_by_market: dict[str, list[float]] = {}
            for o in odds_rows:
                odds_by_market.setdefault(o.market, []).append(o.value)

        # 4. Build predictions for active markets only
        predictions = []
        markets = poisson_result.get("markets", {})

        for market_code, selections in markets.items():
            if market_code not in MARKETS_CONFIG:
                continue
            if not is_market_active(league_id, market_code):
                continue

            labels = MARKETS_CONFIG[market_code]["labels"]

            # Get ML probabilities for this market if available
            ml_proba = ml_probas.get(market_code)

            for label in labels:
                poisson_prob = selections.get(label, 0.0)
                if poisson_prob <= 0:
                    continue

                # ML probability for this selection
                ml_prob = None
                if ml_proba is not None and market_code in ML_MARKETS:
                    # predict_proba returns [P(class0=Under/No), P(class1=Over/Yes)]
                    # "Over"/"Yes" labels → proba[1], "Under"/"No" labels → proba[0]
                    if "Over" in label or "Yes" in label:
                        ml_prob = float(ml_proba[1])
                    else:
                        ml_prob = float(ml_proba[0])

                # Blend
                alpha = MARKET_ALPHA.get(market_code, 0.50)
                if ml_prob is not None and market_code in ML_MARKETS:
                    blended = alpha * poisson_prob + (1 - alpha) * ml_prob
                else:
                    blended = poisson_prob

                # Apply isotonic calibration (corrects systematic over/under-prediction)
                blended = calibrate_probability(market_code, blended)

                # Best odds for this selection
                odds_key = (market_code, label)
                if odds_key not in best_odds:
                    # Save prediction WITHOUT odds (probability-only)
                    predictions.append(Prediction(
                        fixture_id=fixture_id,
                        market=market_code,
                        selection=label,
                        poisson_probability=round(poisson_prob, 4),
                        ml_probability=round(ml_prob, 4) if ml_prob is not None else None,
                        blended_probability=round(blended, 4),
                        best_odd=None,
                        best_bookmaker=None,
                        implied_probability=None,
                        edge=None,
                        expected_value=None,
                        confidence_score=0,
                        is_value_bet=False,
                    ))
                    continue

                o = best_odds[odds_key]
                implied_prob = 1.0 / o.value
                edge = blended - implied_prob
                ev = (blended * (o.value - 1)) - (1 - blended)

                # Confidence score
                confidence = self._calc_confidence(
                    poisson_prob=poisson_prob,
                    ml_prob=ml_prob,
                    edge=edge,
                    league=league,
                    home_games=home_games_count,
                    away_games=away_games_count,
                    odds_values=odds_by_market.get(market_code, []),
                )

                # Pinnacle edge for is_value_bet decision (sharper than soft-book edge)
                p_key = _pinnacle_key(market_code, label)
                pinnacle_prob = 1 / pinnacle_odds[p_key] if p_key in pinnacle_odds else None
                pinnacle_edge = (blended - pinnacle_prob) if pinnacle_prob else None

                # Value bet flag — use Pinnacle edge when available, else bookmaker edge
                effective_edge = pinnacle_edge if pinnacle_edge is not None else edge
                effective_min_edge = max(settings.MIN_EDGE * 100, league_config.min_edge_pct)
                effective_min_confidence = max(settings.MIN_CONFIDENCE, league_config.min_confidence_pct)
                is_value = (
                    (effective_edge * 100) >= effective_min_edge
                    and confidence >= effective_min_confidence
                    and o.value >= MARKET_ODDS_MIN.get(market_code, settings.ODDS_MIN)
                    and o.value <= MARKET_ODDS_MAX.get(market_code, settings.ODDS_MAX)
                )

                # Display-only markets NEVER flag value regardless of edge
                if market_code in DISPLAY_ONLY_MARKETS:
                    is_value = False

                # Blacklisted selections generate predictions but never flag value
                if (market_code, label) in BLACKLISTED_SELECTIONS:
                    is_value = False

                predictions.append(Prediction(
                    fixture_id=fixture_id,
                    market=market_code,
                    selection=label,
                    poisson_probability=round(poisson_prob, 4),
                    ml_probability=round(ml_prob, 4) if ml_prob is not None else None,
                    blended_probability=round(blended, 4),
                    best_odd=o.value,
                    best_bookmaker=o.bookmaker_name,
                    implied_probability=round(implied_prob, 4),
                    edge=round(edge, 4),
                    expected_value=round(ev, 4),
                    confidence_score=confidence,
                    is_value_bet=is_value,
                ))

        # 5. Limit to ONE value bet per market (highest edge)
        best_value_per_market: dict[str, Prediction] = {}
        for pred in predictions:
            if pred.is_value_bet:
                key = pred.market
                if key not in best_value_per_market or pred.edge > best_value_per_market[key].edge:
                    best_value_per_market[key] = pred
        for pred in predictions:
            if pred.is_value_bet and pred is not best_value_per_market.get(pred.market):
                pred.is_value_bet = False

        # 6. Save to DB (delete old predictions first)
        if predictions:
            async with self.session_factory() as session:
                await session.execute(
                    delete(Prediction).where(Prediction.fixture_id == fixture_id)
                )
                session.add_all(predictions)
                await session.commit()
                logger.info(
                    "Saved %d predictions for fixture %d (%d value bets)",
                    len(predictions),
                    fixture_id,
                    sum(1 for p in predictions if p.is_value_bet),
                )

        return predictions

    async def predict_all_for_date(self, target_date: date) -> dict:
        """Run predictions for all fixtures on a given date."""
        async with self.session_factory() as session:
            q = (
                select(Fixture)
                .where(
                    Fixture.date == target_date,
                    Fixture.status.in_(["NS", "TBD", "FT"]),
                )
                .order_by(Fixture.kickoff_time)
            )
            result = await session.execute(q)
            fixtures = list(result.scalars().all())

        total_predictions = 0
        total_value = 0
        errors = 0

        for f in fixtures:
            try:
                preds = await self.predict_fixture(f.id)
                total_predictions += len(preds)
                total_value += sum(1 for p in preds if p.is_value_bet)
            except Exception as e:
                logger.error("Failed to predict fixture %d: %s", f.id, e)
                errors += 1

        return {
            "date": str(target_date),
            "fixtures_processed": len(fixtures),
            "total_predictions": total_predictions,
            "value_bets_found": total_value,
            "errors": errors,
        }

    async def get_predictions_for_date(self, target_date: date) -> list[dict]:
        """Get all saved predictions for a date with fixture/team info."""
        async with self.session_factory() as session:
            q = (
                select(Prediction, Fixture, Team)
                .join(Fixture, Prediction.fixture_id == Fixture.id)
                .join(Team, Fixture.home_team_id == Team.id)
                .where(
                    Fixture.date == target_date,
                    Prediction.market.in_(list(MARKETS_CONFIG.keys())),
                )
                .order_by(Prediction.confidence_score.desc())
            )
            result = await session.execute(q)
            rows = result.all()

            # Need away team names too
            fixture_ids = {r[1].id for r in rows}
            away_teams = {}
            if fixture_ids:
                for fid in fixture_ids:
                    fix = rows[0][1] if rows else None
                    for r in rows:
                        if r[1].id == fid:
                            fix = r[1]
                            break
                    if fix:
                        away_t = await session.get(Team, fix.away_team_id)
                        if away_t:
                            away_teams[fid] = away_t.name

            predictions = []
            for pred, fixture, home_team in rows:
                predictions.append({
                    "id": pred.id,
                    "fixture_id": fixture.id,
                    "home_team": home_team.name,
                    "away_team": away_teams.get(fixture.id, "Unknown"),
                    "kickoff": str(fixture.kickoff_time),
                    "status": fixture.status,
                    "league_id": fixture.league_id,
                    "market": pred.market,
                    "selection": pred.selection,
                    "poisson_probability": pred.poisson_probability,
                    "ml_probability": pred.ml_probability,
                    "blended_probability": pred.blended_probability,
                    "best_odd": pred.best_odd,
                    "best_bookmaker": pred.best_bookmaker,
                    "implied_probability": pred.implied_probability,
                    "edge": pred.edge,
                    "expected_value": pred.expected_value,
                    "confidence_score": pred.confidence_score,
                    "is_value_bet": pred.is_value_bet,
                })

            return predictions

    async def get_value_bets_for_date(self, target_date: date) -> list[dict]:
        """Get only value bets for a date, sorted by confidence then edge."""
        all_preds = await self.get_predictions_for_date(target_date)
        value_bets = [p for p in all_preds if p["is_value_bet"]]
        value_bets.sort(key=lambda x: (x["confidence_score"], x["edge"]), reverse=True)
        return value_bets

    async def analyze_fixture(self, fixture_id: int) -> dict:
        """Deep analysis of a single fixture — Poisson, ML, odds, value."""
        async with self.session_factory() as session:
            fixture = await session.get(Fixture, fixture_id)
            if not fixture:
                return {"error": "Fixture not found"}

            home_team = await session.get(Team, fixture.home_team_id)
            away_team = await session.get(Team, fixture.away_team_id)
            league = await session.get(League, fixture.league_id)

        # Run prediction pipeline
        predictions = await self.predict_fixture(fixture_id)

        # Get Poisson detail
        try:
            poisson_detail = await self.poisson.predict(fixture_id)
        except Exception:
            poisson_detail = {}

        # Group predictions by market
        by_market = {}
        for p in predictions:
            if p.market not in by_market:
                by_market[p.market] = []
            by_market[p.market].append({
                "selection": p.selection,
                "poisson_prob": p.poisson_probability,
                "ml_prob": p.ml_probability,
                "blended_prob": p.blended_probability,
                "best_odd": p.best_odd,
                "bookmaker": p.best_bookmaker,
                "edge": p.edge,
                "ev": p.expected_value,
                "confidence": p.confidence_score,
                "is_value": p.is_value_bet,
            })

        return {
            "fixture_id": fixture_id,
            "home_team": home_team.name if home_team else "Unknown",
            "away_team": away_team.name if away_team else "Unknown",
            "league": league.name if league else "Unknown",
            "kickoff": str(fixture.kickoff_time),
            "status": fixture.status,
            "lambda_home": poisson_detail.get("lambda_home"),
            "lambda_away": poisson_detail.get("lambda_away"),
            "home_advantage": poisson_detail.get("home_advantage"),
            "markets": by_market,
            "value_bets": [
                p for market_preds in by_market.values()
                for p in market_preds
                if p["is_value"]
            ],
        }

    def _calc_confidence(
        self,
        poisson_prob: float,
        ml_prob: float | None,
        edge: float,
        league: League | None,
        home_games: int,
        away_games: int,
        odds_values: list[float],
    ) -> int:
        """
        Confidence score 0-100 based on 5 signals:
        - Model agreement (25%): |poisson - ml| lower diff = higher
        - Probability decisiveness (25%): how decisive the model prediction is
        - Data quality (15%): league coverage flags
        - Sample size (15%): team game count completeness
        - Market consensus (20%): low odds variance = higher
        """
        score = 0.0

        # Model agreement (25 points max)
        if ml_prob is not None:
            agreement = 1 - abs(poisson_prob - ml_prob)
            score += agreement * 25
        else:
            score += 12.5  # neutral when no ML

        # Probability decisiveness (25 points max)
        # Higher model probability = more decisive prediction
        max_prob = max(poisson_prob, ml_prob or 0)
        decisiveness_score = min(max_prob / 0.70, 1.0) * 25
        score += decisiveness_score

        # Data quality (15 points max)
        if league:
            if league.has_statistics:
                score += 5
            if league.has_odds:
                score += 5
            if league.has_injuries:
                score += 5

        # Sample size (15 points max)
        completeness = (min(home_games, 20) + min(away_games, 20)) / 40
        score += completeness * 15

        # Market consensus (20 points max)
        if len(odds_values) >= 2:
            odds_arr = np.array(odds_values)
            variance = float(np.var(odds_arr))
            consensus = max(0, 1 - variance * 10) * 20
            score += consensus
        else:
            score += 10  # neutral

        return int(min(score, 100))
