from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, get_db
from app.models.fixture import Fixture
from app.models.prediction import Prediction
from app.models.team import Team
from app.services.prediction_engine import PredictionEngine

router = APIRouter()


def _get_engine() -> PredictionEngine:
    engine = PredictionEngine(async_session)
    engine.load_models()
    return engine


@router.get("/{date_str}")
async def get_predictions_by_date(date_str: str, db: AsyncSession = Depends(get_db)):
    """All predictions for a date."""
    try:
        target = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    engine = _get_engine()
    predictions = await engine.get_predictions_for_date(target)
    return {"date": date_str, "count": len(predictions), "predictions": predictions}


@router.get("/{date_str}/value")
async def get_value_bets(date_str: str, db: AsyncSession = Depends(get_db)):
    """Only value bets for a date."""
    try:
        target = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    engine = _get_engine()
    value_bets = await engine.get_value_bets_for_date(target)
    return {"date": date_str, "count": len(value_bets), "value_bets": value_bets}


@router.get("/fixture/{fixture_id}")
async def get_fixture_predictions(fixture_id: int, db: AsyncSession = Depends(get_db)):
    """All markets for one fixture."""
    fixture = await db.get(Fixture, fixture_id)
    if not fixture:
        raise HTTPException(status_code=404, detail="Fixture not found")

    result = await db.execute(
        select(Prediction)
        .where(
            Prediction.fixture_id == fixture_id,
            Prediction.market.in_(["dc", "ou15", "ou25", "ou35"]),
        )
        .order_by(Prediction.market, Prediction.selection)
    )
    predictions = result.scalars().all()

    home_team = await db.get(Team, fixture.home_team_id)
    away_team = await db.get(Team, fixture.away_team_id)

    items = []
    for p in predictions:
        items.append({
            "id": p.id,
            "market": p.market,
            "selection": p.selection,
            "poisson_probability": p.poisson_probability,
            "ml_probability": p.ml_probability,
            "blended_probability": p.blended_probability,
            "best_odd": p.best_odd,
            "best_bookmaker": p.best_bookmaker,
            "implied_probability": p.implied_probability,
            "edge": p.edge,
            "expected_value": p.expected_value,
            "confidence_score": p.confidence_score,
            "is_value_bet": p.is_value_bet,
        })

    return {
        "fixture_id": fixture_id,
        "home_team": home_team.name if home_team else "Unknown",
        "away_team": away_team.name if away_team else "Unknown",
        "kickoff": str(fixture.kickoff_time),
        "status": fixture.status,
        "predictions": items,
    }
