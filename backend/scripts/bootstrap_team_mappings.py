"""
One-time script: Populate team_source_mappings table.
For each team in our DB (from API-Football), try to find the OddsPapi participant ID.

Strategy:
1. For each of our 25 leagues, call OddsPapi GET /v4/participants?tournamentId={id}
2. Extract participant names and IDs from participant data
3. Fuzzy-match against our teams table using rapidfuzz
4. Store confirmed matches in team_source_mappings
5. Print unmatched teams for manual review

Run from backend/:
    python scripts/bootstrap_team_mappings.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://betwise:changeme@localhost:5432/betwise",
)

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert

try:
    from rapidfuzz import fuzz
except ImportError:
    print("ERROR: rapidfuzz not installed. Run: pip install rapidfuzz>=3.0.0")
    sys.exit(1)

from app.models.team import Team
from app.models.source_mapping import TeamSourceMapping
from app.services.league_config import LEAGUES
from app.services.oddspapi_client import OddsPapiClient


MATCH_THRESHOLD = 80  # Minimum fuzzy match score to auto-accept


def normalize_name(name: str) -> str:
    """Normalize team name for fuzzy matching."""
    name = name.strip()
    # Remove common suffixes
    for suffix in [" FC", " CF", " SC", " FK", " IF", " BK", " SK"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
    return name


async def main():
    db_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    client = OddsPapiClient()

    print("=" * 70)
    print("  BOOTSTRAP TEAM MAPPINGS — API-Football <-> OddsPapi")
    print("=" * 70)

    total_matched = 0
    total_unmatched = 0
    unmatched_teams = []

    for league in LEAGUES:
        if league.oddspapi_tournament_id <= 0:
            continue

        print(f"\n--- {league.name} (API-Football={league.api_football_id}, OddsPapi={league.oddspapi_tournament_id}) ---")

        # Get our teams for this league from DB
        async with session_factory() as session:
            result = await session.execute(
                select(Team).where(Team.league_id == league.api_football_id)
            )
            our_teams = list(result.scalars().all())

        if not our_teams:
            print(f"  No teams in DB for league {league.api_football_id}")
            continue

        # Get OddsPapi participants for this tournament
        try:
            participants = await client.get_participants(league.oddspapi_tournament_id)
        except Exception as e:
            print(f"  ERROR getting participants: {e}")
            continue

        if isinstance(participants, dict):
            participants = participants.get("data", participants.get("participants", []))

        print(f"  Our teams: {len(our_teams)}, OddsPapi participants: {len(participants)}")

        # Build OddsPapi lookup: name -> (id, name)
        op_lookup = {}
        for p in participants:
            if isinstance(p, dict):
                pid = p.get("participantId") or p.get("id")
                pname = p.get("participantName") or p.get("name", "")
                if pid and pname:
                    op_lookup[normalize_name(pname)] = (pid, pname)

        # Match each of our teams
        matched = 0
        for team in our_teams:
            our_name = normalize_name(team.name)

            best_score = 0
            best_match = None
            best_op_name = None

            for op_norm, (op_id, op_original) in op_lookup.items():
                score = fuzz.ratio(our_name.lower(), op_norm.lower())
                if score > best_score:
                    best_score = score
                    best_match = (op_id, op_original)
                    best_op_name = op_norm

            if best_score >= MATCH_THRESHOLD and best_match:
                async with session_factory() as session:
                    stmt = pg_insert(TeamSourceMapping).values(
                        api_football_team_id=team.id,
                        canonical_name=team.name,
                        oddspapi_participant_id=best_match[0],
                        oddspapi_name=best_match[1],
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["api_football_team_id"],
                        set_={
                            "oddspapi_participant_id": best_match[0],
                            "oddspapi_name": best_match[1],
                        },
                    ) if False else stmt  # No unique constraint yet, just insert
                    await session.execute(stmt)
                    await session.commit()
                matched += 1
                total_matched += 1
                if best_score < 95:
                    print(f"  ~ {team.name} -> {best_match[1]} (score={best_score})")
            else:
                total_unmatched += 1
                unmatched_teams.append((league.name, team.name, best_match[1] if best_match else "?", best_score))
                print(f"  X {team.name} -> best: {best_match[1] if best_match else '?'} (score={best_score})")

        print(f"  Matched: {matched}/{len(our_teams)}")

    await client.close()
    await engine.dispose()

    print("\n" + "=" * 70)
    print(f"  DONE: {total_matched} matched, {total_unmatched} unmatched")
    print("=" * 70)

    if unmatched_teams:
        print("\n  UNMATCHED TEAMS (need manual mapping):")
        for league_name, team_name, best, score in unmatched_teams:
            print(f"    [{league_name}] {team_name} -> best: {best} (score={score})")


if __name__ == "__main__":
    asyncio.run(main())
