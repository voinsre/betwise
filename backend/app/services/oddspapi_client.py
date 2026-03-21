import httpx
from typing import List
from app.config import settings

BASE_URL = "https://api.oddspapi.io/v4"
BOOKMAKER = "pinnacle"


class OddsPapiClient:
    def __init__(self):
        self.api_key = settings.ODDSPAPI_API_KEY
        self.client = httpx.AsyncClient(timeout=30)

    async def _get(self, endpoint: str, params: dict = None) -> dict:
        params = params or {}
        params["apiKey"] = self.api_key
        resp = await self.client.get(f"{BASE_URL}{endpoint}", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_tournaments(self, sport_id: int = 10) -> list:
        return await self._get("/tournaments", {"sportId": sport_id})

    async def get_participants(self, tournament_id: int) -> list:
        return await self._get("/participants", {"tournamentId": tournament_id})

    async def get_markets(self, sport_id: int = 10) -> list:
        return await self._get("/markets", {"sportId": sport_id})

    async def get_odds_by_tournaments(self, tournament_ids: List[int]) -> list:
        ids_str = ",".join(str(t) for t in tournament_ids)
        return await self._get("/odds-by-tournaments", {
            "bookmaker": BOOKMAKER, "tournamentIds": ids_str,
        })

    async def get_historical_odds(self, fixture_id: str) -> dict:
        return await self._get("/historical-odds", {
            "fixtureId": fixture_id, "bookmakers": BOOKMAKER,
        })

    async def get_fixtures(self, tournament_id: int) -> list:
        return await self._get("/fixtures", {"tournamentId": tournament_id, "statusId": 3})

    async def close(self):
        await self.client.aclose()
