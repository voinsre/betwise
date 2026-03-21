"""
Syncs Pinnacle pre-match odds from OddsPapi into the Odds table.

Flow:
1. OddsPapiClient.get_odds_by_tournaments() -> raw Pinnacle odds
2. Match to API-Football fixture via FixtureMatcher
3. Upsert into Odds table with bookmaker_name="Pinnacle"

Called daily by Celery task sync_pinnacle_odds.
Read by predict_fixture() via get_pinnacle_odds_for_fixture().
"""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fixture import Fixture
from app.models.odds import Odds
from app.services.fixture_matcher import FixtureMatcher
from app.services.league_config import LEAGUES, get_oddspapi_tournament_ids_in_season
from app.services.oddspapi_client import OddsPapiClient

logger = logging.getLogger(__name__)

# OddsPapi market IDs -> our market codes.
# Discovered via GET /v4/markets?sportId=10 on 2026-03-21.
ODDSPAPI_MARKET_MAP = {
    "101902": {
        "market": "dc",
        "outcomes": {"101902": "1X", "101903": "12", "101904": "X2"},
    },
    "108": {
        "market": "ou15",
        "outcomes": {"108": "Over 1.5", "109": "Under 1.5"},
    },
    "1010": {
        "market": "ou25",
        "outcomes": {"1010": "Over 2.5", "1011": "Under 2.5"},
    },
    "1012": {
        "market": "ou35",
        "outcomes": {"1012": "Over 3.5", "1013": "Under 3.5"},
    },
}

# Reverse lookup: tournament_id -> api_football_league_id
_TOURNAMENT_TO_LEAGUE = {
    league.oddspapi_tournament_id: league.api_football_id
    for league in LEAGUES
    if league.oddspapi_tournament_id > 0
}


async def sync_pinnacle_odds(session: AsyncSession):
    """Daily task: Fetch Pinnacle pre-match odds and store in Odds table."""
    client = OddsPapiClient()
    matcher = FixtureMatcher()
    await matcher.load_team_cache(session)

    tournament_ids = get_oddspapi_tournament_ids_in_season()
    if not tournament_ids:
        logger.info("No in-season tournaments for Pinnacle sync")
        await client.close()
        return

    # Batch tournament IDs (max 5 per request to avoid rate limits)
    BATCH_SIZE = 5
    all_odds_data = []
    for i in range(0, len(tournament_ids), BATCH_SIZE):
        batch = tournament_ids[i:i + BATCH_SIZE]
        try:
            batch_data = await client.get_odds_by_tournaments(batch)
            if isinstance(batch_data, list):
                all_odds_data.extend(batch_data)
            logger.info("Fetched odds for tournaments %s: %d fixtures", batch, len(batch_data) if isinstance(batch_data, list) else 0)
        except Exception as e:
            logger.error("OddsPapi batch failed for %s: %s", batch, e)
        if i + BATCH_SIZE < len(tournament_ids):
            await asyncio.sleep(2)

    synced = 0
    skipped = 0
    now = datetime.now(timezone.utc)

    for fixture_data in all_odds_data:
        pinnacle_data = fixture_data.get("bookmakerOdds", {}).get("pinnacle", {})
        if not pinnacle_data.get("bookmakerIsActive"):
            continue

        # Extract start date for fixture matching
        start_time = fixture_data.get("startTime", "")[:10]
        try:
            match_date = date.fromisoformat(start_time)
        except ValueError:
            continue

        # Map tournament -> league
        tournament_id = fixture_data.get("tournamentId")
        league_id = _TOURNAMENT_TO_LEAGUE.get(tournament_id)
        if not league_id:
            continue

        # Get participant IDs for team matching
        p1_id = fixture_data.get("participant1Id")
        p2_id = fixture_data.get("participant2Id")

        # Find matching fixture in our DB
        fixtures_result = await session.execute(
            select(Fixture).where(
                Fixture.league_id == league_id,
                Fixture.date >= match_date - timedelta(days=1),
                Fixture.date <= match_date + timedelta(days=1),
                Fixture.status == "NS",
            )
        )
        candidate_fixtures = fixtures_result.scalars().all()

        # Match by team IDs (via team source mapping)
        matched_fixture = None
        for f in candidate_fixtures:
            home_op = matcher._team_cache.get(f.home_team_id)
            away_op = matcher._team_cache.get(f.away_team_id)
            if home_op == p1_id and away_op == p2_id:
                matched_fixture = f
                break

        if not matched_fixture:
            skipped += 1
            continue

        # Extract and upsert Pinnacle odds
        markets = pinnacle_data.get("markets", {})
        for market_id_str, market_data in markets.items():
            if market_id_str not in ODDSPAPI_MARKET_MAP:
                continue

            mapping = ODDSPAPI_MARKET_MAP[market_id_str]
            our_market = mapping["market"]
            outcomes = market_data.get("outcomes", {})

            for outcome_id_str, outcome_data in outcomes.items():
                our_label = mapping["outcomes"].get(outcome_id_str)
                if not our_label:
                    continue

                players = outcome_data.get("players", {})
                player_data = players.get("0", {})
                if not player_data.get("active"):
                    continue

                price = player_data.get("price")
                if not price or price <= 1.0:
                    continue

                # Upsert into Odds table
                existing = (await session.execute(
                    select(Odds).where(
                        Odds.fixture_id == matched_fixture.id,
                        Odds.market == our_market,
                        Odds.label == our_label,
                        Odds.bookmaker_name == "Pinnacle",
                    )
                )).scalar_one_or_none()

                if existing:
                    existing.value = price
                    existing.implied_probability = 1.0 / price
                    existing.fetched_at = now
                else:
                    session.add(Odds(
                        fixture_id=matched_fixture.id,
                        market=our_market,
                        label=our_label,
                        value=price,
                        implied_probability=1.0 / price,
                        bookmaker_name="Pinnacle",
                        bookmaker_id=0,
                        fetched_at=now,
                    ))
                synced += 1

    await session.commit()
    await client.close()
    logger.info("Pinnacle sync: %d odds upserted, %d fixtures unmatched", synced, skipped)


async def get_pinnacle_odds_for_fixture(session: AsyncSession, fixture_id: int) -> dict:
    """
    Retrieve stored Pinnacle odds for a fixture.
    Returns dict like {"dc_1x": 1.35, "ou25_over_2.5": 2.10, ...}
    Called by predict_fixture() for edge calculation.
    """
    result = await session.execute(
        select(Odds).where(
            Odds.fixture_id == fixture_id,
            Odds.bookmaker_name == "Pinnacle",
        )
    )
    pinnacle_odds = {}
    for row in result.scalars().all():
        key = _pinnacle_key(row.market, row.label)
        pinnacle_odds[key] = row.value
    return pinnacle_odds


def _pinnacle_key(market_code: str, label: str) -> str:
    """
    Builds a consistent lookup key for any market/label combo.
    Examples:
        ("ou25", "Over 2.5")  -> "ou25_over_2.5"
        ("ou15", "Under 1.5") -> "ou15_under_1.5"
        ("dc", "1X")          -> "dc_1x"
        ("dc", "12")          -> "dc_12"
    """
    return f"{market_code}_{label}".lower().replace(" ", "_")
