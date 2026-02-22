"""Test settlement logic — Phase 10.

Finds FT fixtures (today or historical) and runs the settlement pipeline.
Prints detailed results: which fixtures settled, prediction accuracy, P&L.
"""

import asyncio
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://betwise:BetWise2026Secure@localhost:5432/betwise",
)

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.fixture import Fixture
from app.models.model_accuracy import ModelAccuracy
from app.models.prediction import Prediction
from app.models.team import Team
from app.services.api_football import APIFootballClient
from app.services.data_sync import DataSyncService
from app.services.settlement import (
    evaluate_prediction,
    settle_fixtures_for_date,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_settlement")


async def main():
    db_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    client = APIFootballClient(api_key=settings.API_FOOTBALL_KEY)
    sync = DataSyncService(session_factory, client)

    try:
        today = date.today()

        # ── Step 1: Check for FT fixtures today ──
        print(f"\n{'='*60}")
        print(f"  BetWise Settlement Test — {today}")
        print(f"{'='*60}\n")

        async with session_factory() as session:
            # Count fixtures by status for today
            status_result = await session.execute(
                select(Fixture.status, func.count(Fixture.id))
                .where(Fixture.date == today)
                .group_by(Fixture.status)
            )
            status_counts = dict(status_result.all())

        print("Today's fixture status breakdown:")
        for status, count in sorted(status_counts.items()):
            print(f"  {status}: {count}")
        print()

        ft_today = status_counts.get("FT", 0)
        target_date = today

        if ft_today == 0:
            # Try yesterday, then find any date with FT fixtures + predictions
            print("No FT fixtures today. Searching for recent date with FT fixtures + predictions...\n")

            async with session_factory() as session:
                result = await session.execute(
                    select(Fixture.date, func.count(Fixture.id))
                    .where(
                        Fixture.status == "FT",
                        Fixture.date >= today - timedelta(days=30),
                    )
                    .group_by(Fixture.date)
                    .order_by(Fixture.date.desc())
                    .limit(5)
                )
                date_counts = result.all()

            if not date_counts:
                print("No FT fixtures found in last 30 days with predictions.")
                print("Running settlement on today's date anyway (will sync fresh data)...\n")
            else:
                # Check which dates have predictions
                for d, count in date_counts:
                    async with session_factory() as session:
                        pred_count = await session.execute(
                            select(func.count(Prediction.id))
                            .join(Fixture)
                            .where(Fixture.date == d, Fixture.status == "FT")
                        )
                        pc = pred_count.scalar() or 0
                        print(f"  {d}: {count} FT fixtures, {pc} predictions")
                        if pc > 0:
                            target_date = d
                            break

                if target_date == today and date_counts:
                    # Use most recent date even without predictions — just test score sync
                    target_date = date_counts[0][0]

                print(f"\nUsing date: {target_date}\n")

        # ── Step 2: Show pre-settlement state ──
        async with session_factory() as session:
            pred_result = await session.execute(
                select(Prediction, Fixture, Team)
                .join(Fixture, Prediction.fixture_id == Fixture.id)
                .join(Team, Fixture.home_team_id == Team.id)
                .where(Fixture.date == target_date, Fixture.status == "FT")
                .order_by(Prediction.fixture_id, Prediction.market)
            )
            rows = pred_result.all()

            # Get away team names
            away_names = {}
            for _, fx, _ in rows:
                if fx.id not in away_names:
                    away_t = await session.get(Team, fx.away_team_id)
                    away_names[fx.id] = away_t.name if away_t else "?"

        if rows:
            print(f"Pre-settlement: {len(rows)} predictions on FT fixtures for {target_date}")

            # Preview some evaluations before running full settlement
            print(f"\n--- Preview: Evaluating predictions against actual scores ---\n")
            current_fixture = None
            preview_count = 0

            for pred, fx, home_team in rows:
                if current_fixture != fx.id:
                    current_fixture = fx.id
                    away = away_names.get(fx.id, "?")
                    print(f"\n  {home_team.name} {fx.score_home_ft}-{fx.score_away_ft} {away}"
                          f" (HT: {fx.score_home_ht}-{fx.score_away_ht})")

                is_correct = evaluate_prediction(pred, fx)
                mark = "✓" if is_correct else ("✗" if is_correct is False else "?")
                vb = " [VALUE]" if pred.is_value_bet else ""
                print(f"    {mark} {pred.market:5s} {pred.selection:12s} "
                      f"@{pred.best_odd:.2f}  conf={pred.confidence_score}  "
                      f"edge={pred.edge:+.1%}{vb}")
                preview_count += 1
                if preview_count >= 50:
                    print(f"\n    ... ({len(rows) - preview_count} more)")
                    break
        else:
            print(f"No predictions found for FT fixtures on {target_date}")
            print("Settlement will still run to sync scores and stats.\n")

        # ── Step 3: Run full settlement ──
        print(f"\n{'='*60}")
        print(f"  Running Settlement Pipeline for {target_date}")
        print(f"{'='*60}\n")

        summary = await settle_fixtures_for_date(target_date, session_factory, sync)

        # ── Step 4: Print results ──
        print(f"\n{'='*60}")
        print(f"  Settlement Results")
        print(f"{'='*60}\n")

        print(f"  Date:                {summary['date']}")
        print(f"  Fixtures settled:    {summary.get('fixtures_settled', 0)}")
        print(f"  Predictions eval'd:  {summary.get('predictions_evaluated', 0)}")
        print(f"  Predictions correct: {summary.get('predictions_correct', 0)}")
        print(f"  Overall accuracy:    {summary.get('overall_accuracy', 0):.1f}%")
        print(f"  Tickets settled:     {summary.get('tickets_settled', 0)}")

        per_market = summary.get("per_market", {})
        if per_market:
            print(f"\n  --- Per-Market Breakdown ---")
            print(f"  {'Market':<8} {'Total':>6} {'Correct':>8} {'Acc%':>6} {'Staked':>8} {'P&L':>8} {'ROI%':>6}")
            print(f"  {'-'*54}")
            for market, ms in sorted(per_market.items()):
                print(f"  {market:<8} {ms['total']:>6} {ms['correct']:>8} "
                      f"{ms['accuracy_pct']:>5.1f}% "
                      f"${ms['value_bets_staked']:>7.0f} "
                      f"${ms['value_bets_pl']:>7.2f} "
                      f"{ms['roi_pct']:>5.1f}%")

        # ── Step 5: Verify model_accuracy rows in DB ──
        async with session_factory() as session:
            acc_result = await session.execute(
                select(ModelAccuracy)
                .where(ModelAccuracy.date == target_date)
                .order_by(ModelAccuracy.market)
            )
            acc_rows = list(acc_result.scalars().all())

        if acc_rows:
            print(f"\n  --- model_accuracy table (date={target_date}) ---")
            for a in acc_rows:
                print(f"  {a.market:<8} total={a.total_predictions} correct={a.correct_predictions} "
                      f"acc={a.accuracy_pct:.1f}% P&L=${a.profit_loss:.2f} ROI={a.roi_pct:.1f}%")
        else:
            print(f"\n  No model_accuracy rows written (possibly no predictions to evaluate)")

        print(f"\n{'='*60}")
        print(f"  Settlement test complete!")
        print(f"{'='*60}\n")

        # ── Step 6: Dry-run evaluation test using historical FT fixtures ──
        print(f"\n{'='*60}")
        print(f"  Dry-Run Evaluation Test (historical FT fixtures)")
        print(f"{'='*60}\n")

        await _dry_run_eval(session_factory)

    finally:
        await client.close()
        await engine.dispose()


async def _dry_run_eval(session_factory):
    """Test evaluate_prediction logic using FT fixtures from the backfill.

    Creates synthetic Prediction objects for each market and checks
    the evaluation against actual scores.
    """
    async with session_factory() as session:
        # Grab 5 random FT fixtures with HT and FT scores
        result = await session.execute(
            select(Fixture, Team)
            .join(Team, Fixture.home_team_id == Team.id)
            .where(
                Fixture.status == "FT",
                Fixture.score_home_ft.isnot(None),
                Fixture.score_away_ft.isnot(None),
                Fixture.score_home_ht.isnot(None),
            )
            .order_by(Fixture.date.desc())
            .limit(5)
        )
        rows = result.all()

        away_names = {}
        for fx, _ in rows:
            if fx.id not in away_names:
                away_t = await session.get(Team, fx.away_team_id)
                away_names[fx.id] = away_t.name if away_t else "?"

    total_tests = 0
    total_passed = 0

    for fx, home_team in rows:
        h_ft = fx.score_home_ft
        a_ft = fx.score_away_ft
        h_ht = fx.score_home_ht
        a_ht = fx.score_away_ht
        away = away_names.get(fx.id, "?")

        print(f"  {home_team.name} {h_ft}-{a_ft} {away} (HT: {h_ht}-{a_ht}) — fixture {fx.id}")

        # Determine correct answers
        # 1X2
        if h_ft > a_ft:
            correct_1x2 = "Home"
        elif h_ft == a_ft:
            correct_1x2 = "Draw"
        else:
            correct_1x2 = "Away"

        # OU25
        total_goals = h_ft + a_ft
        correct_ou = "Over 2.5" if total_goals > 2.5 else "Under 2.5"

        # BTTS
        correct_btts = "Yes" if (h_ft > 0 and a_ft > 0) else "No"

        # HT/FT
        ht_code = "1" if h_ht > a_ht else ("X" if h_ht == a_ht else "2")
        ft_code = "1" if h_ft > a_ft else ("X" if h_ft == a_ft else "2")
        correct_htft = f"{ht_code}/{ft_code}"

        tests = [
            ("1x2", correct_1x2, True),
            ("1x2", "Draw" if correct_1x2 != "Draw" else "Home", False),
            ("ou25", correct_ou, True),
            ("btts", correct_btts, True),
            ("htft", correct_htft, True),
        ]

        for market, selection, expected in tests:
            pred = Prediction(
                fixture_id=fx.id, market=market, selection=selection,
                poisson_probability=0.5, blended_probability=0.5,
                best_odd=2.0, best_bookmaker="Test",
                implied_probability=0.5, edge=0.0, expected_value=0.0,
                confidence_score=50,
            )
            result = evaluate_prediction(pred, fx)
            passed = result == expected
            total_tests += 1
            if passed:
                total_passed += 1
            mark = "PASS" if passed else "FAIL"
            print(f"    [{mark}] {market:5s} {selection:12s} -> {result} (expected {expected})")

        print()

    print(f"  Evaluation tests: {total_passed}/{total_tests} passed\n")


if __name__ == "__main__":
    asyncio.run(main())
