from datetime import date, datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.fixture import Fixture
from app.models.league import League
from app.models.model_accuracy import ModelAccuracy
from app.models.prediction import Prediction
from app.models.team_last20 import TeamLast20

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class SettingsUpdate(BaseModel):
    kelly_multiplier: float | None = None
    min_confidence: int | None = None
    min_edge: float | None = None
    odds_min: float | None = None
    odds_max: float | None = None


@router.post("/login")
async def admin_login(request: LoginRequest):
    """Admin login — returns JWT."""
    if (
        request.username != settings.ADMIN_USERNAME
        or request.password != settings.ADMIN_PASSWORD
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    payload = {
        "sub": request.username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRY_HOURS),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return {"token": token}


@router.get("/dashboard")
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    """Today's overview dashboard."""
    today = date.today()

    fixture_count = await db.execute(
        select(func.count(Fixture.id)).where(Fixture.date == today)
    )
    total_fixtures = fixture_count.scalar() or 0

    pred_count = await db.execute(
        select(func.count(Prediction.id))
        .join(Fixture, Prediction.fixture_id == Fixture.id)
        .where(Fixture.date == today)
    )
    total_predictions = pred_count.scalar() or 0

    value_count = await db.execute(
        select(func.count(Prediction.id))
        .join(Fixture, Prediction.fixture_id == Fixture.id)
        .where(Fixture.date == today, Prediction.is_value_bet.is_(True))
    )
    total_value_bets = value_count.scalar() or 0

    league_count = await db.execute(
        select(func.count(League.id)).where(League.is_active.is_(True))
    )
    active_leagues = league_count.scalar() or 0

    total_db_fixtures = await db.execute(select(func.count(Fixture.id)))

    return {
        "dashboard": {
            "date": str(today),
            "fixtures_today": total_fixtures,
            "predictions_today": total_predictions,
            "value_bets_today": total_value_bets,
            "active_leagues": active_leagues,
            "total_fixtures_in_db": total_db_fixtures.scalar() or 0,
        }
    }


@router.get("/data-health")
async def get_data_health(db: AsyncSession = Depends(get_db)):
    """Sync status and data completeness."""
    status_result = await db.execute(
        select(Fixture.status, func.count(Fixture.id)).group_by(Fixture.status)
    )
    status_counts = {row[0]: row[1] for row in status_result.all()}

    season_result = await db.execute(
        select(Fixture.season, func.count(Fixture.id)).group_by(Fixture.season)
    )
    season_counts = {row[0]: row[1] for row in season_result.all()}

    team_data = await db.execute(
        select(func.count(func.distinct(TeamLast20.team_id)))
    )
    teams_with_data = team_data.scalar() or 0

    latest = await db.execute(select(func.max(Fixture.date)))
    latest_date = latest.scalar()

    return {
        "health": {
            "fixture_status_counts": status_counts,
            "fixtures_per_season": season_counts,
            "teams_with_form_data": teams_with_data,
            "latest_fixture_date": str(latest_date) if latest_date else None,
        }
    }


@router.get("/accuracy")
async def get_accuracy(db: AsyncSession = Depends(get_db)):
    """Model accuracy over time (last 30 days) with summary stats."""
    today = date.today()
    cutoff_30 = today - timedelta(days=30)
    cutoff_7 = today - timedelta(days=7)

    result = await db.execute(
        select(ModelAccuracy)
        .where(ModelAccuracy.date >= cutoff_30)
        .order_by(ModelAccuracy.date.desc())
    )
    rows = result.scalars().all()

    items = []
    for r in rows:
        items.append({
            "date": str(r.date),
            "market": r.market,
            "league_id": r.league_id,
            "total_predictions": r.total_predictions,
            "correct_predictions": r.correct_predictions,
            "accuracy_pct": r.accuracy_pct,
            "avg_edge": r.avg_edge,
            "avg_confidence": r.avg_confidence,
            "total_staked": r.total_staked,
            "total_returned": r.total_returned,
            "profit_loss": r.profit_loss,
            "roi_pct": r.roi_pct,
        })

    # Build per-market summary for 7-day and 30-day windows
    def _summarize(rows_list):
        by_market = {}
        for r in rows_list:
            m = r.market
            if m not in by_market:
                by_market[m] = {"total": 0, "correct": 0, "staked": 0.0, "returned": 0.0}
            by_market[m]["total"] += r.total_predictions
            by_market[m]["correct"] += r.correct_predictions
            by_market[m]["staked"] += r.total_staked
            by_market[m]["returned"] += r.total_returned

        summary = {}
        for m, s in by_market.items():
            pl = s["returned"] - s["staked"]
            summary[m] = {
                "total_predictions": s["total"],
                "correct_predictions": s["correct"],
                "accuracy_pct": round(s["correct"] / s["total"] * 100, 1) if s["total"] > 0 else 0.0,
                "total_staked": round(s["staked"], 2),
                "profit_loss": round(pl, 2),
                "roi_pct": round(pl / s["staked"] * 100, 1) if s["staked"] > 0 else 0.0,
            }
        return summary

    rows_7d = [r for r in rows if r.date >= cutoff_7]

    return {
        "accuracy": items,
        "summary_7d": _summarize(rows_7d),
        "summary_30d": _summarize(rows),
    }


@router.get("/accuracy/{market}")
async def get_market_accuracy(market: str, db: AsyncSession = Depends(get_db)):
    """Market-specific accuracy."""
    result = await db.execute(
        select(ModelAccuracy)
        .where(ModelAccuracy.market == market)
        .order_by(ModelAccuracy.date.desc())
        .limit(90)
    )
    rows = result.scalars().all()

    items = []
    for r in rows:
        items.append({
            "date": str(r.date),
            "total_predictions": r.total_predictions,
            "correct_predictions": r.correct_predictions,
            "accuracy_pct": r.accuracy_pct,
            "avg_edge": r.avg_edge,
            "roi_pct": r.roi_pct,
        })

    return {"market": market, "accuracy": items}


@router.post("/backfill")
async def trigger_backfill(league_id: int, season: int):
    """Trigger historical backfill (placeholder — needs Celery)."""
    return {"status": "queued", "league_id": league_id, "season": season}


@router.post("/retrain")
async def trigger_retrain():
    """Trigger ML retrain (placeholder — needs Celery)."""
    return {"status": "queued", "message": "ML retrain task queued"}


@router.put("/settings")
async def update_settings(request: SettingsUpdate):
    """Update model weights and thresholds (runtime only)."""
    updated = {}
    if request.kelly_multiplier is not None:
        settings.KELLY_MULTIPLIER = request.kelly_multiplier
        updated["kelly_multiplier"] = request.kelly_multiplier
    if request.min_confidence is not None:
        settings.MIN_CONFIDENCE = request.min_confidence
        updated["min_confidence"] = request.min_confidence
    if request.min_edge is not None:
        settings.MIN_EDGE = request.min_edge
        updated["min_edge"] = request.min_edge
    if request.odds_min is not None:
        settings.ODDS_MIN = request.odds_min
        updated["odds_min"] = request.odds_min
    if request.odds_max is not None:
        settings.ODDS_MAX = request.odds_max
        updated["odds_max"] = request.odds_max

    return {"status": "updated", "changes": updated}


@router.get("/leagues")
async def list_leagues(db: AsyncSession = Depends(get_db)):
    """List leagues with status."""
    result = await db.execute(select(League).order_by(League.country, League.name))
    leagues = result.scalars().all()

    items = []
    for lg in leagues:
        items.append({
            "id": lg.id,
            "name": lg.name,
            "country": lg.country,
            "season": lg.season,
            "type": lg.type,
            "is_active": lg.is_active,
            "has_standings": lg.has_standings,
            "has_statistics": lg.has_statistics,
            "has_odds": lg.has_odds,
            "has_injuries": lg.has_injuries,
            "has_predictions": lg.has_predictions,
        })

    return {"count": len(items), "leagues": items}


@router.put("/leagues/{league_id}")
async def update_league(league_id: int, is_active: bool, db: AsyncSession = Depends(get_db)):
    """Enable/disable league."""
    league = await db.get(League, league_id)
    if not league:
        raise HTTPException(status_code=404, detail="League not found")

    league.is_active = is_active
    await db.commit()
    return {"status": "updated", "league_id": league_id, "is_active": is_active}
