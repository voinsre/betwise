import asyncio
import logging
import time

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Target leagues we track
TARGET_LEAGUE_IDS = {39, 140, 135, 78, 61, 2, 3, 88, 94, 179, 203, 144, 40, 136, 79}

BACKFILL_SEASONS = [2023, 2024, 2025]


class APIFootballError(Exception):
    """Raised when the API returns an error response."""

    def __init__(self, message: str, errors: dict | list | None = None):
        super().__init__(message)
        self.errors = errors


class APIFootballClient:
    """Async HTTP client for API-Football v3 with rate limiting and retries."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        max_concurrent: int = 10,
        max_retries: int = 3,
    ):
        self.api_key = api_key or settings.API_FOOTBALL_KEY
        self.base_url = (base_url or settings.API_FOOTBALL_BASE_URL).rstrip("/")
        self.max_retries = max_retries
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"x-apisports-key": self.api_key},
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(self, endpoint: str, params: dict | None = None) -> dict:
        """
        Core request method with rate limiting, retries, and error handling.
        Returns the full parsed JSON response.
        """
        client = await self._get_client()
        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            async with self._semaphore:
                start = time.monotonic()
                try:
                    resp = await client.get(endpoint, params=params)
                    elapsed = time.monotonic() - start

                    logger.info(
                        "API-Football %s %s -> %s (%.2fs)",
                        endpoint,
                        params or {},
                        resp.status_code,
                        elapsed,
                    )

                    if resp.status_code == 429:
                        wait = 2 ** attempt
                        logger.warning("Rate limited (429), retrying in %ds", wait)
                        await asyncio.sleep(wait)
                        last_exc = APIFootballError("Rate limited")
                        continue

                    if resp.status_code >= 500:
                        wait = 2 ** attempt
                        logger.warning("Server error %d, retrying in %ds", resp.status_code, wait)
                        await asyncio.sleep(wait)
                        last_exc = APIFootballError(f"Server error {resp.status_code}")
                        continue

                    resp.raise_for_status()
                    data = resp.json()

                    # Check API-level errors
                    errors = data.get("errors")
                    if errors and (isinstance(errors, list) and len(errors) > 0 or isinstance(errors, dict) and len(errors) > 0):
                        raise APIFootballError(f"API error on {endpoint}: {errors}", errors=errors)

                    return data

                except httpx.HTTPStatusError as exc:
                    last_exc = exc
                    logger.error("HTTP error %s on %s: %s", exc.response.status_code, endpoint, exc)
                    break  # non-retryable status code
                except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                    elapsed = time.monotonic() - start
                    wait = 2 ** attempt
                    logger.warning("Connection error on %s (%.2fs), retry %d in %ds: %s", endpoint, elapsed, attempt, wait, exc)
                    last_exc = exc
                    await asyncio.sleep(wait)

        raise APIFootballError(f"Failed after {self.max_retries} attempts on {endpoint}") from last_exc

    async def _get(self, endpoint: str, params: dict | None = None) -> list[dict]:
        """Make a request and return the 'response' array, handling pagination."""
        data = await self._request(endpoint, params)
        results = data.get("response", [])

        # Handle pagination
        paging = data.get("paging", {})
        current_page = paging.get("current", 1)
        total_pages = paging.get("total", 1)

        while current_page < total_pages:
            current_page += 1
            next_params = {**(params or {}), "page": current_page}
            next_data = await self._request(endpoint, next_params)
            results.extend(next_data.get("response", []))
            paging = next_data.get("paging", {})
            total_pages = paging.get("total", total_pages)

        return results

    # ── Leagues ──────────────────────────────────────────────

    async def get_leagues(self) -> list[dict]:
        """GET /leagues — all available leagues."""
        return await self._get("/leagues")

    # ── Fixtures ─────────────────────────────────────────────

    async def get_fixtures_by_date(self, date: str, timezone: str | None = None) -> list[dict]:
        """GET /fixtures?date={YYYY-MM-DD}&timezone={tz}"""
        params: dict[str, str] = {"date": date}
        if timezone:
            params["timezone"] = timezone
        return await self._get("/fixtures", params)

    async def get_fixtures_by_league_season(
        self, league_id: int, season: int, status: str = "FT"
    ) -> list[dict]:
        """GET /fixtures?league={id}&season={season}&status={status} — for historical backfill."""
        return await self._get("/fixtures", {"league": league_id, "season": season, "status": status})

    async def get_fixture_statistics(self, fixture_id: int) -> list[dict]:
        """GET /fixtures/statistics?fixture={id}"""
        return await self._get("/fixtures/statistics", {"fixture": fixture_id})

    # ── Teams ────────────────────────────────────────────────

    async def get_team_fixtures(self, team_id: int, season: int, last: int = 20) -> list[dict]:
        """GET /fixtures?team={id}&season={season}&last={last} — last N games for a team."""
        return await self._get("/fixtures", {"team": team_id, "season": season, "last": last})

    async def get_team_statistics(self, team_id: int, league_id: int, season: int) -> dict:
        """GET /teams/statistics?team={id}&league={league_id}&season={season}"""
        results = await self._get("/teams/statistics", {"team": team_id, "league": league_id, "season": season})
        return results[0] if results else {}

    # ── Head-to-Head ─────────────────────────────────────────

    async def get_head_to_head(self, team1_id: int, team2_id: int, last: int = 20) -> list[dict]:
        """GET /fixtures/headtohead?h2h={team1}-{team2}&last={last}"""
        h2h = f"{team1_id}-{team2_id}"
        return await self._get("/fixtures/headtohead", {"h2h": h2h, "last": last})

    # ── Odds ─────────────────────────────────────────────────

    async def get_odds(self, fixture_id: int) -> list[dict]:
        """GET /odds?fixture={id} — odds from all bookmakers for all markets."""
        return await self._get("/odds", {"fixture": fixture_id})

    # ── Standings ────────────────────────────────────────────

    async def get_standings(self, league_id: int, season: int) -> list[dict]:
        """GET /standings?league={id}&season={season}"""
        return await self._get("/standings", {"league": league_id, "season": season})

    # ── Injuries ─────────────────────────────────────────────

    async def get_injuries(self, fixture_id: int) -> list[dict]:
        """GET /injuries?fixture={id}"""
        return await self._get("/injuries", {"fixture": fixture_id})

    # ── Context manager ──────────────────────────────────────

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()
