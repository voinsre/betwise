"""On-demand live fixture status check with Redis caching.

Fetches live fixture statuses from API-Football and caches the set of
upcoming (NS) fixture IDs in Redis.  Used by the chat layer to filter
out finished/in-progress games so users only see bettable fixtures.
"""

import json
import logging
from datetime import date

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.models.fixture import Fixture
from app.services.api_football import APIFootballClient

logger = logging.getLogger(__name__)

# Lazy singleton Redis client
_redis: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


async def get_upcoming_fixture_ids(
    target_date: date,
    session_factory: async_sessionmaker,
) -> set[int]:
    """
    Return fixture IDs for games that haven't started yet on target_date.

    1. Check Redis cache (key: "fixtures:{date}:upcoming_ids", TTL 600s)
    2. On miss: call API-Football GET /fixtures?date={date}&timezone=UTC
    3. Filter to status "NS" (Not Started), extract IDs, cache in Redis
    4. On API failure: fall back to DB WHERE status='NS' AND date=target_date
    """
    cache_key = f"fixtures:{target_date}:upcoming_ids"

    # 1. Check Redis cache
    try:
        r = await _get_redis()
        cached = await r.get(cache_key)
        if cached is not None:
            logger.debug("Redis HIT for %s", cache_key)
            return set(json.loads(cached))
    except Exception as e:
        logger.warning("Redis read failed: %s", e)

    # 2. Call API-Football
    try:
        async with APIFootballClient() as client:
            fixtures = await client.get_fixtures_by_date(
                str(target_date), timezone="UTC"
            )

        # 3. Filter NS only, extract IDs
        upcoming_ids: set[int] = set()
        for f in fixtures:
            status = f.get("fixture", {}).get("status", {}).get("short", "")
            if status == "NS":
                fid = f.get("fixture", {}).get("id")
                if fid:
                    upcoming_ids.add(fid)

        logger.info(
            "API-Football: %d total fixtures for %s, %d upcoming (NS)",
            len(fixtures), target_date, len(upcoming_ids),
        )

        # Cache in Redis
        try:
            r = await _get_redis()
            await r.set(cache_key, json.dumps(list(upcoming_ids)), ex=600)
        except Exception as e:
            logger.warning("Redis write failed: %s", e)

        return upcoming_ids

    except Exception as e:
        logger.warning("API-Football call failed, falling back to DB: %s", e)

    # 4. Fallback: DB query
    async with session_factory() as session:
        q = select(Fixture.id).where(
            Fixture.date == target_date,
            Fixture.status == "NS",
        )
        result = await session.execute(q)
        ids = {row[0] for row in result.all()}
        logger.info("DB fallback: %d upcoming fixtures for %s", len(ids), target_date)
        return ids
