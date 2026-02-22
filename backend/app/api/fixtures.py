from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, get_db
from app.models.fixture import Fixture
from app.models.team import Team
from app.services.prediction_engine import PredictionEngine

router = APIRouter()


def _get_engine() -> PredictionEngine:
    engine = PredictionEngine(async_session)
    engine.load_models()
    return engine


@router.get("/{date_str}")
async def get_fixtures_by_date(date_str: str, db: AsyncSession = Depends(get_db)):
    """Get all fixtures for a given date."""
    try:
        target = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    q = (
        select(Fixture)
        .where(Fixture.date == target)
        .order_by(Fixture.kickoff_time)
    )
    result = await db.execute(q)
    fixtures = result.scalars().all()

    items = []
    for f in fixtures:
        home_team = await db.get(Team, f.home_team_id)
        away_team = await db.get(Team, f.away_team_id)
        items.append({
            "id": f.id,
            "date": str(f.date),
            "kickoff": str(f.kickoff_time),
            "home_team": {"id": f.home_team_id, "name": home_team.name if home_team else "Unknown"},
            "away_team": {"id": f.away_team_id, "name": away_team.name if away_team else "Unknown"},
            "league_id": f.league_id,
            "season": f.season,
            "round": f.round,
            "venue": f.venue,
            "referee": f.referee,
            "status": f.status,
            "score": {
                "home_ht": f.score_home_ht,
                "away_ht": f.score_away_ht,
                "home_ft": f.score_home_ft,
                "away_ft": f.score_away_ft,
            },
        })

    return {"date": date_str, "count": len(items), "fixtures": items}


@router.get("/{fixture_id}/analysis")
async def get_fixture_analysis(fixture_id: int, db: AsyncSession = Depends(get_db)):
    """Deep analysis of a single fixture."""
    fixture = await db.get(Fixture, fixture_id)
    if not fixture:
        raise HTTPException(status_code=404, detail="Fixture not found")

    engine = _get_engine()
    analysis = await engine.analyze_fixture(fixture_id)
    return analysis
