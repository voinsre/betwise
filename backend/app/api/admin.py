import asyncio
import hmac
import logging
from datetime import date, datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import get_current_admin
from app.config import settings
from app.database import async_session, get_db
from app.models.fixture import Fixture
from app.models.league import League
from app.models.model_accuracy import ModelAccuracy
from app.models.prediction import Prediction
from app.models.team_last20 import TeamLast20
from app.services.api_football import APIFootballClient
from app.services.data_sync import DataSyncService
from app.services.prediction_engine import PredictionEngine
from app.services.settlement import settle_fixtures_for_date

logger = logging.getLogger(__name__)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


class SettingsUpdate(BaseModel):
    kelly_multiplier: float | None = Field(None, ge=0.01, le=1.0)
    min_confidence: int | None = Field(None, ge=0, le=100)
    min_edge: float | None = Field(None, ge=0.0, le=1.0)
    odds_min: float | None = Field(None, ge=1.0, le=50.0)
    odds_max: float | None = Field(None, ge=1.0, le=50.0)


@router.post("/login")
@limiter.limit("5/minute")
async def admin_login(request_body: LoginRequest, request: Request):
    """Admin login — returns JWT."""
    user_ok = hmac.compare_digest(request_body.username, settings.ADMIN_USERNAME)
    pass_ok = hmac.compare_digest(request_body.password, settings.ADMIN_PASSWORD)
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    payload = {
        "sub": request_body.username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRY_HOURS),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return {"token": token}


@router.get("/dashboard")
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
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
async def get_data_health(db: AsyncSession = Depends(get_db), _admin: dict = Depends(get_current_admin)):
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
async def get_accuracy(
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
    days: int = Query(30, ge=0, le=3650),
    filter_date: str | None = Query(None, alias="date"),
):
    """Model accuracy with multi-range summaries and optional date filtering."""
    today = date.today()

    # Fetch all rows — table is small (~5 markets × days of data)
    result = await db.execute(
        select(ModelAccuracy).order_by(ModelAccuracy.date.desc())
    )
    all_rows = result.scalars().all()

    # Compute date subsets for summaries
    cutoff_7 = today - timedelta(days=7)
    cutoff_30 = today - timedelta(days=30)
    cutoff_90 = today - timedelta(days=90)

    rows_7d = [r for r in all_rows if r.date >= cutoff_7]
    rows_30d = [r for r in all_rows if r.date >= cutoff_30]
    rows_90d = [r for r in all_rows if r.date >= cutoff_90]

    # Build daily detail rows (filtered by days param or specific date)
    if filter_date:
        target = date.fromisoformat(filter_date)
        detail_rows = [r for r in all_rows if r.date == target]
    elif days > 0:
        cutoff = today - timedelta(days=days)
        detail_rows = [r for r in all_rows if r.date >= cutoff]
    else:
        detail_rows = all_rows

    items = []
    for r in detail_rows:
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

    def _summarize(rows_list):
        by_market = {}
        for r in rows_list:
            m = r.market
            if m not in by_market:
                by_market[m] = {
                    "total": 0, "correct": 0, "staked": 0.0, "returned": 0.0,
                    "edge_sum": 0.0, "conf_sum": 0.0,
                }
            by_market[m]["total"] += r.total_predictions
            by_market[m]["correct"] += r.correct_predictions
            by_market[m]["staked"] += r.total_staked
            by_market[m]["returned"] += r.total_returned
            by_market[m]["edge_sum"] += r.avg_edge * r.total_predictions
            by_market[m]["conf_sum"] += r.avg_confidence * r.total_predictions

        summary = {}
        for m, s in by_market.items():
            pl = s["returned"] - s["staked"]
            summary[m] = {
                "total_predictions": s["total"],
                "correct_predictions": s["correct"],
                "accuracy_pct": round(s["correct"] / s["total"] * 100, 1) if s["total"] > 0 else 0.0,
                "avg_edge": round(s["edge_sum"] / s["total"], 4) if s["total"] > 0 else 0.0,
                "avg_confidence": round(s["conf_sum"] / s["total"]) if s["total"] > 0 else 0,
                "total_staked": round(s["staked"], 2),
                "total_returned": round(s["returned"], 2),
                "profit_loss": round(pl, 2),
                "roi_pct": round(pl / s["staked"] * 100, 1) if s["staked"] > 0 else 0.0,
            }
        return summary

    return {
        "accuracy": items,
        "summary_7d": _summarize(rows_7d),
        "summary_30d": _summarize(rows_30d),
        "summary_90d": _summarize(rows_90d),
        "summary_all": _summarize(all_rows),
        "date_range": {
            "earliest": str(all_rows[-1].date) if all_rows else None,
            "latest": str(all_rows[0].date) if all_rows else None,
            "total_days": len(set(r.date for r in all_rows)),
        },
    }


@router.get("/accuracy/{market}")
async def get_market_accuracy(market: str, db: AsyncSession = Depends(get_db), _admin: dict = Depends(get_current_admin)):
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
@limiter.limit("2/hour")
async def trigger_backfill(league_id: int, season: int, request: Request, _admin: dict = Depends(get_current_admin)):
    """Trigger historical backfill (placeholder — needs Celery)."""
    return {"status": "queued", "league_id": league_id, "season": season}


