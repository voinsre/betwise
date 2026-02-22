"""
Quick smoke test for the API-Football client.
Run from the backend/ directory:
    python -m scripts.test_api_client
Or directly:
    python scripts/test_api_client.py
"""

import asyncio
import json
import os
import sys

# Add backend/ to path so we can import app modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

# Load .env from project root
env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
load_dotenv(env_path)

from app.services.api_football import APIFootballClient, TARGET_LEAGUE_IDS


def pp(obj, max_depth=3):
    """Pretty-print a dict/list, truncated for readability."""
    print(json.dumps(obj, indent=2, default=str)[:2000])


async def main():
    api_key = os.getenv("API_FOOTBALL_KEY", "")
    if not api_key:
        print("ERROR: API_FOOTBALL_KEY not set in .env")
        sys.exit(1)

    print(f"Using API key: {api_key[:6]}...{api_key[-4:]}")
    print("=" * 60)

    async with APIFootballClient(api_key=api_key) as client:
        # ── Test 1: get_leagues ─────────────────────────────
        print("\n[1] get_leagues()")
        leagues = await client.get_leagues()
        print(f"    Total leagues returned: {len(leagues)}")

        # Show which of our target leagues were found
        target_found = []
        for lg in leagues:
            league_info = lg.get("league", {})
            if league_info.get("id") in TARGET_LEAGUE_IDS:
                target_found.append(f"    - {league_info['id']:>4}  {league_info['name']}")
        print(f"    Our target leagues found: {len(target_found)}/15")
        for line in target_found[:5]:
            print(line)
        if len(target_found) > 5:
            print(f"    ... and {len(target_found) - 5} more")

        # ── Test 2: get_fixtures_by_date ────────────────────
        today = "2026-02-22"
        print(f"\n[2] get_fixtures_by_date('{today}')")
        fixtures = await client.get_fixtures_by_date(today)
        print(f"    Fixtures today: {len(fixtures)}")

        # Filter to our target leagues
        target_fixtures = [
            f for f in fixtures
            if f.get("league", {}).get("id") in TARGET_LEAGUE_IDS
        ]
        print(f"    In our target leagues: {len(target_fixtures)}")

        if target_fixtures:
            for fx in target_fixtures[:5]:
                fi = fx["fixture"]
                teams = fx["teams"]
                lg = fx["league"]
                print(
                    f"    - [{fi['id']}] {teams['home']['name']} vs {teams['away']['name']}"
                    f"  ({lg['name']}, {fi['status']['short']})"
                )
            if len(target_fixtures) > 5:
                print(f"    ... and {len(target_fixtures) - 5} more")

        # ── Test 3: get_odds on first fixture ───────────────
        pick = target_fixtures[0] if target_fixtures else (fixtures[0] if fixtures else None)
        if pick:
            fid = pick["fixture"]["id"]
            home = pick["teams"]["home"]["name"]
            away = pick["teams"]["away"]["name"]
            print(f"\n[3] get_odds(fixture_id={fid})  ({home} vs {away})")
            odds_data = await client.get_odds(fid)
            if odds_data:
                bookmakers = odds_data[0].get("bookmakers", [])
                print(f"    Bookmakers returned: {len(bookmakers)}")
                if bookmakers:
                    bk = bookmakers[0]
                    print(f"    First bookmaker: {bk['name']}")
                    for bet in bk.get("bets", [])[:4]:
                        vals = ", ".join(
                            f"{v['value']}={v['odd']}" for v in bet.get("values", [])[:4]
                        )
                        print(f"      {bet['name']}: {vals}")
            else:
                print("    No odds data available for this fixture.")
        else:
            print("\n[3] Skipped — no fixtures found to test odds on.")

    print("\n" + "=" * 60)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
