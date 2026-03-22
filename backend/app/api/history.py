from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.database import get_db
from app.models.fixture import Fixture
from app.models.league import League
from app.models.prediction import Prediction
from app.models.team import Team

router = APIRouter()

PERIOD_MAP = {
    "yesterday": 1,
    "3d": 3,
    "7d": 7,
    "30d": 30,
}

PERIOD_LABELS = {
    "yesterday": "Yesterday",
    "3d": "Last 3 Days",
    "7d": "Last 7 Days",
    "30d": "Last 30 Days",
    "all": "All Time",
}


def _resolve_dates(
    period: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
) -> tuple[Optional[date], Optional[date], str]:
    """Return (start_date, end_date, label)."""
    today = date.today()

    if date_from or date_to:
        start = date.fromisoformat(date_from) if date_from else None
        end = date.fromisoformat(date_to) if date_to else today
        label = "Custom Range"
        return start, end, label

    if period == "all":
        return None, None, PERIOD_LABELS["all"]

    days = PERIOD_MAP.get(period or "7d", 7)
    effective_period = period or "7d"
    start = today - timedelta(days=days)
    return start, today, PERIOD_LABELS.get(effective_period, f"Last {days} Days")


@router.get("/history")
async def get_prediction_history(
    period: Optional[str] = Query(None, pattern="^(yesterday|3d|7d|30d|all)$"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    market: Optional[str] = Query(None, pattern="^(dc|ou15|ou25|ou35|all)$"),
    value_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    start_date, end_date, period_label = _resolve_dates(period, date_from, date_to)

    HomeTeam = aliased(Team, flat=True)
    AwayTeam = aliased(Team, flat=True)

    # Build base conditions
    conditions = []
    if start_date:
        conditions.append(Fixture.date >= start_date)
    if end_date:
        conditions.append(Fixture.date <= end_date)
    if value_only:
        conditions.append(Prediction.is_value_bet == True)  # noqa: E712
    if market and market != "all":
        conditions.append(Prediction.market == market)
    else:
        # Show all value-bet markets
        conditions.append(Prediction.market.in_(["dc", "ou15", "ou25", "ou35"]))

    # --- Settled bets (FT fixtures with is_correct evaluated) ---
    settled_q = (
        select(
            Prediction,
            Fixture.id.label("fix_id"),
            Fixture.date.label("fix_date"),
            Fixture.kickoff_time,
            Fixture.status,
            Fixture.score_home_ft,
            Fixture.score_away_ft,
            HomeTeam.name.label("home_team"),
            AwayTeam.name.label("away_team"),
            League.name.label("league_name"),
        )
        .join(Fixture, Prediction.fixture_id == Fixture.id)
        .join(HomeTeam, Fixture.home_team_id == HomeTeam.id)
        .join(AwayTeam, Fixture.away_team_id == AwayTeam.id)
        .join(League, Fixture.league_id == League.id)
        .where(
            Fixture.status == "FT",
            Prediction.is_correct.isnot(None),
            *conditions,
        )
        .order_by(Fixture.date.desc(), Fixture.kickoff_time.desc())
    )
    settled_result = await db.execute(settled_q)
    settled_rows = settled_result.all()

    # --- Pending bets (today's unfinished fixtures) ---
    today = date.today()
    include_pending = (end_date is None or end_date >= today) and (
        start_date is None or start_date <= today
    )

    pending_rows = []
    if include_pending:
        pending_conditions = [c for c in conditions]  # copy
        pending_q = (
            select(
                Prediction,
                Fixture.id.label("fix_id"),
                Fixture.date.label("fix_date"),
                Fixture.kickoff_time,
                Fixture.status,
                Fixture.score_home_ft,
                Fixture.score_away_ft,
                HomeTeam.name.label("home_team"),
                AwayTeam.name.label("away_team"),
                League.name.label("league_name"),
            )
            .join(Fixture, Prediction.fixture_id == Fixture.id)
            .join(HomeTeam, Fixture.home_team_id == HomeTeam.id)
            .join(AwayTeam, Fixture.away_team_id == AwayTeam.id)
            .join(League, Fixture.league_id == League.id)
            .where(
                Fixture.status != "FT",
                Fixture.date == today,
                Prediction.is_correct.is_(None),
                *pending_conditions,
            )
            .order_by(Fixture.kickoff_time.asc())
        )
        pending_result = await db.execute(pending_q)
        pending_rows = pending_result.all()

    # --- Build response ---
    # Summary stats (settled only)
    total_bets = len(settled_rows)
    correct = sum(1 for r in settled_rows if r[0].is_correct)
    hit_rate = round(correct / total_bets * 100, 1) if total_bets else 0.0
    total_profit = round(
        sum(
            (r[0].best_odd - 1.0) if r[0].is_correct else -1.0
            for r in settled_rows
            if r[0].best_odd is not None
        ),
        1,
    )
    total_staked = total_bets
    roi = round(total_profit / total_staked * 100, 1) if total_staked else 0.0
    avg_edge = round(
        sum(r[0].edge or 0 for r in settled_rows) / total_bets * 100, 1
    ) if total_bets else 0.0
    avg_confidence = round(
        sum(r[0].confidence_score for r in settled_rows) / total_bets
    ) if total_bets else 0

    # By market
    by_market: dict = {}
    for r in settled_rows:
        p = r[0]
        m = p.market
        if m not in by_market:
            by_market[m] = {"bets": 0, "correct": 0, "profit": 0.0}
        by_market[m]["bets"] += 1
        if p.is_correct:
            by_market[m]["correct"] += 1
        by_market[m]["profit"] += (p.best_odd - 1.0) if p.is_correct else -1.0
    for m in by_market:
        b = by_market[m]
        b["hit_rate"] = round(b["correct"] / b["bets"] * 100, 1) if b["bets"] else 0
        b["profit"] = round(b["profit"], 1)

    # Group by fixture (settled + pending)
    all_rows = list(settled_rows) + list(pending_rows)
    fixture_map: dict = {}
    for r in all_rows:
        pred = r[0]
        fix_id = r.fix_id
        if fix_id not in fixture_map:
            score = None
            if r.score_home_ft is not None and r.score_away_ft is not None:
                score = f"{r.score_home_ft}-{r.score_away_ft}"
            kickoff_str = ""
            if r.kickoff_time:
                kickoff_str = r.kickoff_time.strftime("%H:%M")
            fixture_map[fix_id] = {
                "fixture_id": fix_id,
                "date": str(r.fix_date),
                "kickoff": kickoff_str,
                "home_team": r.home_team,
                "away_team": r.away_team,
                "league": r.league_name,
                "score": score,
                "status": r.status,
                "predictions": [],
            }

        profit = None
        if pred.is_correct is not None and pred.best_odd is not None:
            profit = round((pred.best_odd - 1.0) if pred.is_correct else -1.0, 2)

        fixture_map[fix_id]["predictions"].append({
            "market": pred.market,
            "selection": pred.selection,
            "blended_probability": round(pred.blended_probability * 100, 1),
            "best_odd": pred.best_odd,
            "best_bookmaker": pred.best_bookmaker,
            "edge": round(pred.edge * 100, 1) if pred.edge else None,
            "confidence": pred.confidence_score,
            "is_value_bet": pred.is_value_bet,
            "is_correct": pred.is_correct,
            "profit": profit,
        })

    # Sort fixtures: pending first (today), then settled by date desc
    fixtures_list = sorted(
        fixture_map.values(),
        key=lambda f: (
            0 if f["status"] != "FT" else 1,
            f["date"],
        ),
        reverse=True,
    )
    # Within settled, date desc is already handled. Pending go first.
    # Actually, let's sort pending at top, then settled by date desc
    pending_fixtures = [f for f in fixtures_list if f["status"] != "FT"]
    settled_fixtures = [f for f in fixtures_list if f["status"] == "FT"]
    fixtures_list = pending_fixtures + settled_fixtures

    return {
        "summary": {
            "total_bets": total_bets,
            "correct": correct,
            "hit_rate": hit_rate,
            "total_profit": total_profit,
            "roi": roi,
            "avg_edge": avg_edge,
            "avg_confidence": avg_confidence,
            "date_from": str(start_date) if start_date else None,
            "date_to": str(end_date) if end_date else None,
            "period_label": period_label,
        },
        "by_market": by_market,
        "fixtures": fixtures_list,
    }
