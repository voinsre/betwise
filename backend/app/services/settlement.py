"""Settlement service — Phase 10.

Core settlement logic: evaluates prediction correctness against actual
fixture results, logs accuracy, and settles tickets. No Celery dependency.
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.fixture import Fixture
from app.models.model_accuracy import ModelAccuracy
from app.models.prediction import Prediction
from app.models.ticket import Ticket
from app.services.data_sync import DataSyncService

logger = logging.getLogger(__name__)

FLAT_STAKE = 10.0  # simulated flat stake per bet


# ── Result evaluation helpers ────────────────────────────────────

def evaluate_prediction(pred: Prediction, fixture: Fixture) -> bool | None:
    """
    Determine if a prediction was correct based on actual scores.
    Returns True (correct), False (incorrect), or None (can't evaluate).
    """
    h_ft = fixture.score_home_ft
    a_ft = fixture.score_away_ft
    h_ht = fixture.score_home_ht
    a_ht = fixture.score_away_ht

    if h_ft is None or a_ft is None:
        return None

    market = pred.market
    selection = pred.selection

    if market == "1x2":
        if h_ft > a_ft:
            actual = "Home"
        elif h_ft == a_ft:
            actual = "Draw"
        else:
            actual = "Away"
        return selection == actual

    elif market == "ou25":
        total = h_ft + a_ft
        if selection == "Over 2.5":
            return total > 2.5
        elif selection == "Under 2.5":
            return total < 2.5

    elif market == "btts":
        both_scored = h_ft > 0 and a_ft > 0
        if selection == "Yes":
            return both_scored
        elif selection == "No":
            return not both_scored

    elif market == "dc":
        if h_ft > a_ft:
            actual_results = {"1X", "12"}
        elif h_ft == a_ft:
            actual_results = {"1X", "X2"}
        else:
            actual_results = {"12", "X2"}
        return selection in actual_results

    elif market == "htft":
        if h_ht is None or a_ht is None:
            return None
        if h_ht > a_ht:
            ht_code = "1"
        elif h_ht == a_ht:
            ht_code = "X"
        else:
            ht_code = "2"
        if h_ft > a_ft:
            ft_code = "1"
        elif h_ft == a_ft:
            ft_code = "X"
        else:
            ft_code = "2"
        actual = f"{ht_code}/{ft_code}"
        return selection == actual

    return None


# ── Core settlement logic ────────────────────────────────────────

async def settle_fixtures_for_date(
    target_date: date,
    session_factory: async_sessionmaker,
    sync_service: DataSyncService,
) -> dict:
    """
    Full settlement pipeline for a given date.
    Returns summary dict with counts and accuracy.
    """
    # 1. Re-sync today's fixtures to get latest scores/statuses
    logger.info("Step 1: Re-syncing fixtures for %s to get final scores...", target_date)
    await sync_service.sync_fixtures_for_date(target_date.isoformat())

    # 2. Load all FT fixtures for the date
    async with session_factory() as session:
        result = await session.execute(
            select(Fixture).where(
                Fixture.date == target_date,
                Fixture.status == "FT",
            )
        )
        finished_fixtures = list(result.scalars().all())

    if not finished_fixtures:
        logger.info("No finished (FT) fixtures found for %s", target_date)
        return {
            "date": str(target_date),
            "fixtures_settled": 0,
            "message": "No FT fixtures found",
        }

    logger.info("Found %d FT fixtures for %s", len(finished_fixtures), target_date)
    fixture_ids = [f.id for f in finished_fixtures]
    fixture_map = {f.id: f for f in finished_fixtures}

    # 3. Sync fixture statistics + update team last20
    logger.info("Step 2: Syncing fixture stats and updating team last20...")
    for fx in finished_fixtures:
        try:
            await sync_service.sync_fixture_statistics(fx.id)
        except Exception as e:
            logger.warning("Failed to sync stats for fixture %d: %s", fx.id, e)

        try:
            await sync_service.sync_team_last20(fx.home_team_id, fx.league_id, fx.season)
            await sync_service.sync_team_last20(fx.away_team_id, fx.league_id, fx.season)
        except Exception as e:
            logger.warning("Failed to update last20 for fixture %d teams: %s", fx.id, e)

    # 4. Load all predictions for settled fixtures
    async with session_factory() as session:
        pred_result = await session.execute(
            select(Prediction).where(Prediction.fixture_id.in_(fixture_ids))
        )
        predictions = list(pred_result.scalars().all())

    logger.info("Step 3: Evaluating %d predictions across %d fixtures...", len(predictions), len(finished_fixtures))

    # 5. Evaluate each prediction
    market_stats: dict[str, dict] = defaultdict(lambda: {
        "total": 0, "correct": 0, "edges": [], "confidences": [],
        "staked": 0.0, "returned": 0.0,
    })

    settled_count = 0
    correct_count = 0

    for pred in predictions:
        fixture = fixture_map.get(pred.fixture_id)
        if not fixture:
            continue

        is_correct = evaluate_prediction(pred, fixture)
        if is_correct is None:
            continue

        settled_count += 1
        market_key = pred.market
        stats = market_stats[market_key]
        stats["total"] += 1
        stats["edges"].append(pred.edge)
        stats["confidences"].append(pred.confidence_score)

        if pred.is_value_bet:
            stats["staked"] += FLAT_STAKE
            if is_correct:
                stats["returned"] += FLAT_STAKE * pred.best_odd

        if is_correct:
            correct_count += 1
            stats["correct"] += 1

    # 6. Write model_accuracy rows
    logger.info("Step 4: Writing accuracy records for %d markets...", len(market_stats))
    async with session_factory() as session:
        for market, stats in market_stats.items():
            total = stats["total"]
            correct = stats["correct"]
            accuracy = (correct / total * 100) if total > 0 else 0.0
            avg_edge = sum(stats["edges"]) / len(stats["edges"]) if stats["edges"] else 0.0
            avg_conf = int(sum(stats["confidences"]) / len(stats["confidences"])) if stats["confidences"] else 0
            staked = stats["staked"]
            returned = stats["returned"]
            pl = returned - staked
            roi = (pl / staked * 100) if staked > 0 else 0.0

            acc = ModelAccuracy(
                date=target_date,
                market=market,
                league_id=None,
                total_predictions=total,
                correct_predictions=correct,
                accuracy_pct=round(accuracy, 2),
                avg_edge=round(avg_edge, 4),
                avg_confidence=avg_conf,
                total_staked=round(staked, 2),
                total_returned=round(returned, 2),
                profit_loss=round(pl, 2),
                roi_pct=round(roi, 2),
            )
            session.add(acc)

        await session.commit()

    # 7. Settle tickets
    logger.info("Step 5: Settling tickets...")
    tickets_settled = await _settle_tickets(session_factory, fixture_map, predictions)

    summary = {
        "date": str(target_date),
        "fixtures_settled": len(finished_fixtures),
        "predictions_evaluated": settled_count,
        "predictions_correct": correct_count,
        "overall_accuracy": round(correct_count / settled_count * 100, 1) if settled_count > 0 else 0.0,
        "tickets_settled": tickets_settled,
        "per_market": {},
    }

    for market, stats in market_stats.items():
        total = stats["total"]
        correct = stats["correct"]
        staked = stats["staked"]
        returned = stats["returned"]
        summary["per_market"][market] = {
            "total": total,
            "correct": correct,
            "accuracy_pct": round(correct / total * 100, 1) if total > 0 else 0.0,
            "value_bets_staked": round(staked, 2),
            "value_bets_returned": round(returned, 2),
            "value_bets_pl": round(returned - staked, 2),
            "roi_pct": round((returned - staked) / staked * 100, 1) if staked > 0 else 0.0,
        }

    logger.info("Settlement complete: %s", summary)
    return summary


async def _settle_tickets(
    session_factory: async_sessionmaker,
    fixture_map: dict[int, Fixture],
    predictions: list[Prediction],
) -> int:
    """Check pending tickets, settle any where all legs are now FT."""
    pred_lookup: dict[tuple, Prediction] = {}
    for p in predictions:
        pred_lookup[(p.fixture_id, p.market, p.selection)] = p

    settled_count = 0

    async with session_factory() as session:
        result = await session.execute(
            select(Ticket).where(Ticket.status == "pending")
        )
        tickets = list(result.scalars().all())

        for ticket in tickets:
            games = ticket.games or []
            all_settled = True
            all_won = True

            for game in games:
                fid = game.get("fixture_id")
                if fid not in fixture_map:
                    all_settled = False
                    break

                fixture = fixture_map[fid]
                market = game.get("market", "")
                selection = game.get("selection", "")

                pred = pred_lookup.get((fid, market, selection))
                if pred:
                    is_correct = evaluate_prediction(pred, fixture)
                else:
                    dummy = Prediction(
                        fixture_id=fid, market=market, selection=selection,
                        poisson_probability=0, blended_probability=0,
                        best_odd=game.get("odd", 1.0), best_bookmaker="",
                        implied_probability=0, edge=0, expected_value=0,
                        confidence_score=0,
                    )
                    is_correct = evaluate_prediction(dummy, fixture)

                if is_correct is None:
                    all_settled = False
                    break
                if not is_correct:
                    all_won = False

            if all_settled:
                if all_won:
                    ticket.status = "won"
                    ticket.profit_loss = round(
                        FLAT_STAKE * ticket.combined_odds - FLAT_STAKE, 2
                    )
                else:
                    ticket.status = "lost"
                    ticket.profit_loss = -FLAT_STAKE

                ticket.settled_at = datetime.now(timezone.utc)
                settled_count += 1

        await session.commit()

    return settled_count
