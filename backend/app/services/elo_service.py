"""ClubElo CSV sync — downloads daily Elo ratings and upserts into DB.

Source: http://api.clubelo.com/YYYY-MM-DD (no auth, CSV format)
"""

import csv
import io
import logging
from datetime import date

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CLUBELO_API = "http://api.clubelo.com"


async def fetch_elo_csv(date_str: str) -> list[dict]:
    """Download ClubElo CSV for a given date, return list of dicts."""
    url = f"{CLUBELO_API}/{date_str}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    reader = csv.DictReader(io.StringIO(resp.text))
    rows = []
    for row in reader:
        try:
            rows.append({
                "team_name": row["Club"],
                "elo": float(row["Elo"]),
                "country": row.get("Country", None),
            })
        except (KeyError, ValueError) as e:
            logger.warning("Skipping malformed ClubElo row: %s — %s", row, e)
    return rows


async def sync_elo_ratings(session: AsyncSession, target_date: date | None = None):
    """Fetch today's ClubElo CSV and upsert into elo_ratings table."""
    target = target_date or date.today()
    date_str = target.isoformat()

    rows = await fetch_elo_csv(date_str)
    if not rows:
        logger.warning("No Elo rows fetched for %s", date_str)
        return 0

    # Bulk upsert via ON CONFLICT
    upsert_sql = text("""
        INSERT INTO elo_ratings (team_name, date, elo, country)
        VALUES (:team_name, :date, :elo, :country)
        ON CONFLICT ON CONSTRAINT uq_elo_team_date
        DO UPDATE SET elo = EXCLUDED.elo, country = EXCLUDED.country
    """)

    values = [
        {"team_name": r["team_name"], "date": target, "elo": r["elo"], "country": r["country"]}
        for r in rows
    ]
    await session.execute(upsert_sql, values)
    await session.commit()

    logger.info("Synced %d Elo ratings for %s", len(values), date_str)
    return len(values)


async def populate_clubelo_mappings(session: AsyncSession):
    """Match ClubElo team names to API-Football teams and populate team_source_mappings."""
    from app.services.team_name_mapper import TeamNameMapper
    from app.models.source_mapping import TeamSourceMapping
    from sqlalchemy import select

    mapper = await TeamNameMapper.from_db(session)
    elo_rows = await fetch_elo_csv(date.today().isoformat())

    matched = 0
    for row in elo_rows:
        clubelo_name = row["team_name"]
        team_id = mapper.match(clubelo_name)
        if not team_id:
            continue

        # Check if mapping exists
        existing = (await session.execute(
            select(TeamSourceMapping)
            .where(TeamSourceMapping.api_football_team_id == team_id)
        )).scalar_one_or_none()

        if existing:
            existing.clubelo_name = clubelo_name
        else:
            session.add(TeamSourceMapping(
                api_football_team_id=team_id,
                canonical_name=clubelo_name,
                clubelo_name=clubelo_name,
            ))
        matched += 1

    await session.commit()
    logger.info("Populated %d ClubElo mappings out of %d teams", matched, len(elo_rows))
    return matched
