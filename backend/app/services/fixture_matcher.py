"""
Matches fixtures between API-Football and OddsPapi.
Tournament mapping: hardcoded in league_config.py (no DB lookup needed).
Team mapping: loaded from team_source_mappings table.
Match logic: same tournament + same date (+-1 day) + same home/away teams.
"""
from datetime import date
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.source_mapping import TeamSourceMapping
from app.services.league_config import get_league_by_api_id


class FixtureMatcher:
    def __init__(self):
        self._team_cache = {}  # api_football_team_id -> oddspapi_participant_id

    async def load_team_cache(self, session: AsyncSession):
        result = await session.execute(select(TeamSourceMapping))
        for tsm in result.scalars().all():
            if tsm.oddspapi_participant_id:
                self._team_cache[tsm.api_football_team_id] = tsm.oddspapi_participant_id

    def get_oddspapi_tournament_id(self, api_football_league_id: int) -> Optional[int]:
        """Reads from hardcoded league_config -- no DB needed."""
        league = get_league_by_api_id(api_football_league_id)
        return league.oddspapi_tournament_id if league and league.oddspapi_tournament_id > 0 else None

    def match_fixture(self, api_football_league_id, match_date, home_team_id,
                      away_team_id, oddspapi_fixtures) -> Optional[str]:
        target_home = self._team_cache.get(home_team_id)
        target_away = self._team_cache.get(away_team_id)
        if not target_home or not target_away:
            return None

        for fixture in oddspapi_fixtures:
            fixture_date = fixture.get("startTime", "")[:10]
            try:
                f_date = date.fromisoformat(fixture_date)
            except (ValueError, TypeError):
                continue
            if abs((f_date - match_date).days) > 1:
                continue
            if (fixture.get("participant1Id") == target_home and
                fixture.get("participant2Id") == target_away):
                return fixture.get("fixtureId") or fixture.get("id")
        return None