@router.post("/retrain")
@limiter.limit("1/hour")
async def trigger_retrain(request: Request, _admin: dict = Depends(get_current_admin)):
    """Trigger ML retrain (placeholder — needs Celery)."""
    return {"status": "queued", "message": "ML retrain task queued"}


async def _run_pipeline():
    """Full pipeline: sync fixtures → sync data → sync odds → run predictions."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    client = APIFootballClient(api_key=settings.API_FOOTBALL_KEY)

    try:
        sync = DataSyncService(session_factory, client)
        today = date.today()
        tomorrow = today + timedelta(days=1)

        # Step 1: Sync fixtures
        logger.info("Pipeline: syncing fixtures for %s and %s", today, tomorrow)
        await sync.sync_fixtures_for_date(today.isoformat())
        await sync.sync_fixtures_for_date(tomorrow.isoformat())

        # Step 2: Sync fixture data
        async with session_factory() as session:
            result = await session.execute(
                select(Fixture).where(Fixture.date == today)
            )
            fixtures = result.scalars().all()

        logger.info("Pipeline: syncing data for %d fixtures", len(fixtures))
        for fx in fixtures:
            try:
                await sync.sync_team_last20(fx.home_team_id, fx.league_id, fx.season)
                await sync.sync_team_last20(fx.away_team_id, fx.league_id, fx.season)
                await sync.sync_head_to_head(fx.home_team_id, fx.away_team_id)
                await sync.sync_injuries(fx.id)
                await sync.sync_standings(fx.league_id, fx.season)
            except Exception as e:
                logger.error("Pipeline: fixture %d data sync failed: %s", fx.id, e)

        # Step 3: Sync odds
        async with session_factory() as session:
            result = await session.execute(
                select(Fixture).where(Fixture.date == today, Fixture.status == "NS")
            )
            ns_fixtures = result.scalars().all()

        logger.info("Pipeline: syncing odds for %d NS fixtures", len(ns_fixtures))
        for fx in ns_fixtures:
            try:
                await sync.sync_odds(fx.id)
            except Exception as e:
                logger.error("Pipeline: odds sync failed for fixture %d: %s", fx.id, e)

        # Step 4: Run predictions
        logger.info("Pipeline: running predictions")
        pred_engine = PredictionEngine(session_factory)
        pred_engine.load_models()

        async with session_factory() as session:
            result = await session.execute(
                select(Fixture).where(
                    Fixture.date == today, Fixture.status.in_(["NS", "TBD"])
                )
            )
            pred_fixtures = list(result.scalars().all())

        total_preds = 0
        total_value = 0
        for fx in pred_fixtures:
            try:
                preds = await pred_engine.predict_fixture(fx.id)
                total_preds += len(preds)
                total_value += sum(1 for p in preds if p.is_value_bet)
            except Exception as e:
                logger.error("Pipeline: prediction failed for fixture %d: %s", fx.id, e)

        logger.info(
            "Pipeline complete: %d predictions, %d value bets across %d fixtures",
            total_preds, total_value, len(pred_fixtures),
        )
    except Exception:
        logger.exception("Pipeline FAILED")
    finally:
        await client.close()
        await engine.dispose()


@router.post("/run-pipeline")
@limiter.limit("2/hour")
async def run_pipeline(
    request: Request,
    background_tasks: BackgroundTasks,
    _admin: dict = Depends(get_current_admin),
):
    """Trigger full daily pipeline: sync → odds → predictions. Runs in background."""
    background_tasks.add_task(_run_pipeline)
    return {"status": "started", "message": "Pipeline running in background — check logs for progress"}


async def _run_settlement(target_date: date):
    """Run settlement for a specific date."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    client = APIFootballClient(api_key=settings.API_FOOTBALL_KEY)

    try:
        sync = DataSyncService(session_factory, client)
        summary = await settle_fixtures_for_date(target_date, session_factory, sync)
        logger.info("Settlement for %s complete: %s", target_date, summary)
    except Exception:
        logger.exception("Settlement FAILED for %s", target_date)
    finally:
        await client.close()
        await engine.dispose()


@router.post("/settle/{settle_date}")
@limiter.limit("5/hour")
async def trigger_settlement(
    settle_date: str,
    request: Request,
    background_tasks: BackgroundTasks,
    _admin: dict = Depends(get_current_admin),
):
    """Trigger settlement for a specific date. Use for missed/failed settlement runs."""
    try:
        target = date.fromisoformat(settle_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    if target > date.today():
        raise HTTPException(status_code=400, detail="Cannot settle future dates.")

    background_tasks.add_task(_run_settlement, target)
    return {"status": "started", "date": settle_date, "message": f"Settlement for {settle_date} running in background"}


@router.put("/settings")
async def update_settings(request: SettingsUpdate, _admin: dict = Depends(get_current_admin)):
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
async def list_leagues(db: AsyncSession = Depends(get_db), _admin: dict = Depends(get_current_admin)):
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
async def update_league(league_id: int, is_active: bool, db: AsyncSession = Depends(get_db), _admin: dict = Depends(get_current_admin)):
    """Enable/disable league."""
    league = await db.get(League, league_id)
    if not league:
        raise HTTPException(status_code=404, detail="League not found")

    league.is_active = is_active
    await db.commit()
    return {"status": "updated", "league_id": league_id, "is_active": is_active}
